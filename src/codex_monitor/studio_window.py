"""The integrated desktop studio: one canvas, one document, one device owner."""

import threading
from dataclasses import asdict, replace

from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFormLayout, QComboBox, QSpinBox, QCheckBox, QLineEdit, QStackedWidget,
    QScrollArea, QFileDialog, QColorDialog, QMessageBox, QProgressBar, QButtonGroup,
)

from .device_controller import DeviceController
from .device_usb import DisplaySettings, list_ports
from .display_preview import DisplayPreview
from .scene import SceneDesign, build_scene, DESIGN_FILE
from .image_frames import encode_rgb565, fill_square
from .local_networks import computer_networks
from .monitor import get_latest_state, register_state_callback, unregister_state_callback
from .bluetooth import get_bluetooth_status, register_bluetooth_status_callback, unregister_bluetooth_status_callback
from .wifi_transport import get_wifi_status, register_wifi_status_callback, unregister_wifi_status_callback
from .utils import read_json_file, write_json_file
from .studio_theme import STYLE
from .studio_widgets import CanvasStage, DeviceBezel, StudioMark, Toggle, line_icon


class StudioSignals(QObject):
    state = pyqtSignal(object)
    bluetooth = pyqtSignal(str)
    broadcast = pyqtSignal(str)
    computer_networks = pyqtSignal(object)


def label(text, name=None, wrap=False):
    if name == "section" and text.isupper():
        text = text.capitalize().replace("Usb", "USB").replace("Wi-fi", "Wi-Fi")
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def action(text, callback, primary=False):
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    if primary:
        result.setObjectName("primary")
    return result


class MetricCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 14, 17, 14)
        layout.setSpacing(5)
        layout.addWidget(label(title, "section"))
        self.value = label("--", "metricValue")
        self.detail = label("Waiting for usage", "muted")
        layout.addWidget(self.value)
        layout.addWidget(self.detail)
        self.track = QProgressBar()
        self.track.setRange(0, 100)
        self.track.setTextVisible(False)
        self.track.setFixedHeight(3)
        self.track.setValue(0)
        layout.addSpacing(6)
        layout.addWidget(self.track)

    def set_value(self, value, detail):
        self.value.setText(f"{value}%" if value is not None else "--")
        self.detail.setText(detail)
        self.track.setValue(round(max(0, min(100, value or 0))))


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codex Display Studio")
        self.resize(1320, 860)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self.controller = DeviceController(self)
        self.signals = StudioSignals(self)
        self.settings = DisplaySettings()
        self.design = SceneDesign()
        self.images = []
        self.state = get_latest_state()
        self.loading = False
        self.dirty = False
        self.busy = False
        self.closed = False
        self.page = 0
        self.preview_kind = "usage"
        self._scan_generation = 0
        self._scan_pending = False
        self._networks = set()
        self._last_preview = None
        self._last_ports = None
        self._last_saved_document = None
        self._rendered_state = None
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.timeout.connect(self._save_draft)
        self._restore()

        root = QWidget()
        root.setObjectName("studio")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._sidebar())

        workspace = QVBoxLayout()
        workspace.setContentsMargins(26, 22, 26, 16)
        workspace.setSpacing(20)
        shell.addLayout(workspace, 1)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(label("Personal workspace", "muted"))
        self.heading = label("Display studio", "heading")
        titles.addWidget(self.heading)
        top.addLayout(titles, 1)
        self.usb_chip = label("USB · searching", "chip")
        self.ble_chip = label("BLE · searching", "chip")
        self.battery_chip = label("BAT · --", "chip")
        for chip in (self.usb_chip, self.ble_chip, self.battery_chip):
            chip.setFixedHeight(29)
        top.addWidget(self.usb_chip)
        self.apply_button = action("Apply to device", self.apply_to_device, True)
        self.apply_button.setEnabled(False)
        top.addSpacing(10)
        top.addWidget(self.apply_button)
        workspace.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(20)
        workspace.addLayout(body, 1)
        body.addWidget(self._canvas_panel(), 1)
        inspector = QFrame()
        inspector.setObjectName("inspector")
        inspector.setFixedWidth(340)
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(20, 20, 20, 20)
        self.inspector_heading = label("Your workspace", "panelHeading")
        inspector_layout.addWidget(self.inspector_heading)
        self.pages = QStackedWidget()
        for content in (self._overview(), self._design_page(), self._animation_page(), self._device_page()):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            self.pages.addWidget(scroll)
        inspector_layout.addWidget(self.pages, 1)
        body.addWidget(inspector)

        footer = QHBoxLayout()
        footer_text = QVBoxLayout()
        self.status = label(self.controller.last_status, "status", True)
        self.draft = label("Saved on this computer", "muted")
        footer_text.addWidget(self.status)
        footer_text.addWidget(self.draft)
        footer.addLayout(footer_text, 1)
        footer.addWidget(self.ble_chip)
        footer.addWidget(self.battery_chip)
        workspace.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        workspace.addWidget(self.progress)

        self.signals.state.connect(self.update_state)
        self.signals.bluetooth.connect(self._bluetooth_status)
        self.signals.broadcast.connect(self.broadcast_label.setText)
        self.signals.computer_networks.connect(self._computer_network_results)
        self._state_callback = self.signals.state.emit
        self._bluetooth_callback = self.signals.bluetooth.emit
        self._broadcast_callback = self.signals.broadcast.emit
        register_state_callback(self._state_callback)
        register_bluetooth_status_callback(self._bluetooth_callback)
        register_wifi_status_callback(self._broadcast_callback)
        self.controller.status.connect(self._device_status)
        self.controller.settings.connect(self._device_settings)
        self.controller.battery.connect(self._battery_status)
        self.controller.wifi.connect(self.wifi_state.setText)
        self.controller.network.connect(self._network_result)
        self.controller.progress.connect(self._upload_progress)
        self._sync_controls()
        self._refresh_preview()
        self._bluetooth_status(get_bluetooth_status())
        self.refresh_ports()
        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self.refresh_ports)
        self.port_timer.start(4000)
        if self.state:
            self.update_state(self.state)

    def _sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(176)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(17, 24, 17, 22)
        layout.setSpacing(8)
        brand = QHBoxLayout()
        brand.addWidget(StudioMark())
        brand.addSpacing(5)
        brand.addWidget(label("codex", "brand"))
        layout.addLayout(brand)
        layout.addWidget(label("Display studio", "muted"))
        layout.addSpacing(37)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i, (title, icon) in enumerate((("Overview", "overview"), ("Design", "design"),
                                          ("Animations", "animation"), ("Device", "device"))):
            button = QPushButton(title)
            button.setIcon(line_icon(icon))
            button.setIconSize(QSize(20, 20))
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(button, i)
            button.clicked.connect(lambda checked, index=i: self.navigate(index))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch()
        layout.addWidget(label("ESP32-C3\n240 × 240 display", "muted"))
        layout.addSpacing(14)
        self.side_connection = label("○  Finding display", "status", True)
        layout.addWidget(self.side_connection)
        return frame

    def _canvas_panel(self):
        surface = CanvasStage()
        surface.setObjectName("surface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(15)
        row = QHBoxLayout()
        row.addWidget(label("Device preview", "panelHeading"))
        row.addStretch()
        self.usage_tab = QPushButton("Usage")
        self.animation_tab = QPushButton("Animation")
        group = QButtonGroup(surface)
        for button, kind in ((self.usage_tab, "usage"), (self.animation_tab, "animation")):
            button.setCheckable(True)
            button.setObjectName("segment")
            group.addButton(button)
            button.clicked.connect(lambda checked, value=kind: self.set_preview_kind(value))
            row.addWidget(button)
        self.usage_tab.setChecked(True)
        layout.addLayout(row)
        layout.addStretch(1)
        bezel = DeviceBezel()
        self.bezel = bezel
        bezel.setObjectName("bezel")
        b = QVBoxLayout(bezel)
        b.setContentsMargins(17, 17, 17, 17)
        self.preview = DisplayPreview()
        self.preview.setFixedSize(340, 340)
        b.addWidget(self.preview)
        bezel.setFixedSize(378, 378)
        layout.addWidget(bezel, 0, Qt.AlignmentFlag.AlignHCenter)
        self.canvas_caption = label("240 × 240 · Live usage", "canvasCaption")
        self.canvas_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.canvas_caption)
        metric_row = QHBoxLayout()
        metric_row.addStretch()
        self.metric_buttons = QButtonGroup(surface)
        for key, title in (("five", "5 hour"), ("week", "Weekly"), ("context", "Context")):
            button = QPushButton(title)
            button.setObjectName("segment")
            button.setCheckable(True)
            self.metric_buttons.addButton(button)
            button.clicked.connect(lambda checked, value=key: self.set_preview_metric(value))
            metric_row.addWidget(button)
            if key == "five":
                button.setChecked(True)
        metric_row.addStretch()
        layout.addLayout(metric_row)
        layout.addStretch(1)
        cards = QHBoxLayout()
        self.five_card, self.week_card, self.context_card = MetricCard("5-HOUR WINDOW"), MetricCard("THIS WEEK"), MetricCard("CONTEXT")
        for card in (self.five_card, self.week_card, self.context_card):
            cards.addWidget(card)
        layout.addLayout(cards)
        return surface

    def _panel(self, intro):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 12, 5, 0)
        layout.setSpacing(16)
        layout.addWidget(label(intro, "muted", True))
        return widget, layout

    def _overview(self):
        widget, layout = self._panel("Your session, at a glance. Changes arrive on the display as you work.")
        layout.addWidget(label("ACTIVE PROJECT", "section"))
        self.project_label = label("Waiting for Codex", "panelHeading", True)
        self.chat_label = label("Open a local Codex session to see live usage.", "muted", True)
        layout.addWidget(self.project_label)
        layout.addWidget(self.chat_label)
        layout.addSpacing(10)
        layout.addWidget(label("YOUR DISPLAY", "section"))
        self.overview_device = label("Looking for the USB display…", "status", True)
        layout.addWidget(self.overview_device)
        layout.addWidget(action("Customize the screen  →", lambda: self.navigate(1)))
        layout.addWidget(action("Choose an animation  →", lambda: self.navigate(2)))
        layout.addSpacing(12)
        self.session_detail = label("Context details will appear here.", "muted", True)
        layout.addWidget(self.session_detail)
        layout.addStretch()
        layout.addWidget(label("The canvas uses live values. Layout edits stay local until you apply them.", "muted", True))
        return widget

    def _spin(self, minimum, maximum, callback):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.valueChanged.connect(callback)
        return spin

    def _design_page(self):
        widget, layout = self._panel("Shape your screen. Every change appears on the canvas.")
        form = QFormLayout()
        form.setVerticalSpacing(13)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = QComboBox()
        self.mode.addItems(["Alternate screens", "Animation only", "Usage only"])
        self.mode.currentIndexChanged.connect(self._edit_settings)
        self.style = QComboBox()
        self.style.addItems(["Circular gauge", "Usage bars"])
        self.style.currentIndexChanged.connect(self._edit_design)
        form.addRow("Screen mode", self.mode)
        form.addRow("Usage layout", self.style)
        layout.addLayout(form)
        layout.addWidget(label("VISIBLE VALUES", "section"))
        self.widget_checks = []
        for title in ("Context remaining", "5-hour limit", "Weekly limit"):
            check = Toggle(title)
            check.toggled.connect(self._edit_settings)
            layout.addWidget(check)
            self.widget_checks.append(check)
        layout.addWidget(label("COLOR PALETTE", "section"))
        colors = QHBoxLayout()
        self.accent_button = action("Accent", lambda: self.choose_color("accent"))
        self.background_button = action("Canvas", lambda: self.choose_color("background"))
        colors.addWidget(self.accent_button)
        colors.addWidget(self.background_button)
        layout.addLayout(colors)
        layout.addWidget(label("PLACEMENT", "section"))
        geometry = QFormLayout()
        self.gauge_x = self._spin(30, 209, self._edit_design)
        self.gauge_y = self._spin(30, 209, self._edit_design)
        self.gauge_radius = self._spin(30, 100, self._edit_design)
        for title, control in (("Center X", self.gauge_x), ("Center Y", self.gauge_y), ("Radius", self.gauge_radius)):
            geometry.addRow(title, control)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Optional screen title")
        self.title_edit.setMaxLength(34)
        self.title_edit.textChanged.connect(self._edit_design)
        geometry.addRow("Title", self.title_edit)
        self.title_x = self._spin(0, 230, self._edit_design)
        self.title_y = self._spin(0, 230, self._edit_design)
        geometry.addRow("Title X", self.title_x)
        geometry.addRow("Title Y", self.title_y)
        layout.addLayout(geometry)
        timing = QFormLayout()
        self.animation_seconds = self._spin(2, 60, self._edit_settings)
        self.usage_seconds = self._spin(2, 60, self._edit_settings)
        self.animation_seconds.setSuffix(" sec")
        self.usage_seconds.setSuffix(" sec")
        timing.addRow("Animation", self.animation_seconds)
        timing.addRow("Usage", self.usage_seconds)
        layout.addWidget(label("SCREEN TIMING", "section"))
        layout.addLayout(timing)
        layout.addStretch()
        return widget

    def _animation_page(self):
        widget, layout = self._panel("Give your display a little personality. Import an image or animated GIF.")
        layout.addWidget(action("Import GIF or image", self.import_animation, True))
        layout.addWidget(label("Or drop a file anywhere in the studio.", "muted", True))
        self.animation_info = label("", "status", True)
        layout.addWidget(self.animation_info)
        row = QHBoxLayout()
        self.play_button = action("Pause preview", self.toggle_playback)
        row.addWidget(self.play_button)
        row.addWidget(action("Reset", self.reset_animation))
        layout.addLayout(row)
        layout.addWidget(label("SCALE & POSITION", "section"))
        form = QFormLayout()
        self.image_scale = self._spin(1, 6, self._edit_animation)
        self.image_x = self._spin(0, 208, self._edit_animation)
        self.image_y = self._spin(0, 208, self._edit_animation)
        self.frame_ms = self._spin(80, 2000, self._edit_animation)
        self.frame_ms.setSuffix(" ms")
        for title, control in (("Scale", self.image_scale), ("Position X", self.image_x),
                               ("Position Y", self.image_y), ("Frame time", self.frame_ms)):
            form.addRow(title, control)
        layout.addLayout(form)
        layout.addWidget(action("Fill display · crop edges", self.fill_animation))
        layout.addStretch()
        layout.addWidget(label("Up to 12 frames · 32 × 32 source pixels\nThe device plays uploaded frames locally.", "muted", True))
        return widget

    def _device_page(self):
        widget, layout = self._panel("Connections, Wi-Fi and battery. Your display stays connected while you work.")
        layout.addWidget(label("USB DISPLAY", "section"))
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)
        row = QHBoxLayout()
        row.addWidget(action("Refresh", self.refresh_ports))
        self.connect_button = action("Connect", self.toggle_usb)
        row.addWidget(self.connect_button)
        layout.addLayout(row)
        self.usb_detail = label(self.controller.last_status, "status", True)
        layout.addWidget(self.usb_detail)
        layout.addWidget(label("WI-FI", "section"))
        self.wifi_state = label(self.controller.last_wifi, "muted", True)
        layout.addWidget(self.wifi_state)
        self.ssid = QComboBox()
        self.ssid.setEditable(True)
        self.ssid.lineEdit().setPlaceholderText("Network name")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Wi-Fi password")
        network_label = label("Network")
        network_label.setBuddy(self.ssid)
        layout.addWidget(network_label)
        layout.addWidget(self.ssid)
        password_label = label("Password")
        password_label.setBuddy(self.password)
        layout.addWidget(password_label)
        layout.addWidget(self.password)
        self.ssid.setAccessibleName("Wi-Fi network")
        self.password.setAccessibleName("Wi-Fi password")
        layout.addWidget(action("Find nearby networks", self.scan_networks))
        self.scan_label = label("2.4 GHz networks supported", "muted", True)
        layout.addWidget(self.scan_label)
        layout.addWidget(action("Connect to Wi-Fi", self.connect_wifi))
        layout.addWidget(label("BLUETOOTH", "section"))
        self.bluetooth_detail = label(get_bluetooth_status(), "muted", True)
        layout.addWidget(self.bluetooth_detail)
        layout.addWidget(label("Live usage travels over BLE. Design and asset uploads use USB.", "muted", True))
        layout.addWidget(label("BATTERY", "section"))
        self.battery_check = Toggle("Enable GPIO1 battery sensor")
        self.battery_check.toggled.connect(self._edit_design)
        layout.addWidget(self.battery_check)
        layout.addWidget(label("Requires the original 2:1 voltage divider. The icon shows -- until a reading is available.", "muted", True))
        self.broadcast_label = label(get_wifi_status(), "muted", True)
        layout.addWidget(self.broadcast_label)
        layout.addStretch()
        layout.addWidget(action("Initialize display storage…", self.initialize_storage))
        return widget

    def navigate(self, page):
        self.page = page
        self.pages.setCurrentIndex(page)
        self.nav_buttons[page].setChecked(True)
        self.inspector_heading.setText(("Your workspace", "Screen design", "Animation library", "Your device")[page])
        self.heading.setText(("Display studio", "Screen design", "Animation library", "Device setup")[page])
        if page == 2:
            self.set_preview_kind("animation")
        elif page in (0, 1):
            self.set_preview_kind("usage")

    def set_preview_kind(self, kind):
        self.preview_kind = kind
        self.usage_tab.setChecked(kind == "usage")
        self.animation_tab.setChecked(kind == "animation")
        self._refresh_preview()

    def set_preview_metric(self, key):
        self.preview.metric = key
        self.preview.update()

    def _sync_controls(self):
        self.loading = True
        s, d = self.settings, self.design
        self.mode.setCurrentIndex(s.mode)
        self.style.setCurrentIndex(0 if d.usage_style == "gauge" else 1)
        for i, check in enumerate(self.widget_checks):
            check.setChecked(bool(s.widgets & (1 << i)))
        for control, value in ((self.gauge_x, d.gauge_x), (self.gauge_y, d.gauge_y),
                               (self.gauge_radius, d.gauge_radius), (self.image_x, d.image_x),
                               (self.image_y, d.image_y), (self.image_scale, d.image_scale),
                               (self.frame_ms, d.frame_ms), (self.animation_seconds, s.animation_seconds),
                               (self.usage_seconds, s.usage_seconds), (self.title_x, d.title_x), (self.title_y, d.title_y)):
            control.setValue(value)
        self.title_edit.setText(d.title)
        self.battery_check.setChecked(d.show_battery)
        self.loading = False
        self._animation_hint()
        self._color_buttons()

    def _edit_settings(self, *args):
        if self.loading:
            return
        mask = sum(1 << i for i, check in enumerate(self.widget_checks) if check.isChecked())
        self.settings = replace(self.settings, mode=self.mode.currentIndex(), widgets=mask,
                                animation_seconds=self.animation_seconds.value(), usage_seconds=self.usage_seconds.value())
        self._mark_dirty()

    def _edit_design(self, *args):
        if self.loading:
            return
        r = self.gauge_radius.value()
        x = max(r, min(239 - r, self.gauge_x.value()))
        y = max(r, min(239 - r, self.gauge_y.value()))
        self.design = replace(self.design, usage_style="gauge" if self.style.currentIndex() == 0 else "bars",
                              gauge_x=x, gauge_y=y, gauge_radius=r, title=self.title_edit.text(),
                              title_x=self.title_x.value(), title_y=self.title_y.value(),
                              show_battery=self.battery_check.isChecked())
        self.loading = True
        self.gauge_x.setValue(x); self.gauge_y.setValue(y)
        self.loading = False
        self._mark_dirty()

    def _edit_animation(self, *args):
        if self.loading:
            return
        scale = self.image_scale.value()
        maximum = 240 - 32 * scale
        self.design = replace(self.design, image_scale=scale, image_x=min(self.image_x.value(), maximum),
                              image_y=min(self.image_y.value(), maximum), frame_ms=self.frame_ms.value())
        self.loading = True
        self.image_x.setValue(self.design.image_x); self.image_y.setValue(self.design.image_y)
        self.loading = False
        self._mark_dirty()

    def _mark_dirty(self):
        self.dirty = True
        self.draft.setText("Editing draft · not yet applied")
        self.draft_timer.start(600)
        self._refresh_preview()

    def _save_draft(self):
        document = (self.settings, self.design)
        if document == self._last_saved_document:
            return
        try:
            self.settings.packet()
            build_scene(self.settings, self.design)
            write_json_file(DESIGN_FILE, {"version": 1, "settings": asdict(self.settings), "design": asdict(self.design)})
            self._last_saved_document = document
            self.draft.setText("Draft saved locally · not yet applied")
        except (ValueError, OSError) as exc:
            self.draft.setText(str(exc))

    def _refresh_preview(self):
        settings = replace(self.settings, mode=2 if self.preview_kind == "usage" else 1)
        signature = (settings, self.design, id(self.images), self.state)
        if signature == self._last_preview:
            return
        self._last_preview = signature
        self.preview.settings = settings
        self.preview.design = self.design
        self.preview.images = self.images
        self.preview.state = self.state
        self.preview.sync_playback()
        self.preview.update()
        self.canvas_caption.setText("240 × 240 · Live usage" if self.preview_kind == "usage" else "240 × 240 · Animation preview")
        self._animation_hint()

    def _animation_hint(self):
        count = len(self.design.frames)
        self.animation_info.setText(f"{count} frames · {self.design.frame_ms} ms per frame" if count > 1
                                    else "Still image · import an animated GIF for motion" if count == 1
                                    else "Default character · import a GIF to animate")

    def _color_buttons(self):
        for button, color, title in ((self.accent_button, self.settings.accent, "Accent"),
                                     (self.background_button, self.settings.background, "Canvas")):
            button.setText(f"●  {title}")
            button.setToolTip(f"#{color}")
            button.setStyleSheet(f"border-bottom:3px solid #{color};")

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor("#" + getattr(self.settings, key)), self)
        if color.isValid():
            self.settings = replace(self.settings, **{key: color.name()[1:].upper()})
            self._color_buttons()
            self._mark_dirty()

    def update_state(self, state):
        if self.closed or state == self._rendered_state:
            return
        self._rendered_state = state
        self.state = state
        self.project_label.setText(state.project or "No active project")
        self.chat_label.setText(state.chat or "Waiting for a Codex session")
        self.five_card.set_value(state.limit_5h_left, f"Resets {state.limit_5h_reset}" if state.limit_5h_reset else "5-hour window")
        self.week_card.set_value(state.limit_7d_left, f"Resets {state.limit_7d_reset}" if state.limit_7d_reset else "Weekly window")
        self.context_card.set_value(state.context_left, "Context remaining")
        used = f"{state.context_used:,}" if state.context_used is not None else "--"
        maximum = f"{state.context_max:,}" if state.context_max is not None else "--"
        self.session_detail.setText(f"{used} / {maximum} context tokens used.\nLive values are sent when the session changes.")
        self._refresh_preview()

    def refresh_ports(self):
        if self.port_combo.view().isVisible():
            return
        selected = self.port_combo.currentData()
        devices = tuple(list_ports())
        if devices == self._last_ports:
            return
        self._last_ports = devices
        self.port_combo.clear()
        for port, description in devices:
            self.port_combo.addItem(f"{port} · {description}", port)
        if not self.port_combo.count():
            self.port_combo.addItem("No USB display detected", None)
        index = self.port_combo.findData(self.controller.active_port or selected)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    def toggle_usb(self):
        if self.controller.connected:
            self.controller.disconnect()
        else:
            port = self.port_combo.currentData()
            if port:
                self.controller.connect_port(port)
            else:
                self.status.setText("Connect the ESP32 with a USB data cable, then refresh.")

    def _device_status(self, message):
        self.status.setText(message)
        self.usb_detail.setText(message)
        self.overview_device.setText(message)
        connected = self.controller.connected
        self.usb_chip.setText("USB · connected" if connected else "USB · searching")
        self._chip_state(self.usb_chip, connected)
        self.side_connection.setText("●  Display connected" if connected else "○  Finding display")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        if self.controller.active_port:
            index = self.port_combo.findData(self.controller.active_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        if message.startswith(("Sending settings", "Uploading screen")):
            self.busy = True
            self.progress.setRange(0, 0)
            self.progress.show()
            self.apply_button.setText("Applying…")
        elif not connected or message.startswith(("Screen design saved", "Settings saved", "Display rejected",
                "Display storage", "Scene upload", "No confirmation", "Upload the")):
            self.busy = False
            self.progress.hide()
            self.apply_button.setText("Apply to device")
        if message.startswith("Screen design saved"):
            self.dirty = False
            self.draft.setText("Design saved on display")
        self.apply_button.setEnabled(connected and not self.busy)

    def _device_settings(self, settings):
        if not self.dirty:
            self.settings = settings
            self._sync_controls()
            self._refresh_preview()

    def _upload_progress(self, percent):
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        if self.busy:
            self.apply_button.setText(f"Applying {percent}%")

    def _battery_status(self, value):
        if self.preview.battery_value == value:
            return
        self.battery_chip.setText(f"BAT · {value}%" if value is not None else "BAT · --")
        self.preview.battery_value = value
        self.preview.update()

    def _chip_state(self, chip, connected):
        if chip.property("online") != connected:
            chip.setProperty("online", connected)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    def _bluetooth_status(self, message):
        if self.closed:
            return
        self.bluetooth_detail.setText(message)
        if message == "Bluetooth: connected":
            text = "BLE · connected"
        elif "not found" in message:
            text = "BLE · not nearby"
        elif "disconnected" in message:
            text = "BLE · offline"
        else:
            text = "BLE · searching"
        self.ble_chip.setText(text)
        self._chip_state(self.ble_chip, message == "Bluetooth: connected")

    def apply_to_device(self):
        if not self.controller.connected:
            self.status.setText("Connect a display before applying your design.")
            return
        try:
            self.settings.packet()
            scene = build_scene(self.settings, self.design)
            write_json_file(DESIGN_FILE, {"version": 1, "settings": asdict(self.settings), "design": asdict(self.design)})
            self._last_saved_document = (self.settings, self.design)
            self.controller.device.send_settings(self.settings, scene, self.design.show_battery)
            self.busy = True
            self.apply_button.setEnabled(False)
            self.apply_button.setText("Applying…")
            self.status.setText("Sending your design…")
            self.draft.setText("Draft saved on this computer")
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _restore(self):
        saved = read_json_file(DESIGN_FILE)
        if not isinstance(saved, dict) or saved.get("version") != 1:
            return
        try:
            settings = DisplaySettings(**saved["settings"])
            values = dict(saved["design"])
            values["frames"] = tuple(values.get("frames", ()))
            design = SceneDesign(**values)
            settings.packet(); build_scene(settings, design)
            images = []
            for encoded in design.frames:
                image = QImage(32, 32, QImage.Format.Format_RGB32)
                for i in range(1024):
                    v = int(encoded[i * 4:i * 4 + 4], 16)
                    image.setPixelColor(i % 32, i // 32, QColor(((v >> 11) & 31) * 255 // 31,
                        ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
                images.append(image)
            self.settings, self.design, self.images = settings, design, images
            self._last_saved_document = (settings, design)
            self.dirty = True  # A saved desktop document takes precedence over device defaults.
        except (KeyError, TypeError, ValueError):
            pass

    def import_animation(self, path=None):
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(self, "Choose animation", "", "Images (*.gif *.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        images, frames = [], []
        delay = 200
        while len(images) < 12:
            image = reader.read()
            if image.isNull():
                break
            frame = QImage(32, 32, QImage.Format.Format_RGB32)
            frame.fill(QColor("#" + self.settings.background))
            small = image.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter = QPainter(frame)
            painter.drawImage((32 - small.width()) // 2, (32 - small.height()) // 2, small)
            painter.end()
            images.append(frame); frames.append(encode_rgb565(frame))
            if len(images) == 1 and 80 <= reader.nextImageDelay() <= 2000:
                delay = reader.nextImageDelay()
            if not reader.supportsAnimation():
                break
        if not images:
            self.status.setText("Could not read this animation.")
            return
        self.images = images
        self.design = replace(self.design, frames=tuple(frames), image_x=24, image_y=24, image_scale=6, frame_ms=delay)
        self.preview.frame = 0
        self.preview.playback_enabled = True
        self.play_button.setText("Pause preview")
        self._sync_controls()
        self.set_preview_kind("animation")
        self._mark_dirty()

    def fill_animation(self):
        if not self.images:
            self.status.setText("Import an image or animated GIF first.")
            return
        self.images = fill_square(self.images)
        self.design = replace(self.design, frames=tuple(encode_rgb565(im) for im in self.images),
                              image_x=24, image_y=24, image_scale=6)
        self._sync_controls(); self._mark_dirty()

    def reset_animation(self):
        self.images = []
        self.design = replace(self.design, frames=())
        self._sync_controls(); self._mark_dirty()

    def toggle_playback(self):
        self.preview.playback_enabled = not self.preview.playback_enabled
        self.preview.sync_playback()
        self.play_button.setText("Pause preview" if self.preview.playback_enabled else "Play preview")

    def scan_networks(self):
        if not self.controller.connected:
            self._start_computer_scan()
            return
        self._scan_generation += 1
        self._scan_pending = True
        generation = self._scan_generation
        self._networks.clear(); self.ssid.clear()
        self.scan_label.setText("Scanning nearby 2.4 GHz networks…")
        self.controller.device.scan_networks()
        QTimer.singleShot(10000, lambda: self._scan_timeout(generation))

    def _scan_timeout(self, generation):
        if not self.closed and self._scan_pending and generation == self._scan_generation:
            self._start_computer_scan()

    def _network_result(self, event):
        if self.closed or not event:
            return
        if event[0] == "item":
            _, name, strength, is_open = event
            if name not in self._networks:
                self._networks.add(name); self.ssid.addItem(name)
                self.ssid.setItemData(self.ssid.count() - 1, f"{strength} dBm · {'open' if is_open else 'secured'}", Qt.ItemDataRole.ToolTipRole)
        elif event[0] == "done" and self._networks:
            self._scan_pending = False
            self.scan_label.setText(f"{len(self._networks)} networks found")
        elif event[0] in ("failed", "unsupported") or (event[0] == "done" and not self._networks):
            self._start_computer_scan()

    def _start_computer_scan(self):
        self._scan_pending = False
        self._scan_generation += 1
        generation = self._scan_generation
        self._networks.clear(); self.ssid.clear()
        self.scan_label.setText("Checking this computer's network list…")
        def worker():
            networks = computer_networks()
            if not self.closed:
                try:
                    self.signals.computer_networks.emit((generation, networks))
                except RuntimeError:
                    pass
        threading.Thread(target=worker, name="studio-network-list", daemon=True).start()

    def _computer_network_results(self, result):
        generation, networks = result
        if self.closed or generation != self._scan_generation:
            return
        for name, strength, is_open in networks:
            if name not in self._networks:
                self._networks.add(name); self.ssid.addItem(name)
        self.scan_label.setText(f"{len(networks)} computer networks; display reception may differ."
                                if networks else "No networks found. You can type a network name.")

    def connect_wifi(self):
        if not self.controller.connected:
            self.status.setText("Connect the display by USB to save Wi-Fi credentials.")
            return
        try:
            self.controller.device.set_wifi(self.ssid.currentText(), self.password.text())
            self.password.clear()
            self.wifi_state.setText("Sending Wi-Fi settings…")
        except ValueError as exc:
            self.status.setText(str(exc))

    def initialize_storage(self):
        if not self.controller.connected:
            self.status.setText("Connect the display before initializing storage.")
            return
        if QMessageBox.warning(self, "Initialize display storage",
                "If the display storage cannot be mounted, this formats its SPIFFS partition and erases files stored there. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.controller.device.initialize_storage()

    def closeEvent(self, event):
        if self.closed:
            event.accept(); return
        self.closed = True
        self.draft_timer.stop()
        if self.dirty:
            self._save_draft()
        self.port_timer.stop()
        self.preview.timer.stop()
        unregister_state_callback(self._state_callback)
        unregister_bluetooth_status_callback(self._bluetooth_callback)
        unregister_wifi_status_callback(self._broadcast_callback)
        self.controller.close()
        super().closeEvent(event)

    def resizeEvent(self, event):
        if hasattr(self, "bezel"):
            size = min(378, max(220, self.height() - 490))
            self.bezel.setFixedSize(size, size)
            self.preview.setFixedSize(size - 38, size - 38)
        super().resizeEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "preview"):
            self.preview.window_active = not self.isMinimized()
            self.preview.sync_playback()
        super().changeEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp")):
                event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path:
                self.navigate(2)
                self.import_animation(path)
                event.acceptProposedAction()
