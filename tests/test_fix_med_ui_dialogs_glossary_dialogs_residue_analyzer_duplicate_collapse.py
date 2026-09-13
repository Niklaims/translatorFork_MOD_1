"""Регрессионный тест для ui-dialogs-glossary-b/bugs/6-residue-duplicate-collapse.

_get_entry_id идентифицировал запись глоссария кортежем (original, rus, note)
без учёта _db_id/позиции. get_current_glossary_state() строил словарь по
этому ключу, из-за чего две байт-в-байт идентичные строки глоссария
(original/rus/note совпадают, но это разные записи БД — PRIMARY KEY только
id, original/rus/note не уникальны) схлопывались в одну уже на этапе
построения текущего состояния, используемого во всех операциях диалога
(_display_details, _delete_entry, итоговый патч).

Первая версия исправления перешла на id(entry) как ключ. Это не пережило
ревью: записи кладутся в ячейки таблицы «Связанные записи» через
QTableWidgetItem.setData(UserRole, entry), PyQt6 конвертирует dict в
QVariantMap, и .data(UserRole) при КАЖДОМ чтении возвращает НОВЫЙ
Python-объект с тем же содержимым — id() у него уже другой при первой же
правке ячейки. Итоговое исправление — строковое поле "_residue_uid" ВНУТРИ
самого словаря (переживает QVariantMap), которое __init__ проставляет
исходным записям, а места, строящие "after"-состояние для существующей
записи, переносят дальше.

Тесты покрывают и прямые вызовы get_current_glossary_state()/_get_entry_id
(байт-в-байт дубликаты), и боевой путь через реальный QTableWidget
(_create_sub_entries_group + правка ячейки), где и ломалась identity-based
версия исправления.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

# ВАЖНО: gemini_translator.ui.widgets.ancestor_utils импортируется первым —
# это разрывает предсуществующий цикл импорта
# ui.widgets -> ui.dialogs.glossary -> ui.dialogs.glossary_dialogs.residue_analyzer,
# который иначе бросает ImportError при прямом импорте residue_analyzer как
# первого обращения к пакету (см. аналогичный порядок в
# tests/test_dedup_finding_ui_dialogs_glossary_b_design_1_residue_analyzer_owner_lookup_characterization.py).
# Сам цикл — отдельный, не относящийся к этой находке дефект структуры импортов.
from gemini_translator.ui.widgets.ancestor_utils import find_ancestor_by_class_name  # noqa: F401
from gemini_translator.ui.dialogs.glossary_dialogs.residue_analyzer import ResidueAnalyzerPage


class _ResidueSettingsStub:
    def get_last_word_exceptions_text(self):
        return " "


class ResidueDuplicateCollapseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_page(self, original_glossary_list):
        page = ResidueAnalyzerPage({}, original_glossary_list, _ResidueSettingsStub(), None)
        self.addCleanup(page.close)
        return page

    def test_two_byte_identical_entries_are_not_collapsed(self):
        """Две отдельные (разные объекты!) записи с одинаковыми
        original/rus/note не должны схлопываться в одну при построении
        текущего состояния глоссария."""
        entry_a = {"original": "Foo", "rus": "Фу", "note": ""}
        entry_b = {"original": "Foo", "rus": "Фу", "note": ""}  # отдельный объект, тот же контент
        self.assertIsNot(entry_a, entry_b)

        page = self._make_page([entry_a, entry_b])

        current_state = page.get_current_glossary_state()

        self.assertEqual(
            len(current_state), 2,
            "Обе байт-в-байт идентичные записи должны сохраниться в текущем "
            "состоянии глоссария, а не схлопнуться в одну",
        )

    def test_get_entry_id_distinguishes_identical_content_different_objects(self):
        """_get_entry_id должен различать две записи с одинаковым содержимым,
        если это разные объекты (разные строки БД)."""
        entry_a = {"original": "Foo", "rus": "Фу", "note": ""}
        entry_b = {"original": "Foo", "rus": "Фу", "note": ""}

        page = self._make_page([entry_a, entry_b])

        self.assertNotEqual(page._get_entry_id(entry_a), page._get_entry_id(entry_b))

    def test_delete_one_duplicate_leaves_the_other_untouched(self):
        """Удаление одной из двух идентичных записей не должно задевать
        вторую: после _delete_entry в патче должна остаться ровно одна
        запись на удаление, и итоговое состояние должно содержать одну
        оставшуюся запись."""
        entry_a = {"original": "Foo", "rus": "Фу", "note": ""}
        entry_b = {"original": "Foo", "rus": "Фу", "note": ""}

        page = self._make_page([entry_a, entry_b])
        # _delete_entry удаляет ВСЕ записи с тем же 'original' (так и задумано —
        # см. docstring кнопки "Удалить этот термин и все его дубликаты"),
        # поэтому проверяем через одиночную запись, чтобы изолировать сценарий.
        page.patch_list.append({"before": entry_a, "after": None})

        current_state = page.get_current_glossary_state()

        self.assertEqual(len(current_state), 1)
        self.assertIs(current_state[0], entry_b)

    def _get_sub_table(self, page, sub_entries, title="t"):
        group = page._create_sub_entries_group(title, sub_entries)
        self.addCleanup(group.deleteLater)
        table = group.findChild(QtWidgets.QTableWidget)
        self.assertIsNotNone(table)
        return table

    def test_sub_table_userrole_readback_loses_object_identity(self):
        """Характеризационная проверка самого механизма поломки: сначала
        убеждаемся, что PyQt6 действительно возвращает НОВЫЙ dict при чтении
        QTableWidgetItem.data(UserRole) — иначе следующие тесты этого файла
        не воспроизводили бы реальный дефект, найденный рецензентом."""
        entry = {"original": "Foo", "rus": "Фу", "note": ""}
        page = self._make_page([entry])

        table = self._get_sub_table(page, [{"type": "duplicate", "data": entry}])

        round_tripped = table.item(0, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        self.assertIsNot(
            round_tripped, entry,
            "Если это когда-нибудь перестанет быть так, ключ на id(entry) "
            "снова станет безопасным — но сейчас PyQt6 конвертирует dict в "
            "QVariantMap и материализует новый объект на каждом чтении",
        )
        self.assertEqual(round_tripped, entry)

    def test_sub_table_edit_does_not_create_phantom_duplicate(self):
        """Боевой путь: _create_sub_entries_group кладёт запись в
        QTableWidgetItem.setData(UserRole, entry) (строка 'duplicate' /
        'occurrence'), пользователь правит ячейку — get_current_glossary_state()
        не должна получить фантомную вторую запись (исходную, не найденную по
        идентификатору), а get_final_patch() не должна разрастаться при
        повторной правке той же строки."""
        entry = {"original": "Foo", "rus": "Фу", "note": ""}
        page = self._make_page([entry])

        table = self._get_sub_table(page, [{"type": "duplicate", "data": entry}])

        table.item(0, 2).setText("Фу eng")  # первая правка: перевод

        state_after_first_edit = page.get_current_glossary_state()
        self.assertEqual(
            len(state_after_first_edit), 1,
            "После правки ячейки должна остаться одна запись глоссария, а "
            "не исходная (нетронутая) плюс изменённая — фантомный дубликат",
        )
        self.assertEqual(state_after_first_edit[0]["rus"], "Фу eng")

        table.item(0, 3).setText("новое примечание")  # вторая правка: примечание

        self.assertEqual(
            len(page.get_final_patch()), 1,
            "Две последовательные правки одной и той же строки таблицы "
            "должны слиться в один элемент патча, а не породить второй, "
            "несливающийся (иначе первая правка молча теряется при "
            "применении патча — см. glossary.py::_apply_patch)",
        )
        final_state = page.get_current_glossary_state()
        self.assertEqual(len(final_state), 1)
        self.assertEqual(final_state[0]["rus"], "Фу eng")
        self.assertEqual(final_state[0]["note"], "новое примечание")

    def test_fragment_row_edit_does_not_create_phantom_duplicate(self):
        """Тот же сценарий для ветки 'fragment' (совпавший термин кладётся в
        UserRole матчем по all_originals_map, а не напрямую из item_info)."""
        entry = {"original": "Foo", "rus": "Фу", "note": ""}
        page = self._make_page([entry])

        table = self._get_sub_table(page, [{"type": "fragment", "data": "Foo"}])

        table.item(0, 2).setText("Фу eng")  # первая правка: перевод

        state_after_first_edit = page.get_current_glossary_state()
        self.assertEqual(
            len(state_after_first_edit), 1,
            "Правка перевода найденного по фрагменту термина не должна "
            "порождать фантомный дубликат исходной записи",
        )
        self.assertEqual(state_after_first_edit[0]["rus"], "Фу eng")

        table.item(0, 3).setText("новое примечание")  # вторая правка: примечание

        self.assertEqual(
            len(page.get_final_patch()), 1,
            "Две последовательные правки одной и той же строки-фрагмента "
            "должны слиться в один элемент патча",
        )
        final_state = page.get_current_glossary_state()
        self.assertEqual(len(final_state), 1)
        self.assertEqual(final_state[0]["rus"], "Фу eng")
        self.assertEqual(final_state[0]["note"], "новое примечание")


if __name__ == "__main__":
    unittest.main()
