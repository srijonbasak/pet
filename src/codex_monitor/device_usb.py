"""USB connection to the ESP32 display, including acknowledged settings."""

import threading
import time
from dataclasses import dataclass

from .display_protocol import state_to_payload
from .monitor import get_latest_state, register_state_callback, unregister_state_callback
from .scene import scene_hash


@dataclass(frozen=True)
class DisplaySettings:
    mode: int = 0
    animation: int = 0
    animation_seconds: int = 11
    usage_seconds: int = 7
    widgets: int = 7
    background: str = "FFFFFF"
    accent: str = "6EA0FF"

    def packet(self):
        if self.mode not in range(3) or self.animation not in range(3):
            raise ValueError("Invalid screen or animation mode")
        if not (2 <= self.animation_seconds <= 60 and 2 <= self.usage_seconds <= 60):
            raise ValueError("Screen times must be between 2 and 60 seconds")
        if not 1 <= self.widgets <= 7:
            raise ValueError("Choose at least one usage widget")
        for color in (self.background, self.accent):
            if len(color) != 6 or any(c not in "0123456789abcdefABCDEF" for c in color):
                raise ValueError("Colors must be six-digit RGB values")
        return (f"CFG|1|{self.mode}|{self.animation}|{self.animation_seconds}|"
                f"{self.usage_seconds}|{self.widgets}|{self.background.upper()}|"
                f"{self.accent.upper()}\n").encode("ascii")

    @classmethod
    def from_reply(cls, reply):
        fields = reply.split("|")
        if len(fields) != 8 or fields[0] != "SET":
            raise ValueError("Invalid settings response")
        obj = cls(*(int(value) for value in fields[1:6]), *fields[6:])
        obj.packet()
        return obj


def list_ports():
    try:
        from serial.tools import list_ports as serial_ports
        ports = [p for p in serial_ports.comports()
                 if not (p.device.startswith("/dev/ttyS") and p.vid is None)]
        ports.sort(key=lambda p: (p.vid not in (0x303A, 0x1A86, 0x10C4, 0x0403), p.device))
        return [(p.device, p.description if p.description and p.description.lower() != "n/a"
                 else "USB serial device") for p in ports]
    except ImportError:
        return []


def find_auto_port(preferred=None):
    """Only auto-open an Espressif USB device or a port the user selected."""
    try:
        from serial.tools import list_ports as serial_ports
        ports = list(serial_ports.comports())
        if preferred and any(p.device == preferred for p in ports):
            return preferred
        matches = [p.device for p in ports if p.vid == 0x303A]
        return matches[0] if len(matches) == 1 else None
    except ImportError:
        return None


