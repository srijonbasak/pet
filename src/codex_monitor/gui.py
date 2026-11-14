"""Desktop entry point for the integrated display studio."""

import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .studio_window import StudioWindow

# Keep the old import usable by launchers while presenting a single app window.
CodexWidget = StudioWindow


def run_gui():
    app = QApplication(sys.argv)
    app.setApplicationName("Codex Display Studio")
    widget = StudioWindow()
    widget.show()
    previous_sigint = signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)
    app.aboutToQuit.connect(widget.close)
    try:
        return app.exec()
    finally:
        signal_timer.stop()
        signal.signal(signal.SIGINT, previous_sigint)
