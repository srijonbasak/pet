"""Small, calm Codex usage window with no polling-heavy UI work."""

import sys

from PyQt6.QtCore import QPoint, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from .bluetooth import get_bluetooth_status, register_bluetooth_status_callback
from .monitor import get_latest_state, register_state_callback
from .wifi_transport import get_wifi_status, register_wifi_status_callback, resend_latest
from .widgets.radial_chart import AnimatedRadialChart


class Signals(QObject):
    state = pyqtSignal(object)
    bluetooth = pyqtSignal(str)
    wifi = pyqtSignal(str)


class DragBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.origin = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if not (handle and handle.startSystemMove()):
                self.origin = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and not self.origin.isNull():
            self.window().move(event.globalPosition().toPoint() - self.origin)


class Metric(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(2)
        caption = QLabel(title.upper())
        caption.setObjectName("caption")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        self.detail = QLabel("Waiting for usage data")
        self.detail.setObjectName("muted")
        layout.addWidget(caption)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_usage(self, value, reset):
        self.value.setText(f"{value}% left" if value is not None else "—")
        self.detail.setText(f"Resets {reset}" if reset else "Usage unavailable")


class CodexWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codex Usage")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(420, 610)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        self.card = QFrame()
        self.card.setObjectName("card")
        outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(25, 20, 25, 24)
        root.setSpacing(14)

        bar = DragBar()
        bar.setObjectName("drag")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 0, 0, 0)
        mark = QLabel("◆")
        mark.setObjectName("mark")
        brand = QLabel("CODEX")
        brand.setObjectName("brand")
        close = QPushButton("×")
        close.setObjectName("close")
        close.clicked.connect(self.close)
        bar_row.addWidget(mark)
        bar_row.addWidget(brand)
        bar_row.addStretch()
        bar_row.addWidget(close)
        root.addWidget(bar)

        eyebrow = QLabel("LIVE USAGE")
        eyebrow.setObjectName("caption")
        self.project = QLabel("Looking for a Codex session…")
        self.project.setObjectName("project")
        self.project.setWordWrap(True)
        self.chat = QLabel("Local data stays on this computer")
        self.chat.setObjectName("muted")
        self.chat.setWordWrap(True)
        root.addWidget(eyebrow)
        root.addWidget(self.project)
        root.addWidget(self.chat)

        self.chart = AnimatedRadialChart()
        self.chart.setFixedHeight(190)
        root.addWidget(self.chart)
        self.context = QLabel("— / — tokens")
        self.context.setObjectName("centerMuted")
        root.addWidget(self.context)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.five = Metric("5 hour")
        self.week = Metric("Weekly")
        row.addWidget(self.five)
        row.addWidget(self.week)
        root.addLayout(row)

        connection = QFrame()
        connection.setObjectName("connection")
        c_layout = QVBoxLayout(connection)
        c_layout.setContentsMargins(14, 12, 14, 12)
        self.wifi = QLabel(get_wifi_status())
        self.ble = QLabel(get_bluetooth_status())
        self.wifi.setObjectName("connectionText")
        self.ble.setObjectName("connectionText")
        c_layout.addWidget(self.wifi)
        c_layout.addWidget(self.ble)
        root.addWidget(connection)

        sync = QPushButton("Send update")
        sync.setObjectName("sync")
        sync.clicked.connect(resend_latest)
        root.addWidget(sync)

        self.setStyleSheet("""
            QWidget { color:#f2f4f3; font-family:"Inter","Segoe UI",sans-serif; background:transparent; }
            QFrame#card { background:#101521; border:1px solid #283853; border-radius:24px; }
            QFrame#drag { border:0; } QLabel#mark { color:#6ea0ff; font-size:18px; }
            QLabel#brand { font-size:12px; font-weight:800; letter-spacing:3px; color:#d9dfdc; }
            QLabel#caption { color:#7f8b86; font-size:10px; font-weight:800; letter-spacing:2px; }
            QLabel#project { color:#fff; font-size:22px; font-weight:650; }
            QLabel#muted { color:#8f9995; font-size:11px; }
            QLabel#centerMuted { color:#8f9995; font-size:11px; qproperty-alignment:AlignCenter; }
            QFrame#metric { background:#151d2d; border:1px solid #293a57; border-radius:14px; }
            QLabel#metricValue { color:#f7faf8; font-size:20px; font-weight:700; }
            QFrame#connection { background:#0b101b; border:1px solid #24334d; border-radius:12px; }
            QLabel#connectionText { color:#aab3af; font-size:11px; }
            QPushButton#close { color:#78817d; border:0; font-size:22px; width:28px; }
            QPushButton#close:hover { color:#fff; }
            QPushButton#sync { min-height:38px; color:#f0f6ff; background:#1d3153; border:1px solid #365d99;
                               border-radius:10px; font-weight:700; }
            QPushButton#sync:hover { background:#27436f; }
        """)

        self.signals = Signals()
        self.signals.state.connect(self.update_state)
        self.signals.bluetooth.connect(self.ble.setText)
        self.signals.wifi.connect(self.wifi.setText)
        register_state_callback(self.signals.state.emit)
        register_bluetooth_status_callback(self.signals.bluetooth.emit)
        register_wifi_status_callback(self.signals.wifi.emit)

    def update_state(self, state):
        self.project.setText(state.project or "No active Codex project")
        self.chat.setText(state.chat or "Waiting for the next Codex event")
        self.chart.set_value(state.context_left, "Context left", "")
        used = f"{state.context_used:,}" if state.context_used is not None else "—"
        maximum = f"{state.context_max:,}" if state.context_max is not None else "—"
        self.context.setText(f"{used} / {maximum} tokens")
        self.five.set_usage(state.limit_5h_left, state.limit_5h_reset)
        self.week.set_usage(state.limit_7d_left, state.limit_7d_reset)


def run_gui():
    app = QApplication(sys.argv)
    app.setApplicationName("Codex Usage")
    widget = CodexWidget()
    initial = get_latest_state()
    if initial:
        widget.update_state(initial)
    widget.show()
    return app.exec()
