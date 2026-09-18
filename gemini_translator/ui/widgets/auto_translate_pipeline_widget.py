# gemini_translator/ui/widgets/auto_translate_pipeline_widget.py

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer

from gemini_translator.ui import theme_manager
from gemini_translator.ui.widgets.toggle_switch_widget import ToggleSwitchWidget
from gemini_translator.ui.widgets.chapter_list_widget import (
    get_task_display_texts,
    get_task_status_display_info,
    get_task_status_tooltip,
)
from gemini_translator.utils.settings import SettingsManager
from gemini_translator.utils.epub_tools import extract_number_from_path

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _recolor_svg(svg_path: Path, color: str) -> QIcon:
    """Загрузить SVG и перекрасить stroke/fill в нужный цвет темы."""
    try:
        svg_text = svg_path.read_text(encoding="utf-8")
        svg_text = svg_text.replace("#6f7b88", color)
        renderer = QSvgRenderer(svg_text.encode("utf-8"))
        pixmap = QPixmap(QSize(16, 16))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon()


def _find_chapter_list_widget(parent):
    """Ищет ChapterListWidget вверх по иерархии родителей."""
    if parent is None:
        return None

    if isinstance(parent, AutoTranslatePipelineWidget):
        curr = parent.parent() if (hasattr(parent, "parent") and callable(parent.parent)) else None
    else:
        curr = parent

    while curr is not None:
        if hasattr(curr, "_mock_children"):
            if "chapter_widget" in curr._mock_children:
                return curr.chapter_widget
            if "chapter_list_widget" in curr._mock_children:
                return curr.chapter_list_widget
            if "task_management_widget" in curr._mock_children:
                tmw = curr.task_management_widget
                if hasattr(tmw, "_mock_children") and "chapter_list_widget" in tmw._mock_children:
                    return tmw.chapter_list_widget
                return getattr(tmw, "chapter_list_widget", None)
            return None

        if hasattr(curr, "chapter_widget"):
            cw = getattr(curr, "chapter_widget", None)
            if cw is not None and not isinstance(cw, AutoTranslatePipelineWidget):
                return cw

        if not isinstance(curr, AutoTranslatePipelineWidget):
            cw = getattr(curr, "chapter_list_widget", None)
            if cw and not isinstance(cw, AutoTranslatePipelineWidget):
                return cw
            tmw = getattr(curr, "task_management_widget", None)
            if tmw and hasattr(tmw, "chapter_list_widget") and tmw.chapter_list_widget:
                return tmw.chapter_list_widget

        curr = curr.parent() if (hasattr(curr, "parent") and callable(curr.parent)) else None
    return None


def _find_epub_path(parent) -> str:
    """Ищет путь к книге/EPUB вверх по иерархии родителей."""
    if parent is None:
        return ""
    if isinstance(parent, AutoTranslatePipelineWidget):
        curr = parent.parent() if (hasattr(parent, "parent") and callable(parent.parent)) else None
    else:
        curr = parent
    while curr is not None:
        if hasattr(curr, "_mock_children"):
            if "paths_widget" in curr._mock_children:
                pw = curr.paths_widget
                if hasattr(pw, "_file_path") and pw._file_path:
                    return str(pw._file_path)
            if "project_manager" in curr._mock_children:
                pm = curr.project_manager
                if hasattr(pm, "book_path") and pm.book_path:
                    return str(pm.book_path)
            return ""

        pw = getattr(curr, "paths_widget", None)
        if pw and hasattr(pw, "_file_path") and pw._file_path:
            return str(pw._file_path)
        pm = getattr(curr, "project_manager", None)
        if pm and hasattr(pm, "book_path") and pm.book_path:
            return str(pm.book_path)
        curr = curr.parent() if (hasattr(curr, "parent") and callable(curr.parent)) else None
    return ""


def _chapter_display_name(chapter_path: str, parent=None, epub_path=None) -> str:
    """Извлекает имя главы в том же формате, что и в списке задач (📄 HTML: basename · N симв.)."""
    if not chapter_path:
        return ""
    if str(chapter_path).startswith("📄 HTML: "):
        return str(chapter_path)

    cw = _find_chapter_list_widget(parent)
    ep = epub_path or _find_epub_path(parent)
    payload = ("epub", ep, str(chapter_path))
    display_text, _ = get_task_display_texts(payload, chapter_widget=cw)
    return display_text


