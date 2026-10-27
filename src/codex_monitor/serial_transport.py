import threading
import time
from queue import Empty, Queue

from .display_protocol import state_to_payload
from .monitor import get_latest_state, register_state_callback


BAUD_RATE = 115200
RESEND_SECONDS = 30

_latest_payload = None
_changed = threading.Event()
_force_reconnect = threading.Event()
_force_send = threading.Event()
_outbox = Queue()
_started = False
_status = "Arduino: not started"
_status_callbacks = []
_requested_port = "auto"


def register_serial_status_callback(callback):
    _status_callbacks.append(callback)


def get_serial_status():
    return _status


def list_serial_devices():
    """Return serial devices in a GUI-friendly form."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [
        {
            "device": port.device,
            "description": port.description or "Serial device",
            "vid": port.vid,
            "pid": port.pid,
        }
        for port in list_ports.comports()
    ]


def select_serial_port(port):
    """Select a path/COM port, or 'auto', and reconnect immediately."""
    global _requested_port
    _requested_port = port or "auto"
    _force_reconnect.set()
    _changed.set()
    _set_status(f"Arduino: switching to {_requested_port}...")


def resend_latest():
    _force_send.set()
    _changed.set()


def send_display_test():
    """Queue a recognizable LCD test page without replacing live state."""
    packet = (
        "CD2|USB LINK WORKS|LCD test from app|100|12345|258400|"
        "88|10:59 PM|77|Sep 27\n"
    ).encode("ascii")
    _outbox.put(packet)
    _changed.set()


def _set_status(message):
    global _status
    if message == _status:
        return
    _status = message
    print(message)
    for callback in tuple(_status_callbacks):
        try:
            callback(message)
        except Exception:
            pass


def _on_state_changed(state):
    global _latest_payload
    payload = state_to_payload(state)
    if payload != _latest_payload:
        _latest_payload = payload
        _changed.set()


def _find_arduino_port(list_ports):
    ports = list(list_ports.comports())
    if not ports:
        return None

    arduino_vids = {0x2341, 0x2A03}
    clone_vids = {0x1A86, 0x0403, 0x10C4}

    for port in ports:
        text = f"{port.description} {port.manufacturer}".lower()
        if port.vid in arduino_vids or "arduino" in text:
            return port.device
    for port in ports:
        if port.vid in clone_vids:
            return port.device
    return ports[0].device if len(ports) == 1 else None


def _serial_worker():
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        _set_status("Arduino: pyserial is not installed")
        return

    while True:
        requested_port = _requested_port
        port = (
            _find_arduino_port(list_ports)
            if requested_port in (None, "auto")
            else requested_port
        )
        if not port:
            _set_status("Arduino: no USB serial device found")
            _changed.wait(2)
            _changed.clear()
            continue

        try:
            _set_status(f"Arduino: opening {port}...")
            with serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=0.1,
                write_timeout=2,
            ) as connection:
                # An Uno resets when its USB serial port opens.
                time.sleep(2)
                connection.reset_input_buffer()
                _set_status(f"Arduino: connected on {port}; checking firmware...")
                last_payload = None
                last_write = 0.0
                first_write_at = None
                acknowledged = False
                firmware_warning_sent = False
                _force_reconnect.clear()

                while connection.is_open:
                    if _force_reconnect.is_set() or _requested_port != requested_port:
                        break

                    try:
                        while True:
                            connection.write(_outbox.get_nowait())
                            connection.flush()
                            if first_write_at is None:
                                first_write_at = time.monotonic()
                    except Empty:
                        pass

                    payload = _latest_payload
                    now = time.monotonic()
                    if payload and (
                        payload != last_payload
                        or now - last_write >= RESEND_SECONDS
                        or _force_send.is_set()
                    ):
                        connection.write(payload)
                        connection.flush()
                        last_payload = payload
                        last_write = now
                        if first_write_at is None:
                            first_write_at = now
                        _force_send.clear()

                    if connection.in_waiting:
                        reply = connection.readline().decode("ascii", "replace").strip()
                        if reply == "ACK|CD2" and not acknowledged:
                            acknowledged = True
                            _set_status(f"Arduino: display online on {port}")

                    if (
                        not acknowledged
                        and not firmware_warning_sent
                        and first_write_at is not None
                        and time.monotonic() - first_write_at >= 3
                    ):
                        firmware_warning_sent = True
                        _set_status(
                            "Arduino: port is open, but display firmware did not reply; "
                            "upload the supplied Uno sketch"
                        )

                    _changed.wait(0.25)
                    _changed.clear()
        except Exception as exc:
            _set_status(f"Arduino: disconnected ({exc})")
            time.sleep(2)


def run_serial_client(port="auto"):
    """Start automatic USB serial delivery to an Arduino Uno."""
    global _started, _requested_port
    if _started:
        return
    _started = True
    _requested_port = port or "auto"

    register_state_callback(_on_state_changed)
    initial = get_latest_state()
    if initial:
        _on_state_changed(initial)

    thread = threading.Thread(
        target=_serial_worker,
        name="arduino-serial",
        daemon=True,
    )
    thread.start()
