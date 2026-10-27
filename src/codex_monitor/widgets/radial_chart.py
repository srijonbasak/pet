from PyQt6.QtWidgets import QWidget
import math

from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QConicalGradient, QBrush
from PyQt6.QtCore import Qt, QRectF, QLineF, QPropertyAnimation, pyqtProperty

class AnimatedRadialChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._target_value = 0.0
        
        self.label = "Context"
        self.subtitle = ""
        
        self.animation = QPropertyAnimation(self, b"animated_value")
        self.animation.setDuration(1200) # 1.2 second animation
        
        self.setMinimumSize(180, 180)

    @pyqtProperty(float)
    def animated_value(self):
        return self._value

    @animated_value.setter
    def animated_value(self, val):
        self._value = val
        self.update() # trigger paintEvent

    def set_value(self, new_val, label=None, subtitle=None):
        if label is not None:
            self.label = label
        if subtitle is not None:
            self.subtitle = subtitle
            
        # Ensure new_val is a float
        new_val = float(new_val) if new_val is not None else 0.0
        
        if self._target_value != new_val:
            self.animation.stop()
            self.animation.setStartValue(self._value)
            self.animation.setEndValue(new_val)
            self.animation.start()
            self._target_value = new_val
        else:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Determine square bounding box
        size = min(width, height) - 24
        rect = QRectF((width - size) / 2, (height - size) / 2, size, size)
        
        stroke_width = max(8, int(size * 0.06))
        
        # Fine inner ring and futuristic tick marks.
        pen_inner = QPen(QColor(255, 255, 255, 38))
        pen_inner.setWidth(1)
        painter.setPen(pen_inner)
        inner_rect = rect.adjusted(stroke_width, stroke_width, -stroke_width, -stroke_width)
        painter.drawArc(inner_rect, 0, 360 * 16)

        center = rect.center()
        outer_radius = size / 2 + 7
        inner_radius = outer_radius - 4
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        for angle in range(0, 360, 30):
            radians = math.radians(angle)
            painter.drawLine(QLineF(
                center.x() + math.cos(radians) * inner_radius,
                center.y() + math.sin(radians) * inner_radius,
                center.x() + math.cos(radians) * outer_radius,
                center.y() + math.sin(radians) * outer_radius,
            ))
        
        # Draw background track (white to gray gradient style)
        pen_bg = QPen(QColor(255, 255, 255, 28))
        pen_bg.setWidth(stroke_width)
        pen_bg.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 0, 360 * 16)
        
        # Draw progress track
        # Start angle is at 90 degrees (12 o'clock). Qt uses 1/16th of a degree.
        # Positive values are counter-clockwise, so we use negative for clockwise.
        start_angle = 90 * 16
        span_angle = -int((self._value / 100.0) * 360 * 16)
        
        # Gradient
        gradient = QConicalGradient(rect.center(), 90)
        gradient.setColorAt(0.0, QColor("#d5e5fb"))
        gradient.setColorAt(0.45, QColor("#8eb6ef"))
        gradient.setColorAt(1.0, QColor("#6489bd"))

        glow_pen = QPen(QBrush(gradient), float(stroke_width + 7))
        glow_color = QColor(110, 160, 255, 32)
        glow_pen.setColor(glow_color)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawArc(rect, start_angle, span_angle)
        
        pen_progress = QPen(QBrush(gradient), float(stroke_width))
        pen_progress.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_progress)
        painter.drawArc(rect, start_angle, span_angle)
        
        # Draw Text
        painter.setPen(QColor("#FFFFFF"))
        
        # Value %
        font_value = QFont("Segoe UI", int(size * 0.16), QFont.Weight.Bold)
        painter.setFont(font_value)
        val_text = f"{int(self._value)}%"
        val_rect = QRectF(rect.left(), center.y() - 48, rect.width(), 48)
        painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, val_text)
        
        # Label (e.g. CONTEXT)
        painter.setPen(QColor("#c4cedb"))
        font_label = QFont("Segoe UI", int(size * 0.065), QFont.Weight.DemiBold)
        font_label.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        painter.setFont(font_label)
        label_rect = QRectF(rect.left(), center.y() + 12, rect.width(), 28)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.label.upper())