class ChapterStatusWidget(QFrame):
    """Карточка статуса конкретной главы с отображением как в списке задач."""

    retry_requested = pyqtSignal(str)

    def __init__(
        self,
        chapter_path: str,
        display_name: str,
        status: str = "waiting",
        tooltip_text: str = "",
        parent_widget=None,
        task_payload: tuple = None,
        parent=None,
    ):
        super().__init__(parent)
        self.chapter_path = chapter_path
        self.display_name = display_name
        self.status = status
        self._tooltip_text = tooltip_text or chapter_path
        self._chapter_list_widget = parent_widget
        self._task_payload = task_payload

        self.setObjectName("chapterStatusCard")
        self._setup_ui()
        self.update_status(status, task_payload=task_payload)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.title_label = QLabel(self.display_name)
        self.title_label.setFont(QFont("Segoe UI", 9))
        self.title_label.setToolTip(self._tooltip_text)

        # Сохраняем status_icon для обратной совместимости
        self.status_icon = QLabel()
        self.status_icon.setVisible(False)

        self.status_label = QLabel()
        self.status_label.setFont(QFont("Segoe UI", 9))

        # Кнопка «Повтор» для ошибочных глав
        self.retry_btn = QPushButton()
        retry_icon = _recolor_svg(_ASSETS_DIR / "retry.svg", theme_manager.color("text_secondary"))
        self.retry_btn.setIcon(retry_icon)
        self.retry_btn.setIconSize(QSize(14, 14))
        self.retry_btn.setFixedSize(22, 22)
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setToolTip("Повторить обработку этой главы")
        self.retry_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {theme_manager.color('button_hover')};
            }}
        """)
        self.retry_btn.clicked.connect(lambda *args: self.retry_requested.emit(self.chapter_path))
        self.retry_btn.setVisible(False)

        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.status_icon)
        layout.addWidget(self.status_label)
        layout.addWidget(self.retry_btn)

        self.setStyleSheet(f"""
            QFrame#chapterStatusCard {{
                background-color: {theme_manager.color('panel_alt_bg')};
                border: 1px solid {theme_manager.color('border')};
                border-radius: 6px;
            }}
        """)

    def update_status(self, status: str, details: dict | str = None, task_payload: tuple = None):
        self.status = status
        if task_payload is not None:
            self._task_payload = task_payload
        payload = self._task_payload

        details_dict = details if isinstance(details, dict) else {}
        if isinstance(details, str) and details:
            details_dict = {"errors": {details: 1}}

        cw = self._chapter_list_widget
        palette = cw.palette() if (cw and hasattr(cw, "palette") and not hasattr(cw, "_mock_children")) else self.palette()
        display_text, color_hex = get_task_status_display_info(status, details_dict, payload, palette=palette)
        status_tooltip = get_task_status_tooltip(display_text, status, details_dict)

        self.status_label.setText(display_text)
        self.status_label.setToolTip(status_tooltip)
        self.status_label.setStyleSheet(f"color: {color_hex}; font-weight: bold;")

        # Как в списке задач: если pending/waiting — обычный цвет, иначе цвет статуса
        if status in ("pending", "waiting"):
            self.title_label.setStyleSheet(f"color: {theme_manager.color('text_primary')};")
        else:
            self.title_label.setStyleSheet(f"color: {color_hex};")

        self.retry_btn.setVisible(status.startswith("error"))


def _make_icon_button(icon: QIcon, tooltip: str) -> QPushButton:
    """Создает стандартную кнопку действия с SVG-иконкой."""
    btn = QPushButton()
    btn.setIcon(icon)
    btn.setIconSize(QSize(16, 16))
    btn.setFixedSize(30, 30)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: 6px;
        }}
        QPushButton:hover {{
            background: {theme_manager.color('button_hover')};
        }}
        QPushButton:pressed {{
            background: {theme_manager.color('button_pressed')};
        }}
    """)
    return btn


