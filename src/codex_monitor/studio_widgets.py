"""Small painted controls for the native studio; no animation or web runtime."""

from PyQt6.QtCore import Qt, QRectF, QSize, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QLinearGradient, QPainterPath
from PyQt6.QtWidgets import QFrame, QWidget, QCheckBox


def line_icon(kind):
    icon = QIcon()
    for state, color in ((QIcon.State.Off, '#788393'), (QIcon.State.On, '#3569e8')):
        pixmap = QPixmap(40, 40)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if kind == 'overview':
            p.drawEllipse(QRectF(3, 3, 14, 14))
            p.drawArc(QRectF(6, 6, 8, 8), 25 * 16, 260 * 16)
            p.drawLine(QPointF(10, 10), QPointF(13, 7))
        elif kind == 'design':
            for x, y in ((3, 3), (11, 3), (3, 11), (11, 11)):
                p.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
        elif kind == 'animation':
            path = QPainterPath(); path.moveTo(7, 5); path.lineTo(15, 10); path.lineTo(7, 15); path.closeSubpath()
            p.drawPath(path); p.drawLine(3, 5, 3, 15)
        else:
            p.drawRoundedRect(QRectF(3, 2, 14, 13), 3, 3)
            p.drawLine(7, 18, 13, 18); p.drawLine(10, 15, 10, 18)
        p.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class StudioMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(30, 30)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#3569e8'), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x, y, dx, dy in ((5, 5, 1, 1), (25, 5, -1, 1), (5, 25, 1, -1), (25, 25, -1, -1)):
            p.drawLine(x, y, x + dx * 7, y); p.drawLine(x, y, x, y + dy * 7)
        p.setPen(QPen(QColor('#303c50'), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(12, 12, 15, 15); p.drawLine(15, 15, 12, 18); p.drawLine(18, 18, 21, 18)


class CanvasStage(QFrame):
    def __init__(self):
        super().__init__()
        self._background = None
        self._background_key = None

    def paintEvent(self, event):
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if key != self._background_key:
            ratio = self.devicePixelRatioF()
            self._background = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
            self._background.setDevicePixelRatio(ratio)
            self._background.fill(Qt.GlobalColor.transparent)
            self._paint_background(self._background)
            self._background_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._background)

    def _paint_background(self, target):
        p = QPainter(target); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        path = QPainterPath(); path.addRoundedRect(rect, 18, 18)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor('#f0f2f5'))
        p.setPen(QPen(QColor(105, 121, 145, 26), 1))
        for x in range(18, self.width(), 26):
            for y in range(72, max(73, self.height() - 155), 26):
                p.drawPoint(x, y)
        p.setPen(QPen(QColor('#edf0f4'), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 18, 18)


class DeviceBezel(QFrame):
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor('#515864')); gradient.setColorAt(.35, QColor('#252a32'))
        gradient.setColorAt(1, QColor('#14171c'))
        p.setBrush(gradient); p.setPen(QPen(QColor('#7b838f'), 1))
        p.drawRoundedRect(rect, 27, 27)
        p.setBrush(QColor('#090b0e')); p.setPen(QPen(QColor('#2e333d'), 1))
        p.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 23, 23)
        p.setPen(QPen(QColor('#a9b0bb'), 1))
        p.drawLine(QPointF(28, 3), QPointF(self.width() - 28, 3))
        p.setBrush(QColor('#79a5eb')); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(self.width() / 2 - 1.5, self.height() - 11, 3, 3))


class Toggle(QCheckBox):
    def __init__(self, text):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 43, 31)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - 17) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#3569e8') if self.isChecked() else QColor('#d2d7dd'))
        p.drawRoundedRect(QRectF(0, y, 29, 17), 8.5, 8.5)
        p.setBrush(QColor('#ffffff'))
        p.drawEllipse(QRectF(14 if self.isChecked() else 3, y + 3, 11, 11))
        p.setPen(QColor('#384453') if self.isEnabled() else QColor('#9aa4b2'))
        p.drawText(self.rect().adjusted(40, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor('#80adff'), 1, Qt.PenStyle.DotLine)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, -1, -1), 4, 4)
