from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen

from gemini_translator.ui import theme_manager

class ToggleSwitchWidget(QWidget):
    """iOS/macOS-style toggle switch с плавной анимацией."""
    
    toggled = pyqtSignal(bool)
    
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self._checked = checked
        self._position = 1.0 if checked else 0.0
        
        self.animation = QPropertyAnimation(self, b"position", self)
        self.animation.setDuration(200)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @pyqtProperty(float)
    def position(self):
        return self._position

    @position.setter
    def position(self, pos):
        self._position = pos
        self.update()

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked != checked:
            self._checked = checked
            self.animation.setStartValue(self._position)
            self.animation.setEndValue(1.0 if checked else 0.0)
            self.animation.start()
            self.toggled.emit(self._checked)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Вычисление цветов в зависимости от позиции анимации (0.0 -> 1.0)
        bg_color_off = QColor(theme_manager.color("input_bg"))
        bg_color_on = QColor(theme_manager.color("accent"))
        
        # Линейная интерполяция
        r = bg_color_off.red() + (bg_color_on.red() - bg_color_off.red()) * self._position
        g = bg_color_off.green() + (bg_color_on.green() - bg_color_off.green()) * self._position
        b = bg_color_off.blue() + (bg_color_on.blue() - bg_color_off.blue()) * self._position
        
        track_color = QColor(int(r), int(g), int(b))
        
        # Отрисовка фона (track)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, self.height() / 2, self.height() / 2)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawPath(path)
        
        # Отрисовка бордера, если выключено (для контраста)
        if self._position < 1.0:
            border_color = QColor(theme_manager.color("border_strong"))
            border_pen = QPen(border_color, 1)
            painter.setPen(border_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        # Отрисовка ручки (handle)
        handle_radius = self.height() / 2 - 2
        
        # X-координата центра ручки интерполируется
        start_x = self.height() / 2
        end_x = self.width() - self.height() / 2
        handle_x = start_x + (end_x - start_x) * self._position
        handle_y = self.height() / 2
        
        handle_color = QColor(theme_manager.color("text_primary")) if self._position > 0.5 else QColor(theme_manager.color("text_secondary"))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(handle_color)
        painter.drawEllipse(QRectF(handle_x - handle_radius, handle_y - handle_radius, handle_radius * 2, handle_radius * 2))