class StageCardWidget(QFrame):
    """Карточка отдельного этапа конвейера с тумблером и аккордеоном."""

    stage_toggled = pyqtSignal(str, bool)
    edit_requested = pyqtSignal(str)
    restart_requested = pyqtSignal(str)

    def __init__(self, stage_id: str, title: str, parent=None):
        super().__init__(parent)
        self.stage_id = stage_id
        self.title = title
        self.status = "waiting"
        self._is_expanded = False
        self._accordion_height = 0
        self._chapter_widgets = {}  # chapter_path -> ChapterStatusWidget

        self.setObjectName("stageCardWidget")
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        self.header_frame = QFrame()
        self.header_frame.setObjectName("stageCardHeader")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(15, 12, 15, 12)

        # Индикатор статуса
        self.status_indicator = QLabel("○")
        self.status_indicator.setFixedSize(24, 24)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_indicator.setStyleSheet(f"""
            color: {theme_manager.color('text_muted')};
            font-size: 14pt;
            font-weight: bold;
        """)

        # Информация
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.title_label = QLabel(self.title)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        self.title_label.setFont(font)

        self.subtitle_label = QLabel("В ожидании")
        self.subtitle_label.setStyleSheet(f"color: {theme_manager.color('text_muted')}; font-size: 8pt;")

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.subtitle_label)

        # Счётчик глав
        self.chapter_count_label = QLabel("")
        self.chapter_count_label.setStyleSheet(f"color: {theme_manager.color('text_muted')}; font-size: 8pt;")

        # Тумблер
        self.toggle_switch = ToggleSwitchWidget(checked=True)
        self.toggle_switch.toggled.connect(self._on_toggle)

        # --- SVG-кнопки ---
        icon_color = theme_manager.color("text_secondary")

        edit_icon = _recolor_svg(_ASSETS_DIR / "edit.svg", icon_color)
        self.btn_edit = _make_icon_button(edit_icon, "Редактировать параметры этапа")
        self.btn_edit.clicked.connect(self._on_edit_clicked)

        retry_icon = _recolor_svg(_ASSETS_DIR / "retry.svg", icon_color)
        self.btn_restart = _make_icon_button(retry_icon, "Повторить этот шаг")
        self.btn_restart.clicked.connect(lambda: self.restart_requested.emit(self.stage_id))

        expand_icon = _recolor_svg(_ASSETS_DIR / "chevron-down.svg", icon_color)
        self.btn_expand = _make_icon_button(expand_icon, "Показать / скрыть прогресс по главам")
        self.btn_expand.clicked.connect(self.toggle_accordion)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(4)
        actions_layout.addWidget(self.btn_edit)
        actions_layout.addWidget(self.btn_restart)
        actions_layout.addWidget(self.btn_expand)

        # Собираем Header
        header_layout.addWidget(self.status_indicator)
        header_layout.addSpacing(10)
        header_layout.addLayout(info_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.chapter_count_label)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.toggle_switch)
        header_layout.addSpacing(15)
        header_layout.addLayout(actions_layout)

        # Accordion
        self.accordion_container = QFrame()
        self.accordion_container.setObjectName("stageCardAccordion")
        self.accordion_layout = QVBoxLayout(self.accordion_container)
        self.accordion_layout.setContentsMargins(15, 0, 15, 15)
        self.accordion_layout.setSpacing(8)

        accordion_title = QLabel("Прогресс по главам")
        accordion_title.setStyleSheet(f"color: {theme_manager.color('text_secondary')}; font-weight: bold; margin-bottom: 5px;")
        self.accordion_layout.addWidget(accordion_title)

        # Заглушка «Нет глав»
        self.no_chapters_label = QLabel("Главы не выбраны")
        self.no_chapters_label.setStyleSheet(f"color: {theme_manager.color('text_muted')}; font-style: italic;")
        self.accordion_layout.addWidget(self.no_chapters_label)

        self.chapters_container = QVBoxLayout()
        self.chapters_container.setSpacing(5)
        self.accordion_layout.addLayout(self.chapters_container)

        self.accordion_container.setVisible(False)
        self.accordion_container.setMaximumHeight(0)

        main_layout.addWidget(self.header_frame)
        main_layout.addWidget(self.accordion_container)

        self.setStyleSheet(f"""
            QFrame#stageCardWidget {{
                background-color: {theme_manager.color('panel_bg')};
                border: 1px solid {theme_manager.color('border')};
                border-radius: 8px;
            }}
            QFrame#stageCardHeader {{
                background: transparent;
                border: none;
            }}
            QFrame#stageCardAccordion {{
                background: transparent;
                border: none;
                border-top: 1px solid {theme_manager.color('border')};
            }}
        """)

        self.animation = QPropertyAnimation(self.accordion_container, b"maximumHeight")
        self.animation.setDuration(250)

    def _on_toggle(self, is_active: bool):
        self.stage_toggled.emit(self.stage_id, is_active)
        if not is_active:
            self.set_status("disabled", "Отключено")
        else:
            self.set_status("waiting", "В ожидании")

    def _on_edit_clicked(self):
        """Перенаправляет во вкладку настроек этого этапа."""
        self.edit_requested.emit(self.stage_id)

    def set_status(self, status: str, text: str = ""):
        self.status = status
        if status in ("success", "completed"):
            self.status_indicator.setText("✔")
            self.status_indicator.setStyleSheet(f"color: {theme_manager.color('success')}; font-size: 14pt; font-weight: bold;")
        elif status == "error":
            self.status_indicator.setText("✕")
            self.status_indicator.setStyleSheet(f"color: {theme_manager.color('danger')}; font-size: 14pt; font-weight: bold;")
        elif status == "active":
            self.status_indicator.setText("↻")
            self.status_indicator.setStyleSheet(f"color: {theme_manager.color('accent')}; font-size: 14pt; font-weight: bold;")
        elif status == "waiting":
            self.status_indicator.setText("○")
            self.status_indicator.setStyleSheet(f"color: {theme_manager.color('text_muted')}; font-size: 14pt; font-weight: bold;")
        elif status == "disabled":
            self.status_indicator.setText("○")
            self.status_indicator.setStyleSheet(f"color: {theme_manager.color('border_strong')}; font-size: 14pt; font-weight: bold;")

        if text:
            self.subtitle_label.setText(text)

    def set_chapters(self, items: list, parent_dialog=None, chapter_list_widget=None, epub_path=None):
        """Заменяет список глав в аккордеоне реальными данными из проекта.
        Если элемент в items является списком, он отображается как один пакетный виджет."""
        # Удаляем старые
        self._chapter_widgets.clear()
        while self.chapters_container.count():
            item_ly = self.chapters_container.takeAt(0)
            if item_ly.widget():
                item_ly.widget().deleteLater()

        if not items:
            self.no_chapters_label.setVisible(True)
            self.chapter_count_label.setText("")
        else:
            self.no_chapters_label.setVisible(False)
            
            # Подсчитываем реальное количество глав
            total_chapters = 0
            for item in items:
                if isinstance(item, (list, tuple)):
                    total_chapters += len(item)
                else:
                    total_chapters += 1
            self.chapter_count_label.setText(f"({total_chapters} глав)")

            cw = chapter_list_widget or _find_chapter_list_widget(parent_dialog or self)
            ep = epub_path or _find_epub_path(parent_dialog or self)

            for item in items:
                if isinstance(item, (list, tuple)):
                    task_payload = ("epub_batch", ep, list(item))
                    status_payload = ("glossary_batch_task", ep, list(item)) if self.stage_id == "glossary_collection" else task_payload
                    ch_path_key = str(list(item))
                else:
                    ch_path = item
                    task_payload = ("epub", ep, ch_path)
                    status_payload = ("glossary_batch_task", ep, [ch_path]) if self.stage_id == "glossary_collection" else task_payload
                    ch_path_key = str(ch_path)

                display_text, tooltip_text = get_task_display_texts(status_payload, chapter_widget=cw)
                
                widget = ChapterStatusWidget(
                    ch_path_key,
                    display_text,
                    "waiting",
                    tooltip_text=tooltip_text,
                    parent_widget=cw,
                    task_payload=status_payload,
                    parent=self,
                )
                widget.retry_requested.connect(
                    lambda t=ch_path_key: self.restart_requested.emit(f"{self.stage_id}:{t}")
                )
                self.chapters_container.addWidget(widget)
                self._chapter_widgets[ch_path_key] = widget

        self._update_accordion_height()

    def update_chapter_status(self, chapter_path: str, status: str, details: dict | str = None, task_payload: tuple = None):
        """Обновляет статус конкретной главы с использованием методов списка задач."""
        widget = self._chapter_widgets.get(chapter_path)
        if not widget:
            norm = chapter_path.replace("\\", "/")
            for p, w in self._chapter_widgets.items():
                if p.replace("\\", "/") == norm:
                    widget = w
                    break
        if widget:
            widget.update_status(status, details=details, task_payload=task_payload)

    def update_stage_summary(self):
        """Вычисляет сводный статус этапа на основе статусов всех глав."""
        if not self._chapter_widgets:
            return

        statuses = [w.status for w in self._chapter_widgets.values()]
        total = len(statuses)
        success_count = sum(1 for s in statuses if s in ("success", "completed", "glossary_success"))
        error_count = sum(1 for s in statuses if str(s).startswith("error"))
        in_progress_count = sum(1 for s in statuses if s in ("in_progress", "completion"))
        pending_count = sum(1 for s in statuses if s in ("pending", "waiting"))

        if success_count == total and total > 0:
            self.set_status("success", f"Завершено ({total}/{total})")
        elif error_count > 0 and in_progress_count == 0 and pending_count == 0:
            self.set_status("error", f"Ошибки: {error_count}/{total}")
        elif in_progress_count > 0:
            self.set_status("active", f"Обработка... ({success_count}/{total})")
        elif success_count > 0:
            self.set_status("active", f"В процессе ({success_count}/{total})")
        elif pending_count > 0:
            self.set_status("waiting", f"В очереди ({total} глав)")
        else:
            self.set_status("waiting", f"Ожидание ({total} глав)")

    def clear_chapters(self):
        self._chapter_widgets.clear()
        while self.chapters_container.count():
            item = self.chapters_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.no_chapters_label.setVisible(True)
        self.chapter_count_label.setText("")
        self.set_status("waiting", "В ожидании")
        self._update_accordion_height()

    def _update_accordion_height(self):
        self.accordion_container.setMaximumHeight(16777215)
        self._accordion_height = self.accordion_container.sizeHint().height()
        if self._is_expanded:
            self.accordion_container.setMaximumHeight(16777215)
        else:
            self.accordion_container.setMaximumHeight(0)

    def toggle_accordion(self):
        icon_color = theme_manager.color("text_secondary")
        self._update_accordion_height()
        try:
            self.animation.finished.disconnect()
        except TypeError:
            pass

        if self._is_expanded:
            self.animation.setStartValue(self.accordion_container.height())
            self.animation.setEndValue(0)
            expand_icon = _recolor_svg(_ASSETS_DIR / "chevron-down.svg", icon_color)
            self.btn_expand.setIcon(expand_icon)
            self.animation.finished.connect(self._on_collapse_finished)
        else:
            self.accordion_container.setVisible(True)
            self.animation.setStartValue(0)
            self.animation.setEndValue(self._accordion_height)
            expand_icon = _recolor_svg(_ASSETS_DIR / "chevron-up.svg", icon_color)
            self.btn_expand.setIcon(expand_icon)
            self.animation.finished.connect(self._on_expand_finished)

        self._is_expanded = not self._is_expanded
        self.animation.start()

    def _on_collapse_finished(self):
        if not self._is_expanded:
            self.accordion_container.setVisible(False)

    def _on_expand_finished(self):
        if self._is_expanded:
            self.accordion_container.setMaximumHeight(16777215)