class DeviceUSB:
    """Own the port in one background thread; UI never blocks on USB I/O."""

    def __init__(self, on_status, on_settings, on_battery=None, on_wifi=None, on_network=None, on_progress=None):
        self.on_status = on_status
        self.on_settings = on_settings
        self.on_battery = on_battery or (lambda value: None)
        self.on_wifi = on_wifi or (lambda value: None)
        self.on_network = on_network or (lambda value: None)
        self.on_progress = on_progress or (lambda value: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._pending = None
        self._pending_scene = None
        self._payload = None
        self._initialize_storage = False
        self._pending_wifi = None
        self._pending_battery = None
        self._scan_requested = False
        register_state_callback(self._on_state)
        initial = get_latest_state()
        if initial:
            self._on_state(initial)

    def _on_state(self, state):
        with self._lock:
            self._payload = state_to_payload(state)

    def connect(self, port):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(port,), daemon=True)
        self._thread.start()
        return True

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def disconnect(self):
        self._stop.set()

    def close(self):
        self.disconnect()
        unregister_state_callback(self._on_state)

    def send_settings(self, settings, scene=None, battery=None):
        packet = settings.packet()
        if scene is not None and (not isinstance(scene, bytes) or not 0 < len(scene) <= 60000):
            raise ValueError("Invalid scene size")
        with self._lock:
            self._pending = packet
            self._pending_scene = scene
            self._pending_battery = battery

    def set_wifi(self, ssid, password):
        ssid_bytes, password_bytes = ssid.encode("utf-8"), password.encode("utf-8")
        if not 1 <= len(ssid_bytes) <= 32 or b"\0" in ssid_bytes:
            raise ValueError("Wi-Fi name must be 1–32 UTF-8 bytes")
        if b"\0" in password_bytes or (password_bytes and not 8 <= len(password_bytes) <= 63):
            raise ValueError("Wi-Fi password must be empty or 8–63 UTF-8 bytes")
        packet = f"WIFI|SET|{ssid_bytes.hex().upper()}|{password_bytes.hex().upper()}\n".encode("ascii")
        with self._lock:
            self._pending_wifi = packet

    def initialize_storage(self):
        with self._lock:
            self._initialize_storage = True

    def scan_networks(self):
        with self._lock:
            self._scan_requested = True

    def _run(self, port):
        try:
            import serial
            self.on_status(f"Opening {port}…")
            with serial.Serial(port, 115200, timeout=0.1, write_timeout=2) as conn:
                self.on_status("Waiting for display firmware…")
                ready = False
                deadline = time.monotonic() + 18
                next_hello = 0
                last_payload = None
                last_sent = 0
                pending_sent = None
                sent_at = 0
                attempts = 0
                engine = 0
                scene = None
                scene_offset = 0
                scene_waiting = False
                scene_deadline = 0
                while not self._stop.is_set():
                    now = time.monotonic()
                    if not ready and now >= next_hello:
                        conn.write(b"HELLO|1\n")
                        next_hello = now + 1
                    if not ready and now > deadline:
                        self.on_status("No response. Upload the USB-enabled sketch and enable USB CDC on boot.")
                        break
                    if ready:
                        with self._lock:
                            payload = self._payload
                            wifi_packet, self._pending_wifi = self._pending_wifi, None
                            scan_requested, self._scan_requested = self._scan_requested, False
                            initialize = self._initialize_storage
                            self._initialize_storage = False
                            if self._pending is not None:
                                pending_sent, self._pending = self._pending, None
                                scene, self._pending_scene = self._pending_scene, None
                                battery, self._pending_battery = self._pending_battery, None
                                sent_at = 0
                                attempts = 0
                                scene_offset = 0
                                scene_waiting = False
                                if scene is not None and engine < 2:
                                    self.on_status("Upload the new display engine sketch first")
                                    pending_sent = None
                                    scene = None
                                elif battery is not None and engine < 3:
                                    self.on_status("Upload the updated battery and Wi-Fi firmware first")
                                    pending_sent = None
                                    scene = None
                                elif battery is not None:
                                    conn.write(b"BAT|1\n" if battery else b"BAT|0\n")
                        if wifi_packet:
                            if engine >= 3:
                                conn.write(wifi_packet)
                                self.on_status("Sending Wi-Fi settings to display…")
                            else:
                                self.on_status("Upload the updated battery and Wi-Fi firmware first")
                        if scan_requested:
                            if engine >= 4:
                                conn.write(b"WIFI|SCAN\n")
                            else:
                                self.on_network(("unsupported",))
                        if initialize:
                            if engine >= 2:
                                conn.write(b"SCN|INIT\n")
                                self.on_status("Initializing display storage…")
                            else:
                                self.on_status("Upload the new display engine sketch first")
                        if pending_sent and now - sent_at >= 2:
                            if attempts >= 4:
                                pending_sent = None
                                self.on_status("No confirmation received; settings may not be saved")
                            else:
                                conn.write(pending_sent)
                                sent_at = now
                                attempts += 1
                                self.on_status("Sending settings…")
                        if payload and (payload != last_payload or now - last_sent >= 20):
                            conn.write(payload)
                            last_payload, last_sent = payload, now
                        if scene_waiting and now >= scene_deadline:
                            conn.write(b"SCN|ABORT\n")
                            scene = None
                            scene_waiting = False
                            self.on_status("Scene upload timed out; previous scene remains saved")
                    reply = conn.readline().decode("ascii", "replace").strip()
                    if reply == "READY|1":
                        ready = True
                        self.on_status(f"Connected to {port}")
                    elif reply.startswith("ENGINE|"):
                        try:
                            engine = int(reply.split("|")[1])
                        except (ValueError, IndexError):
                            engine = 0
                    elif reply.startswith("WIFI|"):
                        parts = reply.split("|")
                        state = parts[1] if len(parts) > 1 else ""
                        if state == "CONNECTED" and len(parts) > 2:
                            self.on_wifi(f"Display Wi-Fi: connected · {parts[2]}")
                        elif state == "CONNECTING":
                            self.on_wifi("Display Wi-Fi: connecting…")
                        elif state == "FAILED":
                            self.on_wifi("Display Wi-Fi: failed. Check the name, password, and 2.4 GHz signal.")
                        elif state == "DISCONNECTED":
                            self.on_wifi("Display Wi-Fi: disconnected")
                    elif reply.startswith("BATTERY|"):
                        try:
                            value = int(reply.split("|")[1])
                            self.on_battery(value if 0 <= value <= 100 else None)
                        except (ValueError, IndexError):
                            pass
                    elif reply.startswith("SCAN|"):
                        parts = reply.split("|")
                        if len(parts) == 5 and parts[1] == "ITEM":
                            try:
                                name = bytes.fromhex(parts[2]).decode("utf-8", "replace")
                                self.on_network(("item", name, int(parts[3]), parts[4] == "1"))
                            except ValueError:
                                pass
                        elif len(parts) >= 2:
                            self.on_network((parts[1].lower(),))
                    elif reply == "ACK|SCN|INIT":
                        self.on_status("Display storage is ready. Send your design again.")
                    elif reply == "ACK|CFG|1":
                        pending_sent = None
                        if scene is None:
                            self.on_status("Settings saved on display")
                        else:
                            conn.write(f"SCN|BEGIN|{len(scene)}|{scene_hash(scene):08X}\n".encode("ascii"))
                            scene_waiting = True
                            scene_deadline = time.monotonic() + 8
                            self.on_status("Uploading screen design…")
                            self.on_progress(0)
                    elif reply.startswith("ACK|SCN|") and scene is not None:
                        part = reply.split("|")[-1]
                        if part == "DONE":
                            self.on_progress(100)
                            scene = None
                            scene_waiting = False
                            self.on_status("Screen design saved on display")
                        elif part.isdigit() and int(part) == scene_offset:
                            self.on_progress(int(scene_offset * 100 / len(scene)))
                            if scene_offset == len(scene):
                                conn.write(b"SCN|END\n")
                            else:
                                chunk = scene[scene_offset:scene_offset + 80]
                                conn.write(f"SCN|DATA|{scene_offset}|{chunk.hex().upper()}\n".encode("ascii"))
                                scene_offset += len(chunk)
                            scene_deadline = time.monotonic() + 8
                    elif reply.startswith("SET|"):
                        try:
                            self.on_settings(DisplaySettings.from_reply(reply))
                        except ValueError:
                            self.on_status("Display sent invalid settings")
                    elif reply.startswith("ERR|"):
                        pending_sent = None
                        scene = None
                        scene_waiting = False
                        if reply in ("ERR|scene-begin", "ERR|scene-storage"):
                            self.on_status("Display storage unavailable. Initialize storage, then send again.")
                        else:
                            self.on_status(f"Display rejected command: {reply[4:]}")
        except Exception as exc:
            if not self._stop.is_set():
                if isinstance(exc, PermissionError) or "Permission denied" in str(exc):
                    self.on_status("USB connection failed: permission denied. Add your user to dialout, then log out and back in.")
                elif "Input/output error" in str(exc):
                    self.on_status("USB connection failed: port unavailable. Refresh and select the ESP32 USB port; close Serial Monitor.")
                else:
                    self.on_status(f"USB connection failed: {exc}")
        finally:
            with self._lock:
                self._pending = None
                self._pending_scene = None
                self._pending_wifi = None
                self._pending_battery = None
                self._scan_requested = False
            if self._stop.is_set():
                self.on_status("USB disconnected")
