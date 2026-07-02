from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QSpacerItem, QSizePolicy, QFrame
from PyQt6.QtCore import pyqtSignal, QPropertyAnimation

from gemini_translator.ui import theme_manager

class SidebarWidget(QFrame):
    """Вертикальная панель навигации в стиле OpenCode."""
    
    # Сигнал с индексом выбранного раздела
    section_changed = pyqtSignal(int)
    
    def __init__(self, sections: list[tuple[str, str]], version: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarWidget")
        self.sections = sections
        self.buttons = []
        self._current_index = 0
        
        self.setFixedWidth(150)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 8, 2, 5)
        layout.setSpacing(2)
        
        # Заголовок
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(5, 0, 0, 10)
        title_label = QLabel("Gemini EPUB")
        title_label.setObjectName("heroTitle")
        subtitle_label = QLabel("Translator")
        subtitle_label.setObjectName("heroSubtitle")
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        layout.addLayout(header_layout)
        
        # Кнопки секций
        self.button_group = QtWidgets.QButtonGroup(self)
        self.button_group.setExclusive(True)
        
        for i, (icon, text) in enumerate(self.sections):
            btn = QPushButton(f"{icon}  {text}")
            btn.setObjectName("sidebarNavButton")
            btn.setCheckable(True)
            btn.setProperty("active", "false")
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            
            self.button_group.addButton(btn, i)
            self.buttons.append(btn)
            layout.addWidget(btn)
            
        self.button_group.idClicked.connect(self._on_button_clicked)
        
        if self.buttons:
            self._set_button_active(0)
            
        # Spacer для смещения нижних элементов
        layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        
        # Разделитель
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        separator.setStyleSheet(f"background-color: {theme_manager.color('border')}; border: none; height: 1px;")
        layout.addWidget(separator)
        
        # Настройки приложения
        self.app_settings_btn = QPushButton("⚙️ Приложение")
        self.app_settings_btn.setObjectName("sidebarNavButton")
        self.app_settings_btn.setCheckable(True)
        self.app_settings_btn.setProperty("active", "false")
        self.app_settings_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.button_group.addButton(self.app_settings_btn, len(self.sections))
        self.buttons.append(self.app_settings_btn)
        layout.addWidget(self.app_settings_btn)
        
        # Версия
        version_label = QLabel(version)
        version_label.setObjectName("sidebarVersionLabel")
        version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        
    def _on_button_clicked(self, index: int):
        if self._current_index == index:
            return
        self._current_index = index
        self._set_button_active(index)
        self.section_changed.emit(index)
        
    def _set_button_active(self, active_index: int):
        for i, btn in enumerate(self.buttons):
            is_active = (i == active_index)
            btn.setChecked(is_active)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            
    def set_current_index(self, index: int):
        if 0 <= index < len(self.buttons):
            self.buttons[index].click()