class AutoTranslatePipelineWidget(QWidget):
    """Главный виджет вкладки 'Автоперевод'."""

    edit_requested = pyqtSignal(str)
    start_pipeline_requested = pyqtSignal()
    stop_pipeline_requested = pyqtSignal()

    def __init__(self, settings_manager=None, parent=None, event_bus=None, engine=None):
        super().__init__(parent)
        if settings_manager is None:
            try:
                from gemini_translator.api.settings import SettingsManager
                settings_manager = SettingsManager()
            except Exception:
                settings_manager = None
        self.settings = settings_manager
        self.stages = {}
        self._current_chapters = []
        self._event_bus = event_bus
        self._engine = engine
        self._uses_topic_subscription = False
        self._is_session_active = False

        self._setup_ui()
        self._load_settings()
        self._init_event_bus()

    @property
    def event_bus(self):
        if self._event_bus:
            return self._event_bus
        parent = self.parent()
        bus = getattr(parent, "bus", None) or getattr(parent, "event_bus", None)
        if bus:
            return bus
        app = QMessageBox.instance() if hasattr(QMessageBox, "instance") else None
        from PyQt6.QtWidgets import QApplication
        q_app = QApplication.instance()
        return getattr(q_app, "event_bus", None)

    @property
    def engine(self):
        if self._engine:
            return self._engine
        parent = self.parent()
        eng = getattr(parent, "engine", None)
        if eng:
            return eng
        from PyQt6.QtWidgets import QApplication
        q_app = QApplication.instance()
        return getattr(q_app, "engine", None)

    @property
    def task_manager(self):
        parent = self.parent()
        tm = getattr(parent, "task_manager", None)
        if tm:
            return tm
        eng = self.engine
        if eng and hasattr(eng, "task_manager"):
            return eng.task_manager
        from PyQt6.QtWidgets import QApplication
        q_app = QApplication.instance()
        return getattr(q_app, "task_manager", None)

    @property
    def project_manager(self):
        parent = self.parent()
        return getattr(parent, "project_manager", None)

    @property
    def chapter_list_widget(self):
        return _find_chapter_list_widget(self)

    @property
    def epub_path(self) -> str:
        return _find_epub_path(self)

    def _init_event_bus(self):
        bus = self.event_bus
        if not bus:
            return
        if hasattr(bus, "subscribe"):
            bus.subscribe("task_state_changed", self._on_task_state_changed)
            bus.subscribe("session_started", self._on_session_started)
            bus.subscribe("session_finished", self._on_session_finished)
            bus.subscribe("assembly_finished", self._on_assembly_finished)
            self._uses_topic_subscription = True
        elif hasattr(bus, "event_posted"):
            bus.event_posted.connect(self.on_event)

    def on_event(self, event_data: dict):
        """Слушает события шины и реагирует на изменения состояния задач."""
        if not isinstance(event_data, dict):
            return
        event_name = event_data.get("event")
        if event_name == "task_state_changed":
            self._on_task_state_changed(event_data)
        elif event_name == "session_started":
            self._on_session_started(event_data)
        elif event_name == "session_finished":
            self._on_session_finished(event_data)
        elif event_name == "assembly_finished":
            self._on_assembly_finished(event_data)

    def _on_task_state_changed(self, event_data: dict):
        data = event_data.get("data", {}) if isinstance(event_data, dict) else {}
        full_state = data.get("full_state")
        if isinstance(full_state, list):
            self.update_task_states(full_state)
        else:
            tm = self.task_manager
            if tm and hasattr(tm, "get_ui_state_list"):
                self.update_task_states(tm.get_ui_state_list())

    def _on_session_started(self, _event_data: dict = None):
        self.refresh_chapter_statuses()

    def _on_session_finished(self, _event_data: dict = None):
        self.refresh_chapter_statuses()

    def _on_assembly_finished(self, _event_data: dict = None):
        self.refresh_chapter_statuses()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_chapter_statuses()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Верхняя панель управления
        top_bar_layout = QHBoxLayout()
        header_label = QLabel("Раздел: Автоперевод")
        font = QFont("Segoe UI", 16)
        font.setBold(True)
        header_label.setFont(font)
        header_label.setStyleSheet(f"color: {theme_manager.color('text_primary')};")

        self.btn_start_pipeline = QPushButton("▶ Запустить автоперевод")
        self.btn_start_pipeline.setMinimumHeight(34)
        self.btn_start_pipeline.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_pipeline.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_manager.color('accent')};
                color: #ffffff;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 6px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {theme_manager.color('accent_hover')};
            }}
        """)
        self.btn_start_pipeline.clicked.connect(self.start_pipeline_requested.emit)

        self.btn_stop_pipeline = QPushButton("⏹ Остановить автоперевод")
        self.btn_stop_pipeline.setMinimumHeight(34)
        self.btn_stop_pipeline.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop_pipeline.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_manager.color('danger')};
                color: #ffffff;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 6px;
                border: none;
            }}
        """)
        self.btn_stop_pipeline.setVisible(False)
        self.btn_stop_pipeline.clicked.connect(self.stop_pipeline_requested.emit)

        top_bar_layout.addWidget(header_label)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.btn_start_pipeline)
        top_bar_layout.addWidget(self.btn_stop_pipeline)
        main_layout.addLayout(top_bar_layout)

        # Скролл зона
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("background: transparent;")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self.pipeline_layout = QVBoxLayout(scroll_content)
        self.pipeline_layout.setContentsMargins(0, 0, 0, 0)
        self.pipeline_layout.setSpacing(12)

        stage_definitions = [
            ("glossary_collection", "Сбор глоссария"),
            ("glossary_validation", "Валидация глоссария"),
            ("machine_translation", "Машинный перевод (AI)"),
            ("untranslated_fixing", "Доперевод недоперевода (AI)"),
            ("ai_editing", "ИИ-редактирование для улучшения читаемости"),
        ]

        for stage_id, title in stage_definitions:
            card = StageCardWidget(stage_id, title)
            card.stage_toggled.connect(self._save_settings)
            card.restart_requested.connect(self._on_restart_requested)
            card.edit_requested.connect(self.edit_requested.emit)
            
            if stage_id == "untranslated_fixing":
                card.btn_edit.setVisible(False)

            self.stages[stage_id] = card
            self.pipeline_layout.addWidget(card)

        self.pipeline_layout.addStretch()
        scroll_area.setWidget(scroll_content)

        main_layout.addWidget(scroll_area)

    def update_chapters(self, chapter_paths: list[str]):
        """Обновляет список глав во ВСЕХ карточках этапов.
        Вызывается из InitialSetupPage при изменении html_files."""
        self._current_chapters = list(chapter_paths or [])
        cw = self.chapter_list_widget
        ep = self.epub_path
        
        # Получаем настройки пакетирования из родительского окна (InitialSetupPage)
        parent = self.parent()
        use_batching = False
        batch_size = 50
        if parent and hasattr(parent, "translation_options_widget"):
            use_batching = parent.translation_options_widget.batch_checkbox.isChecked()
            batch_size = parent.translation_options_widget.task_size_spin.value()
            
        items = []
        if use_batching and batch_size > 0:
            for i in range(0, len(self._current_chapters), batch_size):
                items.append(self._current_chapters[i:i + batch_size])
        else:
            items = self._current_chapters

        if not items:
            for card in self.stages.values():
                card.clear_chapters()
        else:
            for card in self.stages.values():
                card.set_chapters(
                    items,
                    chapter_list_widget=cw,
                    epub_path=ep,
                )
            self.refresh_chapter_statuses()

    def update_task_states(self, ui_state_list: list):
        """Обновляет статусы глав на основе данных из task_manager.get_ui_state_list()."""
        if not ui_state_list and not self._current_chapters:
            return

        translation_status_map = {}
        glossary_status_map = {}

        for entry in (ui_state_list or []):
            try:
                task_tuple, ui_status, details = entry
                _task_id, payload = task_tuple

                if isinstance(payload, (list, tuple)) and len(payload) >= 3:
                    task_type = payload[0]
                    chapter_ref = payload[2]
                    if isinstance(chapter_ref, str):
                        chapters = [chapter_ref]
                    elif isinstance(chapter_ref, (list, tuple)):
                        chapters = [str(list(chapter_ref))]
                        chapters.extend(list(chapter_ref))
                    else:
                        continue

                    details_dict = details if isinstance(details, dict) else {}
                    target_map = glossary_status_map if task_type == "glossary_batch_task" else translation_status_map

                    for ch in chapters:
                        existing = target_map.get(ch)
                        if existing is None or _status_priority(ui_status) > _status_priority(existing[0]):
                            target_map[ch] = (ui_status, details_dict, payload)
            except (ValueError, TypeError, IndexError):
                continue

        # Применяем к machine_translation
        stage_trans = self.stages.get("machine_translation")
        if stage_trans:
            for ch_path, (status, details, payload) in translation_status_map.items():
                stage_trans.update_chapter_status(ch_path, status, details=details, task_payload=payload)
            stage_trans.update_stage_summary()

        # Применяем к glossary_collection
        stage_gloss = self.stages.get("glossary_collection")
        if stage_gloss and glossary_status_map:
            for ch_path, (status, details, payload) in glossary_status_map.items():
                stage_gloss.update_chapter_status(ch_path, status, details=details, task_payload=payload)
            stage_gloss.update_stage_summary()

    def refresh_chapter_statuses(self):
        """Обновляет статусы всех выбранных глав по всем этапам, используя сущ. методы."""
        if not self._current_chapters:
            return

        pm = self.project_manager
        tm = self.task_manager
        ep = self.epub_path

        glossary_done_set = set()
        if pm and hasattr(pm, "load_glossary_generation_map"):
            try:
                glossary_done_set = {p.replace("\\", "/") for p in pm.load_glossary_generation_map()}
            except Exception:
                pass

        val_cache_entries = {}
        if pm and hasattr(pm, "load_validation_cache"):
            try:
                vc_data = pm.load_validation_cache()
                if isinstance(vc_data, dict):
                    val_cache_entries = vc_data.get("chapters", {}) or {}
            except Exception:
                pass

        # 1. Проверяем постоянные результаты на диске через project_manager
        card_gloss = self.stages.get("glossary_collection")
        card_trans = self.stages.get("machine_translation")
        card_untrans = self.stages.get("untranslated_fixing")
        card_edit = self.stages.get("ai_editing")

        for ch in self._current_chapters:
            norm_ch = ch.replace("\\", "/")

            if card_gloss:
                gloss_payload = ("glossary_batch_task", ep, [ch])
                if norm_ch in glossary_done_set:
                    card_gloss.update_chapter_status(ch, "success", details={}, task_payload=gloss_payload)
                else:
                    card_gloss.update_chapter_status(ch, "waiting", details={}, task_payload=gloss_payload)

            if pm and hasattr(pm, "get_versions_for_original"):
                try:
                    epub_payload = ("epub", ep, ch)
                    versions = pm.get_versions_for_original(ch) or {}
                    has_trans = any(k != "filtered" for k in versions.keys())
                    if card_trans:
                        if has_trans:
                            card_trans.update_chapter_status(ch, "success", details={}, task_payload=epub_payload)
                        else:
                            card_trans.update_chapter_status(ch, "waiting", details={}, task_payload=epub_payload)

                    if card_untrans:
                        if not has_trans:
                            card_untrans.update_chapter_status(ch, "waiting", details={}, task_payload=epub_payload)
                        elif "_validated.html" in versions:
                            card_untrans.update_chapter_status(ch, "success", details={}, task_payload=epub_payload)
                        else:
                            ch_entry = val_cache_entries.get(norm_ch) or val_cache_entries.get(ch)
                            if isinstance(ch_entry, dict) and ch_entry.get("untranslated_words"):
                                card_untrans.update_chapter_status(ch, "waiting", details={}, task_payload=epub_payload)
                            else:
                                card_untrans.update_chapter_status(ch, "success", details={}, task_payload=epub_payload)

                    if card_edit:
                        if "_validated.html" in versions:
                            card_edit.update_chapter_status(ch, "success", details={}, task_payload=epub_payload)
                        else:
                            card_edit.update_chapter_status(ch, "waiting", details={}, task_payload=epub_payload)
                except Exception:
                    pass

        # 2. Накладываем актуальные задачи из task_manager (они имеют приоритет: in_progress, error, pending и т.д.)
        if tm and hasattr(tm, "get_ui_state_list"):
            try:
                ui_state_list = tm.get_ui_state_list()
                if ui_state_list:
                    self.update_task_states(ui_state_list)
            except Exception:
                pass

        # 3. Обновляем сводки по всем этапам
        for card in self.stages.values():
            card.update_stage_summary()

    def _on_restart_requested(self, target: str):
        """Обработчик запроса на повтор этапа или конкретной главы."""
        if ":" in target:
            stage_id, chapter = target.split(":", 1)
            # Пытаемся найти и перезапустить задачу через task_manager
            tm = self.task_manager
            if tm and hasattr(tm, "reanimate_tasks") and hasattr(tm, "get_ui_state_list"):
                try:
                    failed_ids = []
                    for entry in tm.get_ui_state_list():
                        task_tuple, ui_status, _ = entry
                        task_id, payload = task_tuple
                        if ui_status == "error" and isinstance(payload, (list, tuple)) and len(payload) >= 3:
                            ch_ref = payload[2]
                            norm_ch = chapter.replace("\\", "/")
                            matches = False
                            if isinstance(ch_ref, str) and ch_ref.replace("\\", "/") == norm_ch:
                                matches = True
                            elif isinstance(ch_ref, (list, tuple)):
                                if any(isinstance(c, str) and c.replace("\\", "/") == norm_ch for c in ch_ref):
                                    matches = True
                            if matches:
                                failed_ids.append(task_id)
                    if failed_ids:
                        parent = self.parent()
                        if hasattr(parent, "_handle_task_reanimation"):
                            parent._handle_task_reanimation(failed_ids)
                        else:
                            tm.reanimate_tasks(failed_ids)
                        self.refresh_chapter_statuses()
                        return
                except Exception:
                    pass

            QMessageBox.information(
                self,
                "Повтор главы",
                f"Запрошен повтор главы «{_chapter_display_name(chapter)}»\n"
                f"на этапе «{stage_id}»."
            )
        else:
            QMessageBox.information(
                self,
                "Повтор этапа",
                f"Запрошен перезапуск этапа «{target}»."
            )

    def _load_settings(self):
        if not self.settings or not hasattr(self.settings, "_generic_loader"):
            return
        pipeline_config = self.settings._generic_loader("auto_translate_pipeline", {})
        for stage_id, card in self.stages.items():
            is_active = pipeline_config.get(stage_id, True)
            card.toggle_switch.setChecked(is_active)
            if not is_active:
                card.set_status("disabled", "Отключено")

    def _save_settings(self, *_args):
        if not self.settings or not hasattr(self.settings, "_generic_saver"):
            return
        pipeline_config = {}
        for stage_id, card in self.stages.items():
            pipeline_config[stage_id] = card.toggle_switch.isChecked()
        self.settings._generic_saver("auto_translate_pipeline", pipeline_config)

    def get_enabled_stages(self) -> list[str]:
        """Возвращает список ID активных этапов в порядке их выполнения."""
        ordered_ids = [
            "glossary_collection",
            "glossary_validation",
            "machine_translation",
            "untranslated_fixing",
            "ai_editing",
        ]
        return [
            sid for sid in ordered_ids
            if sid in self.stages and self.stages[sid].toggle_switch.isChecked()
        ]

    def set_stage_status(self, stage_id: str, status: str, text: str = ""):
        card = self.stages.get(stage_id)
        if card:
            card.set_status(status, text)

    def set_session_mode(self, is_session_active: bool):
        self._is_session_active = is_session_active
        if hasattr(self, "btn_start_pipeline"):
            self.btn_start_pipeline.setVisible(not is_session_active)
        if hasattr(self, "btn_stop_pipeline"):
            self.btn_stop_pipeline.setVisible(is_session_active)
        for card in self.stages.values():
            if hasattr(card, "toggle_switch"):
                card.toggle_switch.setEnabled(not is_session_active)
            if hasattr(card, "btn_edit"):
                card.btn_edit.setEnabled(not is_session_active)
            if hasattr(card, "btn_restart"):
                card.btn_restart.setEnabled(not is_session_active)



def _status_priority(status: str) -> int:
    """Возвращает приоритет статуса для выбора наиболее актуального."""
    if not status:
        return 0
    if status in ("in_progress", "completion"):
        return 5
    if str(status).startswith("error"):
        return 4
    if status in ("pending", "waiting"):
        return 3
    if status == "held":
        return 2
    if status in ("success", "completed", "glossary_success"):
        return 1
    return 0

