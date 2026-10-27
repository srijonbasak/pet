"""Low-overhead UDP broadcaster for the ESP32 display."""

import socket
import threading
import time

from .display_protocol import state_to_payload
from .monitor import get_latest_state, register_state_callback

PORT = 4210
KEEPALIVE_SECONDS = 20
_payload = None
_changed = threading.Event()
_started = False
_target = "255.255.255.255"
_status = "Wi-Fi: not started"
_callbacks = []


def register_wifi_status_callback(callback):
    _callbacks.append(callback)


def get_wifi_status():
    return _status


def _set_status(value):
    global _status
    if value == _status:
        return
    _status = value
    for callback in tuple(_callbacks):
        try:
            callback(value)
        except Exception:
            pass


def _on_state(state):
    global _payload
    value = state_to_payload(state)
    if value != _payload:
        _payload = value
        _changed.set()


def _worker():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        _changed.wait(KEEPALIVE_SECONDS)
        _changed.clear()
        if not _payload:
            continue
        try:
            sock.sendto(_payload, (_target, PORT))
            _set_status(f"Wi-Fi: broadcasting · UDP {PORT}")
        except OSError as exc:
            _set_status(f"Wi-Fi: {exc}")
            time.sleep(2)


def resend_latest():
    _changed.set()


def run_wifi_client(target="255.255.255.255"):
    global _started, _target
    if _started:
        return
    _started = True
    _target = target or "255.255.255.255"
    register_state_callback(_on_state)
    initial = get_latest_state()
    if initial:
        _on_state(initial)
    threading.Thread(target=_worker, name="codex-wifi", daemon=True).start()
