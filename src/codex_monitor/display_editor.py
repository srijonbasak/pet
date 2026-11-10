"""A small screen designer for the ESP32's built-in layouts."""

from dataclasses import asdict, replace
from pathlib import Path
import threading

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QImage, QImageReader
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget, QFileDialog, QLineEdit,
    QMessageBox,
)

from .device_usb import DisplaySettings, list_ports
from .device_controller import DeviceController
from .scene import SceneDesign, build_scene
from .utils import read_json_file, write_json_file
from .local_networks import computer_networks
from .image_frames import encode_rgb565, fill_square

DESIGN_FILE = Path(__file__).resolve().parents[2] / "display_design.json"


class _Signals(QObject):
    status = pyqtSignal(str)
    settings = pyqtSignal(object)
    battery = pyqtSignal(object)
    wifi = pyqtSignal(str)


class DisplayPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = DisplaySettings()
        self.design = SceneDesign()
        self.images = []
        self.frame = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(200)
        self.setFixedSize(240, 240)

    def advance(self):
        if self.images:
            self.frame = (self.frame + 1) % len(self.images)
            self.update()

    def draw_battery(self, painter):
        bg = QColor("#" + self.settings.background) if self.settings.mode != 2 else QColor("white")
        color = QColor("white") if bg.lightness() < 128 else QColor("#34445a")
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(182, 10, 22, 11)
        painter.fillRect(204, 13, 2, 5, color)
        painter.setPen(color)
        painter.drawText(210, 19, "--")

    def paintEvent(self, event):
        s = self.settings
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor("#" + s.accent)
        if s.mode == 2:
            p.fillRect(self.rect(), QColor("#ffffff"))
            d = self.design
            if d.usage_style == "bars":
                y = 60
                for bit, label in ((2, "5-HOUR LIMIT"), (4, "WEEKLY LIMIT"), (1, "CONTEXT")):
                    if not s.widgets & bit:
                        continue
                    p.setPen(QColor("#64748a")); p.drawText(30, y + 9, label)
                    p.setPen(QColor("#222d3e")); p.drawText(30, y + 27, "70% LEFT")
                    p.fillRect(30, y + 35, 180, 6, QColor("#e0e6ed"))
                    p.fillRect(30, y + 35, 126, 6, accent)
                    y += 55
                if d.title:
                    p.setPen(QColor("#34445a")); p.drawText(d.title_x, d.title_y + 8, d.title)
                self.draw_battery(p)
                p.end()
                return
            ring = QRectF(d.gauge_x - d.gauge_radius, d.gauge_y - d.gauge_radius,
                          d.gauge_radius * 2, d.gauge_radius * 2)
            p.setPen(QPen(QColor("#e0e6ed"), 9))
            p.drawArc(ring, 225 * 16, -270 * 16)
            p.setPen(QPen(accent, 9))
            p.drawArc(ring, 225 * 16, -190 * 16)
            label = next((label for bit, label in ((2, "5-HOUR LIMIT"),
                         (4, "WEEKLY LIMIT"), (1, "CONTEXT")) if s.widgets & bit), "USAGE")
            p.setPen(QColor("#8795a6"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y - 31, 170, 20), Qt.AlignmentFlag.AlignCenter, label)
            font = p.font()
            font.setPointSize(24)
            p.setFont(font)
            p.setPen(QColor("#222d3e"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y - 9, 170, 38), Qt.AlignmentFlag.AlignCenter, "70%")
            font.setPointSize(9)
            p.setFont(font)
            p.setPen(QColor("#8795a6"))
            p.drawText(QRectF(d.gauge_x - 85, d.gauge_y + 31, 170, 18), Qt.AlignmentFlag.AlignCenter, "LEFT")
            if d.title:
                p.drawText(d.title_x, d.title_y + 8, d.title)
        else:
            p.fillRect(self.rect(), QColor("#" + s.background))
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


