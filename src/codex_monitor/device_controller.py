"""Keep the USB connection alive for the lifetime of the desktop app."""

import time
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal

from .device_usb import DeviceUSB, find_auto_port


class DeviceController(QObject):
    status = pyqtSignal(str)
    settings = pyqtSignal(object)
    battery = pyqtSignal(object)
    wifi = pyqtSignal(str)
    network = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        path = Path(__file__).resolve().parents[2] / ".device_settings.ini"
        self.preferences = QSettings(str(path), QSettings.Format.IniFormat)
        self.preferred_port = self.preferences.value("usb_port", "", type=str)
        self.active_port = None
        self.connected = False
        self.paused = False
        self.last_status = "Looking for an ESP32 USB display…"
        self.last_settings = None
        self.last_battery = None
        self.last_wifi = "Display Wi-Fi: unknown"
        self._last_attempt = 0.0
        self.device = DeviceUSB(self.status.emit, self.settings.emit, self.battery.emit,
                                self.wifi.emit, self.network.emit)
        self.status.connect(self._record_status)
        self.settings.connect(self._record_settings)
        self.battery.connect(self._record_battery)
        self.wifi.connect(self._record_wifi)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._auto_connect)
        self.timer.start(3000)
        QTimer.singleShot(0, self._auto_connect)

    def _record_status(self, message):
        self.last_status = message
        if message.startswith("Connected to "):
            self.connected = True
            self.active_port = message[len("Connected to "):]
            self.preferred_port = self.active_port
            self.preferences.setValue("usb_port", self.preferred_port)
        elif message.startswith(("USB connection failed", "No response", "USB disconnected")):
            self.connected = False
            self.active_port = None
            self.last_battery = None
            self.last_wifi = "Display Wi-Fi: unknown"

    def _record_settings(self, settings):
        self.last_settings = settings

    def _record_battery(self, value):
        self.last_battery = value

    def _record_wifi(self, value):
        self.last_wifi = value

    def _auto_connect(self):
        if self.paused or self.device.is_running() or time.monotonic() - self._last_attempt < 8:
            return
        port = find_auto_port(self.preferred_port)
        if port:
            self._last_attempt = time.monotonic()
            self.device.connect(port)

    def connect_port(self, port):
        self.paused = False
        if self.device.is_running():
            return False
        self._last_attempt = time.monotonic()
        return self.device.connect(port)

    def disconnect(self):
        self.paused = True
        self.device.disconnect()

    def close(self):
        self.timer.stop()
        self.device.close()
