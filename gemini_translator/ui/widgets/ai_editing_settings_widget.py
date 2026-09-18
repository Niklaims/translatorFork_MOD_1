# -*- coding: utf-8 -*-
"""Виджет настроек и промпта для этапа 'ИИ-редактирование для улучшения читаемости'."""

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QCheckBox, QPushButton
)

from ...api import config as api_config
from ...utils.settings import SettingsManager
from .. import theme_manager
from .common_widgets import NoScrollComboBox, NoScrollDoubleSpinBox, NoScrollSpinBox
from .preset_widget import PresetWidget


class AIEditingSettingsWidget(QWidget):
    """Вкладка управления параметрами и промптом ИИ-редактирования и вычитки."""

    settings_changed = pyqtSignal()
    open_checker_requested = pyqtSignal()

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        super().__init__(parent)
        app = QtWidgets.QApplication.instance()
        self.settings_manager = settings_manager or (app.get_settings_manager() if hasattr(app, "get_settings_manager") else SettingsManager())

        self._init_ui()
        self._load_saved_settings()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # 1. Заголовок
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title_label = QLabel("🪄 ИИ-редактирование для улучшения читаемости")
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {theme_manager.color('text_primary')};")

        subtitle_label = QLabel(
            "Настройка параметров стилистической правки, вычитки рассогласований рода, "
            "нормализации терминологии и повышения качества литературного русского текста."
        )
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet(f"color: {theme_manager.color('text_secondary')}; font-size: 9pt;")
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        main_layout.addLayout(header_layout)

        # 2. Параметры
        params_group = QGroupBox("Параметры редактирования")
        params_layout = QVBoxLayout(params_group)
        params_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Модель для редактуры:"))
        self.model_combo = NoScrollComboBox()
        self.model_combo.addItem("Наследовать из основных настроек", "inherit")
        try:
            for m_name, m_info in sorted(api_config.all_models().items()):
                self.model_combo.addItem(f"{m_name}", m_info.get("id", m_name))
        except Exception:
            pass
        self.model_combo.currentIndexChanged.connect(self._on_setting_changed)
        row1.addWidget(self.model_combo, 1)

        row1.addSpacing(15)
        row1.addWidget(QLabel("Режим:"))
        self.mode_combo = NoScrollComboBox()
        self.mode_combo.addItem("Стандартная редактура (полная)", "standard")
        self.mode_combo.addItem("Быстрая вычитка (опечатки, род)", "fast")
        self.mode_combo.currentIndexChanged.connect(self._on_setting_changed)
        row1.addWidget(self.mode_combo)

        params_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Температура:"))
        self.temp_spin = NoScrollDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.3)
        self.temp_spin.valueChanged.connect(self._on_setting_changed)
        row2.addWidget(self.temp_spin)

        row2.addSpacing(15)
        row2.addWidget(QLabel("Чанк глав за раз:"))
        self.chunk_size_spin = NoScrollSpinBox()
        self.chunk_size_spin.setRange(1, 10)
        self.chunk_size_spin.setValue(3)
        self.chunk_size_spin.setToolTip("Количество последовательных глав для совместного анализа согласованности.")
        self.chunk_size_spin.valueChanged.connect(self._on_setting_changed)
        row2.addWidget(self.chunk_size_spin)

        row2.addSpacing(15)
        self.auto_apply_chk = QCheckBox("Автоматически сохранять одобренные правки в книгу")
        self.auto_apply_chk.setChecked(True)
        self.auto_apply_chk.toggled.connect(self._on_setting_changed)
        row2.addWidget(self.auto_apply_chk)

        row2.addStretch()
        params_layout.addLayout(row2)

        main_layout.addWidget(params_group)

        # 3. Редактор промпта редактирования
        prompt_group = QGroupBox("Промпт редактирования")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.setContentsMargins(5, 5, 5, 5)

        self.preset_widget = PresetWidget(
            parent=self,
            preset_name="Промпт редактирования",
            default_prompt_func=api_config.default_correction_prompt,
            load_presets_func=self.settings_manager.load_correction_prompts,
            save_presets_func=self.settings_manager.save_correction_prompts,
            get_last_text_func=self.settings_manager.get_last_correction_prompt_text,
            get_last_preset_func=self.settings_manager.get_last_correction_prompt_preset_name,
            save_last_preset_func=self.settings_manager.save_last_correction_prompt_preset_name,
            show_default_button=True,
        )
        self.preset_widget.load_last_session_state()
        self.preset_widget.text_changed.connect(self._on_setting_changed)
        prompt_layout.addWidget(self.preset_widget)

        main_layout.addWidget(prompt_group, 1)

        # 4. Кнопка ручного открытия проверки консистентности
        bottom_layout = QHBoxLayout()
        self.btn_open_checker = QPushButton("🪄 Открыть инструмент проверки консистентности…")
        self.btn_open_checker.setToolTip("Запустить интерактивную страницу анализа связности персонажей, имен и сюжета")
        self.btn_open_checker.clicked.connect(self.open_checker_requested.emit)
        bottom_layout.addWidget(self.btn_open_checker)
        bottom_layout.addStretch()

        main_layout.addLayout(bottom_layout)

    def _on_setting_changed(self, *_args):
        self._save_settings()
        self.settings_changed.emit()

    def get_settings(self) -> dict:
        return {
            "model": self.model_combo.currentData(),
            "mode": self.mode_combo.currentData(),
            "temperature": self.temp_spin.value(),
            "chunk_size": self.chunk_size_spin.value(),
            "auto_apply": self.auto_apply_chk.isChecked(),
            "prompt": self.preset_widget.get_prompt() or api_config.default_correction_prompt(),
            "prompt_preset": self.preset_widget.get_current_preset_name(),
        }

    def set_settings(self, data: dict):
        if not isinstance(data, dict):
            return
        if "model" in data:
            idx = self.model_combo.findData(data["model"])
            if idx != -1:
                self.model_combo.setCurrentIndex(idx)
        if "mode" in data:
            idx = self.mode_combo.findData(data["mode"])
            if idx != -1:
                self.mode_combo.setCurrentIndex(idx)
        if "temperature" in data:
            self.temp_spin.setValue(float(data["temperature"]))
        if "chunk_size" in data:
            self.chunk_size_spin.setValue(int(data["chunk_size"]))
        if "auto_apply" in data:
            self.auto_apply_chk.setChecked(bool(data["auto_apply"]))
        if "prompt" in data:
            self.preset_widget.set_prompt(str(data["prompt"]))
        if "prompt_preset" in data and data["prompt_preset"]:
            self.preset_widget.set_preset_by_name(str(data["prompt_preset"]))

    def _load_saved_settings(self):
        saved = self.settings_manager._generic_loader("ai_editing_settings", {})
        if saved:
            self.set_settings(saved)

    def _save_settings(self):
        self.settings_manager._generic_saver("ai_editing_settings", self.get_settings())
        if hasattr(self.preset_widget, "save_last_session_state"):
            self.preset_widget.save_last_session_state()

    def set_session_mode(self, is_session_active: bool):
        for widget in [self.model_combo, self.mode_combo, self.temp_spin,
                       self.chunk_size_spin, self.auto_apply_chk]:
            widget.setEnabled(not is_session_active)
        if hasattr(self.preset_widget, "set_session_mode"):
            self.preset_widget.set_session_mode(is_session_active)
