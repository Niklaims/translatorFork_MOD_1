# gemini_translator/ui/dialogs/glossary_dialogs/paste_terms.py
"""Массовая вставка терминов в имеющийся глоссарий.

Сценарий общий для вкладки «Глоссарий» и Менеджера глоссариев: карточка
ввода → Мастер импорта → сравнение с глоссарием (plan_glossary_paste) →
карточка подтверждения, если вставка расходится с глоссарием → итог.
Как записать изменения, решает вызывающий — см. ``run_glossary_paste``.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gemini_translator.ui import theme_manager
from gemini_translator.ui.overlay_host import exec_dialog
from gemini_translator.utils.glossary_tools import plan_glossary_paste
from .import_master import ImporterWizardDialog


def wizard_input_for_pasted_text(text):
    """Аргументы ``(initial_data, is_from_table)`` Мастера импорта для
    вставленного текста. JSON мастер разбирает сам. Остальное получает
    готовыми строками, разрезанными по табуляции, — так столбцы из
    электронной таблицы приходят разложенными, а обычный текст не вызывает
    окна «Ошибка в формате JSON», как при импорте TXT-файла."""
    if text.lstrip()[:1] in ("[", "{"):
        return text, False
    return [line.split("\t") for line in text.splitlines() if line.strip()], True


class PasteTermsInputDialog(QDialog):
    """Карточка ввода: сюда вставляют или набирают список терминов."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вставка терминов")
        self.resize(640, 440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>Вставка терминов</h3>"))

        hint = QLabel(
            "Подойдут строки вида «оригинал = перевод», столбцы, скопированные "
            "из таблицы, и JSON программы. На следующем шаге Мастер импорта "
            "разложит строки на оригинал, перевод и примечание."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme_manager.color('text_muted')};")
        layout.addWidget(hint)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("林动 = Линь Дун\n武祖 = Боевой Предок")
        label = QLabel("Термины, по одному на строку:")
        label.setBuddy(self.text_edit)
        layout.addWidget(label)
        layout.addWidget(self.text_edit, 1)

        buttons = QDialogButtonBox()
        self.next_button = buttons.addButton(
            "Разобрать строки", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_button = buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        self.next_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.text_edit.textChanged.connect(self._update_next_button)
        self._update_next_button()

    def text(self) -> str:
        return self.text_edit.toPlainText()

    def _update_next_button(self):
        self.next_button.setEnabled(bool(self.text().strip()))


class PasteConflictsDialog(QDialog):
    """Карточка подтверждения: какие термины глоссария вставка заменит.

    Галочки стоят у всех строк. «Заменить отмеченные» кладёт выбранные
    расхождения в ``accepted_conflicts`` и принимает карточку; «Добавить
    только новые» закрывает её кодом ``KEEP_EXISTING``; «Отмена» — reject.
    """

    KEEP_EXISTING = 2

    def __init__(self, conflicts, new_terms=0, parent=None):
        super().__init__(parent)
        self.conflicts = list(conflicts)
        self.accepted_conflicts = []
        self.setWindowTitle("Заменить термины в глоссарии?")
        self.resize(980, 540)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>Заменить термины в глоссарии?</h3>"))
        explanation = QLabel(
            "Эти термины уже есть в глоссарии, но во вставке у них другой перевод "
            "или примечание. Заменятся только отмеченные строки; пустое поле во "
            "вставке старое значение не стирает."
        )
        if new_terms:
            explanation.setText(
                explanation.text()
                + " Новые термины из вставки добавятся и при замене, и без неё."
            )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(len(self.conflicts), 5)
        self.table.setHorizontalHeaderLabels([
            "Оригинал", "Перевод сейчас", "Перевод станет",
            "Примечание сейчас", "Примечание станет",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._fill_table()
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox()
        self.replace_button = buttons.addButton("", QDialogButtonBox.ButtonRole.AcceptRole)
        self.keep_button = buttons.addButton(
            f"Добавить только новые ({new_terms})", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.keep_button.setVisible(bool(new_terms))
        self.cancel_button = buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        self.replace_button.clicked.connect(self._replace_checked)
        self.keep_button.clicked.connect(lambda: self.done(self.KEEP_EXISTING))
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.table.itemChanged.connect(self._update_replace_button)
        self._update_replace_button()

    def _fill_table(self):
        muted = QColor(theme_manager.color("text_muted"))
        # Фон ячеек (BackgroundRole) стиль таблиц темы не рисует, поэтому
        # новое значение выделено цветом текста.
        changed = QColor(theme_manager.color("success_text"))
        for row, conflict in enumerate(self.conflicts):
            original = QTableWidgetItem(conflict.replacement["original"])
            original.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            original.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, original)

            for column, field in ((1, "rus"), (3, "note")):
                before = QTableWidgetItem(str(conflict.current.get(field) or ""))
                after = QTableWidgetItem(conflict.replacement[field])
                if after.text() != before.text():
                    font = before.font()
                    font.setStrikeOut(True)
                    before.setFont(font)
                    font = after.font()
                    font.setBold(True)
                    after.setFont(font)
                    after.setForeground(changed)
                else:
                    after.setForeground(muted)
                for item in (before, after):
                    item.setToolTip(item.text())
                self.table.setItem(row, column, before)
                self.table.setItem(row, column + 1, after)
        self.table.resizeRowsToContents()

    def _checked_rows(self):
        return [
            row for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def _update_replace_button(self, *_):
        count = len(self._checked_rows())
        self.replace_button.setText(f"Заменить отмеченные ({count})")
        self.replace_button.setEnabled(count > 0)

    def _replace_checked(self):
        self.accepted_conflicts = [self.conflicts[row] for row in self._checked_rows()]
        self.accept()


def glossary_paste_summary(plan, replaced: int) -> str:
    kept = plan.unchanged + len(plan.conflicts) - replaced
    lines = []
    if not plan.additions and not replaced:
        lines.append("Глоссарий не изменился.")
    if plan.additions:
        lines.append(f"Добавлено новых терминов: {len(plan.additions)}")
    if replaced:
        lines.append(f"Заменено: {replaced}")
    if kept:
        lines.append(f"Без изменений: {kept}")
    if plan.skipped:
        lines.append(f"Пропущено строк без оригинала: {plan.skipped}")
    return "\n".join(lines)


def run_glossary_paste(parent, existing_entries, apply_changes) -> None:
    """Проводит пользователя через вставку терминов в ``existing_entries``.

    ``apply_changes(plan, accepted_conflicts)`` вызывается, только если
    глоссарий действительно меняется: во вставке есть новые термины или
    пользователь принял замены. Индексы расхождений в плане указывают на
    ``existing_entries``.
    """
    input_dialog = PasteTermsInputDialog(parent)
    if exec_dialog(parent, input_dialog) != QDialog.DialogCode.Accepted:
        return

    initial_data, from_table = wizard_input_for_pasted_text(input_dialog.text())
    wizard = ImporterWizardDialog(
        initial_data=initial_data, is_from_table=from_table, parent=parent
    )
    if exec_dialog(parent, wizard) != QDialog.DialogCode.Accepted:
        return
    pasted_entries = wizard.get_glossary()
    if not pasted_entries:
        return  # мастер уже сообщил, что не извлёк ни одной записи

    plan = plan_glossary_paste(existing_entries, pasted_entries)
    accepted_conflicts = []
    if plan.conflicts:
        card = PasteConflictsDialog(plan.conflicts, new_terms=len(plan.additions), parent=parent)
        answer = exec_dialog(parent, card)
        if answer == QDialog.DialogCode.Accepted:
            accepted_conflicts = card.accepted_conflicts
        elif answer != PasteConflictsDialog.KEEP_EXISTING:
            return

    if plan.additions or accepted_conflicts:
        apply_changes(plan, accepted_conflicts)
    QMessageBox.information(
        parent, "Вставка терминов", glossary_paste_summary(plan, len(accepted_conflicts))
    )