class DisplayEditor(QDialog):
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.setWindowTitle("Codex Display Studio")
        self.setObjectName("displayStudio")
        self.resize(860, 760)
        self.setMinimumWidth(720)
        self.setStyleSheet("""
            QDialog#displayStudio { background-color: #101725; color: #e9f0fb; }
            QWidget { font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 14px;
                      color: #e9f0fb; background: transparent; }
            QLabel { color: #cfdaea; }
            QLabel#title { color: #ffffff; font-size: 22px; font-weight: 700; }
            QLabel#subtle { color: #9aabc3; }
            QLabel#status { color: #c1d5f0; background: #17263b; padding: 10px;
                            border: 1px solid #29405f; border-radius: 8px; }
            QComboBox, QSpinBox, QLineEdit { background: #172338; border: 1px solid #384b66;
                                border-radius: 7px; padding: 6px 10px; min-height: 24px;
                                color: #f3f7ff; selection-background-color: #345b91; }
            QComboBox QAbstractItemView { background: #172338; color: #f3f7ff;
                                          selection-background-color: #345b91; }
            QComboBox::drop-down { border: 0; width: 22px; }
            QPushButton { background: #253c60; border: 1px solid #416590; border-radius: 7px;
                          color: #f1f7ff; padding: 8px 14px; font-weight: 600; }
            QPushButton:hover { background: #304e78; }
            QPushButton:disabled { color: #7b8ba1; background: #1b2738; border-color: #304054; }
            QPushButton#send { background: #4678c5; border-color: #6c9bea; color: white; }
            QPushButton#send:hover { background: #5789d7; }
            QPushButton#send:disabled { background: #27364a; border-color: #34465e; color: #7b8ba1; }
            QCheckBox { spacing: 8px; padding: 3px; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #6f86a5;
                                   border-radius: 3px; background: #101725; }
            QCheckBox::indicator:checked { background: #6ea0ff; border-color: #9ec0ff; }
        """)
        self.owns_controller = controller is None
        self.controller = controller or DeviceController(self)
        self.device = self.controller.device
        self.connected = False
        self.dirty = False
        self.loading = False
        self.background = "FFFFFF"
        self.accent = "6EA0FF"
        self.design = SceneDesign()
        self.animation_images = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        title = QLabel("Make the display yours")
        title.setObjectName("title")
        root.addWidget(title)
        intro = QLabel("Your display connects automatically. Choose a screen and send your design over USB.")
        intro.setObjectName("subtle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        connection = QHBoxLayout()
        self.ports = QComboBox()
        self.refresh = QPushButton("Refresh")
        self.refresh.clicked.connect(self.refresh_ports)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        connection.addWidget(self.ports, 1)
        connection.addWidget(self.refresh)
        connection.addWidget(self.connect_button)
        root.addLayout(connection)
        self.status = QLabel("Select your ESP32 USB port to begin.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.device_details = QLabel("Display Wi-Fi: unknown    ·    Battery: --")
        self.device_details.setObjectName("subtle")
        self.device_details.setWordWrap(True)
        self._wifi_detail = "Display Wi-Fi: unknown"
        self._battery_detail = "Battery: --"
        root.addWidget(self.device_details)

        content = QHBoxLayout()
        self.preview = DisplayPreview()
        content.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        self.mode = QComboBox()
        self.mode.addItems(["Alternate screens", "Animation only", "Usage only"])
        self.animation = QComboBox()
        self.animation.addItems(["Desktop scene", "Standing character", "Laptop character"])
        self.animation.setVisible(False)
        self.animation_time = QSpinBox()
        self.animation_time.setRange(2, 60)
        self.animation_time.setSuffix(" sec")
        self.usage_time = QSpinBox()
        self.usage_time.setRange(2, 60)
        self.usage_time.setSuffix(" sec")
        self.checks = []
        for label in ("Context", "5-hour limit", "Weekly limit"):
            check = QCheckBox(label)
            self.checks.append(check)
        self.battery_check = QCheckBox("Enable battery sensor (GPIO1, 2:1 divider)")
        self.battery_check.setToolTip("Enable only if your battery voltage is connected to GPIO1 through a suitable 2:1 voltage divider.")
        self.background_button = QPushButton("Choose background")
        self.accent_button = QPushButton("Choose accent")
        self.background_button.clicked.connect(lambda: self.choose_color("background"))
        self.accent_button.clicked.connect(lambda: self.choose_color("accent"))
        form.addRow("Screen", self.mode)
        form.addRow("Animation time", self.animation_time)
        form.addRow("Usage time", self.usage_time)
        for check in self.checks:
            form.addRow("", check)
        form.addRow("", self.battery_check)
        form.addRow("Background", self.background_button)
        form.addRow("Accent", self.accent_button)
        content.addLayout(form, 1)
        root.addLayout(content)
        design_row = QHBoxLayout()
        edit_design = QPushButton("Edit layout & animation…")
        edit_design.clicked.connect(self.edit_design)
        initialize = QPushButton("Initialize storage…")
        initialize.clicked.connect(self.initialize_storage)
        wifi = QPushButton("Set up Wi-Fi…")
        wifi.clicked.connect(self.configure_wifi)
        design_row.addWidget(edit_design, 1)
        design_row.addWidget(wifi)
        design_row.addWidget(initialize)
        root.addLayout(design_row)
        note = QLabel("Preview shows an example value. Changes are saved on the device when sent.")
        note.setObjectName("subtle")
        note.setWordWrap(True)
        root.addWidget(note)
        self.frame_hint = QLabel("")
        self.frame_hint.setObjectName("subtle")
        self.frame_hint.setWordWrap(True)
        root.addWidget(self.frame_hint)
        self.send = QPushButton("Send to display")
        self.send.setObjectName("send")
        self.send.setEnabled(False)
        self.send.clicked.connect(self.send_settings)
        root.addWidget(self.send)

        for combo in (self.mode, self.animation):
            combo.currentIndexChanged.connect(self._changed)
        for spin in (self.animation_time, self.usage_time):
            spin.valueChanged.connect(self._changed)
        for check in self.checks:
            check.toggled.connect(self._changed)
        self.battery_check.toggled.connect(self._changed)
        self._apply_settings(DisplaySettings())
        self.refresh_ports()
        self._restore_design()
        self._refresh_animation_hint()
        self.controller.status.connect(self._status_changed)
        self.controller.settings.connect(self._load_device_settings)
        self.controller.battery.connect(self._battery_changed)
        self.controller.wifi.connect(self._wifi_changed)
        self.connected = self.controller.connected
        self._status_changed(self.controller.last_status)
        if self.connected:
            self.connect_button.setText("Disconnect")
            self.send.setEnabled(True)
        self._wifi_changed(self.controller.last_wifi)
        self._battery_changed(self.controller.last_battery)
        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self._refresh_disconnected_ports)
        self.port_timer.start(3000)

    def _refresh_disconnected_ports(self):
        if not self.ports.view().isVisible():
            self.refresh_ports()

    def refresh_ports(self):
        selected = self.ports.currentData()
        self.ports.clear()
        for path, description in list_ports():
            self.ports.addItem(f"{path} · {description}", path)
        if self.ports.count() == 0:
            self.ports.addItem("No USB device found — plug in ESP32 and refresh", None)
            if not self.connected:
                self.status.setText("Connect the ESP32 with a data USB cable, close Arduino Serial Monitor, then refresh.")
        index = self.ports.findData(selected)
        if self.controller.active_port:
            index = self.ports.findData(self.controller.active_port)
        if index >= 0:
            self.ports.setCurrentIndex(index)

    def toggle_connection(self):
        if self.connected:
            self.controller.disconnect()
            self.connected = False
            self.send.setEnabled(False)
            self.connect_button.setText("Connect")
            return
        port = self.ports.currentData()
        if not port:
            self.status.setText("Connect the ESP32, then refresh the port list.")
            return
        if self.controller.connect_port(port):
            self.connect_button.setText("Connecting…")
            self.connect_button.setEnabled(False)

    def _status_changed(self, status):
        self.status.setText(status)
        if status.startswith("Connected to "):
            self.connected = True
            self.connect_button.setText("Disconnect")
            self.connect_button.setEnabled(True)
            self.send.setEnabled(True)
        elif status.startswith(("USB connection failed", "No response", "USB disconnected")):
            self.connected = False
            self.connect_button.setText("Connect")
            self.connect_button.setEnabled(True)
            self.send.setEnabled(False)
            self._wifi_changed("Display Wi-Fi: unknown")
            self._battery_changed(None)
        elif status.startswith(("Screen design saved", "Settings saved", "Display rejected",
                                "Display storage unavailable", "Scene upload timed out",
                                "No confirmation", "Upload the new", "Upload the updated")):
            self.send.setEnabled(self.connected)

    def _settings(self):
        mask = sum((1 << i) for i, check in enumerate(self.checks) if check.isChecked())
        return DisplaySettings(self.mode.currentIndex(), self.animation.currentIndex(),
                               self.animation_time.value(), self.usage_time.value(), mask,
                               self.background, self.accent)

    def _refresh_animation_hint(self):
        count = len(self.design.frames)
        if count == 1:
            self.frame_hint.setText("Your saved image has one frame. Import an animated GIF for motion.")
        elif count > 1:
            self.frame_hint.setText(f"Animation: {count} frames · {self.design.frame_ms} ms per frame.")
        else:
            self.frame_hint.setText("The default character is still. Import an animated GIF for motion.")

    def _battery_changed(self, value):
        self._battery_detail = f"Battery: {value}%" if value is not None else "Battery: --"
        self.device_details.setText(f"{self._wifi_detail}    ·    {self._battery_detail}")

    def _wifi_changed(self, value):
        self._wifi_detail = value
        self.device_details.setText(f"{self._wifi_detail}    ·    {self._battery_detail}")

    def _changed(self, *args):
        if self.loading:
            return
        self.design = replace(self.design, show_battery=self.battery_check.isChecked())
        self.preview.design = self.design
        self.dirty = True
        self.preview.settings = self._settings()
        self.preview.update()

    def _apply_settings(self, settings):
        self.loading = True
        self.mode.setCurrentIndex(settings.mode)
        self.animation.setCurrentIndex(settings.animation)
        self.animation_time.setValue(settings.animation_seconds)
        self.usage_time.setValue(settings.usage_seconds)
        for i, check in enumerate(self.checks):
            check.setChecked(bool(settings.widgets & (1 << i)))
        self.battery_check.setChecked(self.design.show_battery)
        self.background, self.accent = settings.background, settings.accent
        self.preview.settings = settings
        self.preview.update()
        self.loading = False
        self.dirty = False

    def _load_device_settings(self, settings):
        if not self.dirty:
            self._apply_settings(settings)

    def choose_color(self, attribute):
        color = QColorDialog.getColor(QColor("#" + getattr(self, attribute)), self)
        if color.isValid():
            setattr(self, attribute, color.name()[1:].upper())
            self._changed()

    def send_settings(self):
        try:
            settings = self._settings()
            self.device.send_settings(settings, build_scene(settings, self.design), self.design.show_battery)
            self._save_design()
            self.dirty = False
            self.send.setEnabled(False)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _save_design(self):
        write_json_file(DESIGN_FILE, {"version": 1, "settings": asdict(self._settings()),
                                      "design": asdict(self.design)})

    def _restore_design(self):
        saved = read_json_file(DESIGN_FILE)
        if not isinstance(saved, dict) or saved.get("version") != 1:
            return
        try:
            settings = DisplaySettings(**saved["settings"])
            data = dict(saved["design"])
            data["frames"] = tuple(data.get("frames", ()))
            design = SceneDesign(**data)
            settings.packet()
            build_scene(settings, design)
            images = []
            for encoded in design.frames:
                image = QImage(32, 32, QImage.Format.Format_RGB32)
                for i in range(1024):
                    rgb = int(encoded[i * 4:i * 4 + 4], 16)
                    r, g, b = (rgb >> 11) & 31, (rgb >> 5) & 63, rgb & 31
                    image.setPixelColor(i % 32, i // 32, QColor(r * 255 // 31, g * 255 // 63, b * 255 // 31))
                images.append(image)
            self.design, self.animation_images = design, images
            self._apply_settings(settings)
            self.preview.design, self.preview.images = design, images
            self.preview.timer.setInterval(design.frame_ms)
            self.preview.update()
            self.dirty = True  # Keep the desktop design when a device reports older settings.
        except (KeyError, TypeError, ValueError):
            self.status.setText("Could not open the saved desktop design; using defaults.")

    def initialize_storage(self):
        if not self.connected:
            self.status.setText("Connect the ESP32 before initializing storage.")
            return
        answer = QMessageBox.warning(self, "Initialize display storage",
            "If the display storage is unformatted or damaged, this formats its SPIFFS partition and erases files stored there. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.device.initialize_storage()

    def configure_wifi(self):
        if not self.connected:
            self.status.setText("Connect the ESP32 by USB before setting up Wi-Fi.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Connect display to Wi-Fi")
        dialog.resize(570, 350)
        dialog.setStyleSheet("QDialog { background: #101725; }")
        root = QVBoxLayout(dialog)
        info = QLabel("Enter a 2.4 GHz Wi-Fi network. Credentials are sent over USB and saved on the ESP32.")
        info.setWordWrap(True)
        root.addWidget(info)
        form = QFormLayout()
        ssid = QComboBox()
        ssid.setEditable(True)
        ssid.setMinimumWidth(350)
        ssid.lineEdit().setPlaceholderText("Choose a network or type its name")
        password = QLineEdit(); password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("Password (leave empty for an open network)")
        form.addRow("Network", ssid); form.addRow("Password", password)
        root.addLayout(form)
        error = QLabel(""); error.setWordWrap(True); root.addWidget(error)
        scan_status = QLabel("Scanning for nearby 2.4 GHz networks…")
        scan_status.setWordWrap(True)
        root.addWidget(scan_status)
        scan_button = QPushButton("Scan networks")
        root.addWidget(scan_button)
        found = set()
        active = threading.Event()
        active.set()
        generation = [0]
        def scan():
            generation[0] += 1
            found.clear()
            ssid.clear()
            scan_status.setText("Scanning for nearby 2.4 GHz networks…")
            self.device.scan_networks()
        def computer_fallback():
            current = generation[0]
            scan_status.setText("Display scan unavailable; checking this computer's network list…")
            def worker():
                networks = computer_networks()
                if active.is_set():
                    try:
                        self.controller.network.emit(("computer_result", current, networks))
                    except RuntimeError:
                        pass
            threading.Thread(target=worker, name="wifi-list", daemon=True).start()
        def network_event(event):
            if not event:
                return
            if event[0] == "item":
                _, name, signal, is_open = event
                if name not in found:
                    found.add(name)
                    ssid.addItem(name)
                    ssid.setItemData(ssid.count() - 1,
                                     f"{signal} dBm · {'open' if is_open else 'secured'}",
                                     Qt.ItemDataRole.ToolTipRole)
            elif event[0] == "done":
                if found:
                    scan_status.setText(f"Found {len(found)} network(s). You can also type a hidden network name.")
                else:
                    computer_fallback()
            elif event[0] == "failed":
                computer_fallback()
            elif event[0] == "unsupported":
                computer_fallback()
            elif event[0] == "computer_result" and event[1] == generation[0]:
                for name, strength, is_open in event[2]:
                    if name not in found:
                        found.add(name)
                        ssid.addItem(name)
                        ssid.setItemData(ssid.count() - 1,
                                         f"Computer Wi-Fi · {strength}% signal · {'open' if is_open else 'secured'}",
                                         Qt.ItemDataRole.ToolTipRole)
                scan_status.setText(
                    f"Found {len(found)} network(s) on this computer; display reception may differ."
                    if found else "No networks found. Check 2.4 GHz Wi-Fi or type the network name manually."
                )
        scan_button.clicked.connect(scan)
        self.controller.network.connect(network_event)
        send = QPushButton("Connect display")
        def submit():
            try:
                self.device.set_wifi(ssid.currentText(), password.text())
            except ValueError as exc:
                error.setText(str(exc)); return
            password.clear()
            self.status.setText("Sending Wi-Fi settings to display…")
            dialog.accept()
        send.clicked.connect(submit)
        root.addWidget(send)
        QTimer.singleShot(0, scan)
        try:
            dialog.exec()
        finally:
            active.clear()
            try:
                self.controller.network.disconnect(network_event)
            except (TypeError, RuntimeError):
                pass

    def edit_design(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Layout & animation")
        dialog.resize(640, 720)
        dialog.setStyleSheet("QDialog { background: #101725; }")
        root = QVBoxLayout(dialog)
        form = QFormLayout()
        style = QComboBox()
        style.addItem("Circular gauge", "gauge")
        style.addItem("Usage bars", "bars")
        style.setCurrentIndex(max(0, style.findData(self.design.usage_style)))
        form.addRow("Usage layout", style)
        fields = {}
        for name, label, minimum, maximum in (
            ("gauge_x", "Gauge center X", 0, 239), ("gauge_y", "Gauge center Y", 0, 239),
            ("gauge_radius", "Gauge radius", 30, 100), ("title_x", "Title X", 0, 230),
            ("title_y", "Title Y", 0, 230), ("image_x", "Animation X", 0, 208),
            ("image_y", "Animation Y", 0, 208), ("image_scale", "Animation scale", 1, 6),
            ("frame_ms", "Frame time (ms)", 80, 2000)):
            spin = QSpinBox(); spin.setRange(minimum, maximum); spin.setValue(getattr(self.design, name))
            fields[name] = spin; form.addRow(label, spin)
        title = QLineEdit(self.design.title)
        title.setMaxLength(34)
        form.addRow("Usage title", title)
        root.addLayout(form)
        image_info = QLabel(("1 frame: still image (import an animated GIF for motion)" if len(self.animation_images) == 1
                             else f"{len(self.animation_images)} imported frames") if self.animation_images else "Default character")
        image_info.setWordWrap(True)
        root.addWidget(image_info)
        frames = list(self.design.frames)
        images = list(self.animation_images)

        def import_image():
            path, _ = QFileDialog.getOpenFileName(dialog, "Choose animation", "", "Images (*.gif *.png *.jpg *.jpeg *.webp)")
            if not path:
                return
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            loaded, encoded = [], []
            while len(loaded) < 12:
                image = reader.read()
                if image.isNull():
                    break
                frame = QImage(32, 32, QImage.Format.Format_RGB32)
                frame.fill(QColor("#" + self.background))
                scaled = image.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                painter = QPainter(frame)
                painter.drawImage((32 - scaled.width()) // 2, (32 - scaled.height()) // 2, scaled)
                painter.end()
                loaded.append(frame); encoded.append(encode_rgb565(frame))
                if len(loaded) == 1:
                    delay = reader.nextImageDelay()
                    if 80 <= delay <= 2000:
                        fields["frame_ms"].setValue(delay)
                if not reader.supportsAnimation():
                    break
            if not loaded:
                image_info.setText("Could not read that image.")
                return
            images[:] = loaded; frames[:] = encoded
            fields["image_x"].setValue(24)
            fields["image_y"].setValue(24)
            fields["image_scale"].setValue(6)
            image_info.setText("1 frame: still image (import an animated GIF for motion)" if len(images) == 1
                               else f"{len(images)} frames imported · first 12 frames · enlarged to 192 px")

        buttons = QHBoxLayout()
        load = QPushButton("Import GIF or image…"); load.clicked.connect(import_image)
        clear = QPushButton("Use default character")
        def clear_image():
            frames.clear(); images.clear(); image_info.setText("Default character")
        clear.clicked.connect(clear_image)
        buttons.addWidget(load); buttons.addWidget(clear); root.addLayout(buttons)
        fill = QPushButton("Fill display — crop image edges")
        def fill_image():
            if not images:
                image_info.setText("Import an image or GIF first; the default character is already enlarged.")
                return
            fitted = fill_square(images)
            images[:] = fitted
            frames[:] = [encode_rgb565(frame) for frame in fitted]
            fields["image_x"].setValue(24)
            fields["image_y"].setValue(24)
            fields["image_scale"].setValue(6)
            image_info.setText("Image enlarged to 192 px. Edges may be cropped; apply to preview.")
        fill.clicked.connect(fill_image)
        root.addWidget(fill)
        apply = QPushButton("Apply to preview")
        def accept():
            candidate = replace(self.design, **{name: spin.value() for name, spin in fields.items()},
                                usage_style=style.currentData(),
                                title=title.text(), frames=tuple(frames))
            try:
                build_scene(self._settings(), candidate)
            except ValueError as exc:
                image_info.setText(str(exc)); return
            self.design = candidate
            self.animation_images = images
            self.preview.design = candidate
            self.preview.images = images
            self.preview.frame = 0
            self.preview.timer.setInterval(candidate.frame_ms)
            self.preview.update()
            self._refresh_animation_hint()
            self.dirty = True
            dialog.accept()
        apply.clicked.connect(accept)
        root.addWidget(apply)
        dialog.exec()

    def closeEvent(self, event):
        self.port_timer.stop()
        for signal, callback in ((self.controller.status, self._status_changed),
                                 (self.controller.settings, self._load_device_settings),
                                 (self.controller.battery, self._battery_changed),
                                 (self.controller.wifi, self._wifi_changed)):
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass
        if self.owns_controller:
            self.controller.close()
        super().closeEvent(event)
