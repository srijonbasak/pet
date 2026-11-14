"""Live device canvas shared by the integrated studio."""

from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .device_usb import DisplaySettings
from .scene import SceneDesign


class DisplayPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = DisplaySettings()
        self.design = SceneDesign()
        self.images = []
        self.frame = 0
        self.state = None
        self.metric = "five"
        self.battery_value = None
        self.playback_enabled = True
        self.window_active = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.setFixedSize(240, 240)

    def advance(self):
        if len(self.images) > 1 and self.settings.mode != 2 and self.playback_enabled and self.window_active:
            self.frame = (self.frame + 1) % len(self.images)
            self.update()
        else:
            self.timer.stop()

    def sync_playback(self):
        interval = self.design.frame_ms
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        play = (self.isVisible() and self.window_active and self.playback_enabled
                and self.settings.mode != 2 and len(self.images) > 1)
        if play and not self.timer.isActive():
            self.timer.start()
        elif not play and self.timer.isActive():
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_playback()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def draw_battery(self, painter):
        painter.save()
        bg = QColor("#" + self.settings.background) if self.settings.mode != 2 else QColor("white")
        color = QColor("white") if bg.lightness() < 128 else QColor("#34445a")
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(182, 10, 22, 11)
        painter.fillRect(204, 13, 2, 5, color)
        painter.setPen(color)
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        painter.drawText(210, 19, f"{self.battery_value}%" if self.battery_value is not None else "--")
        painter.restore()

    def paintEvent(self, event):
        s = self.settings
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 240, self.height() / 240)
        # Draw in the same logical coordinate space as the physical display.
        value_map = {"five": ("5-HOUR LIMIT", getattr(self.state, "limit_5h_left", None)),
                     "week": ("WEEKLY LIMIT", getattr(self.state, "limit_7d_left", None)),
                     "context": ("CONTEXT", getattr(self.state, "context_left", None))}
        selected_label, selected_value = value_map.get(self.metric, value_map["five"])
        accent = QColor("#" + s.accent)
        if s.mode == 2:
            p.fillRect(QRectF(0, 0, 240, 240), QColor("#ffffff"))
            d = self.design
            if d.usage_style == "bars":
                y = 60
                for bit, key in ((2, "five"), (4, "week"), (1, "context")):
                    if not s.widgets & bit:
                        continue
                    label, value = value_map[key]
                    p.setPen(QColor("#64748a")); p.drawText(30, y + 9, label)
                    p.setPen(QColor("#222d3e")); p.drawText(30, y + 27, f"{value}% LEFT" if value is not None else "--")
                    p.fillRect(30, y + 35, 180, 6, QColor("#e0e6ed"))
                    p.fillRect(30, y + 35, int(180 * max(0, min(100, value or 0)) / 100), 6, accent)
                    y += 55
                if d.title:
                    p.setPen(QColor("#34445a")); p.drawText(d.title_x, d.title_y + 8, d.title)
                self.draw_battery(p)
                p.end()
                return
            radius = d.gauge_radius - 7
            ring = QRectF(d.gauge_x - radius, d.gauge_y - radius, radius * 2, radius * 2)
            p.setPen(QPen(QColor("#c2cddb"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 225 * 16, -270 * 16)
            p.setPen(QPen(accent, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 225 * 16, -int(270 * 16 * max(0, min(100, selected_value or 0)) / 100))
            label = selected_label
            font = p.font()
            font.setPixelSize(16)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("#34445a"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y - 31, 170, 20), Qt.AlignmentFlag.AlignCenter, label)
            font = p.font()
            font.setPointSize(24)
            p.setFont(font)
            p.setPen(QColor("#222d3e"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y - 9, 170, 38), Qt.AlignmentFlag.AlignCenter,
                       f"{selected_value}%" if selected_value is not None else "--")
            font.setPixelSize(16)
            p.setFont(font)
            p.setPen(QColor("#34445a"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y + 31, 170, 18), Qt.AlignmentFlag.AlignCenter, "LEFT")
            if d.title:
                p.drawText(d.title_x, d.title_y + 8, d.title)
        else:
            p.fillRect(QRectF(0, 0, 240, 240), QColor("#" + s.background))
            if self.images:
                d = self.design
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                p.drawImage(QRectF(d.image_x, d.image_y, 32 * d.image_scale,
                                   32 * d.image_scale), self.images[self.frame % len(self.images)])
                self.draw_battery(p)
                p.end()
                return
            p.setPen(QPen(accent, 2))
            p.setBrush(QColor("#30415c"))
            p.drawRoundedRect(38, 35, 164, 120, 10, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#050912"))
            p.drawRoundedRect(56, 54, 128, 80, 4, 4)
            p.setPen(accent)
            p.drawText(QRectF(56, 54, 128, 80), Qt.AlignmentFlag.AlignCenter,
                       "⌃  ⌃" if s.animation == 2 else "•  •  •")
            p.setBrush(QColor("#30415c"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(80, 155, 80, 40, 6, 6)
            p.drawRect(86, 195, 24, 25)
            p.drawRect(130, 195, 24, 25)
            if s.animation == 2:
                p.setBrush(QColor("#425879"))
                p.setPen(QPen(accent, 2))
                p.drawRoundedRect(58, 151, 99, 49, 3, 3)
                p.drawText(QRectF(58, 151, 99, 49), Qt.AlignmentFlag.AlignCenter, "◇")
        self.draw_battery(p)
        p.setPen(QPen(QColor("#60728d"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, 239, 239)
