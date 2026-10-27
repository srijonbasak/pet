import asyncio
import threading
from bleak import BleakScanner, BleakClient

from .display_protocol import state_to_payload
from .monitor import register_state_callback, get_latest_state

# Standard generic access or a custom UUID. We'll use a placeholder UUID.
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
DEVICE_NAME = "CodexDisplay"

_latest_payload = None
_state_changed_event = None  # Will be initialized in the async loop
_ble_loop = None
_status = "Bluetooth: scanning"
_status_callbacks = []

def register_bluetooth_status_callback(callback):
    _status_callbacks.append(callback)

def get_bluetooth_status():
    return _status

def _set_status(value):
    global _status
    if value == _status:
        return
    _status = value
    for callback in tuple(_status_callbacks):
        try:
            callback(value)
        except Exception:
            pass

async def _write_payload(client, payload):
    # Twenty bytes works even before a larger BLE MTU has been negotiated.
    # Small chunks work before a larger BLE MTU has been negotiated.
    for offset in range(0, len(payload), 20):
        await client.write_gatt_char(
            CHAR_UUID, payload[offset:offset + 20], response=True
        )

async def _ble_client_task():
    global _latest_payload, _state_changed_event, _ble_loop
    
    # Initialize the event in the correct event loop
    _ble_loop = asyncio.get_running_loop()
    _state_changed_event = asyncio.Event()
    
    while True:
        try:
            _set_status("Bluetooth: scanning for CodexDisplay")
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            
            if not device:
                _set_status("Bluetooth: display not found")
                await asyncio.sleep(5)
                continue

            _set_status("Bluetooth: connecting")
            
            async with BleakClient(device) as client:
                _set_status("Bluetooth: connected")
                
                # Send the initial state if available
                if _latest_payload:
                    try:
                        await _write_payload(client, _latest_payload)
                    except Exception as e:
                        print(f"Failed to write initial state: {e}")
                
                while client.is_connected:
                    await _state_changed_event.wait()
                    _state_changed_event.clear()
                    
                    if _latest_payload:
                        try:
                            await _write_payload(client, _latest_payload)
                            print(f"BLE write success: {_latest_payload!r}")
                        except Exception as e:
                            print(f"BLE write error: {e}")
                            break # Break inner loop to reconnect

        except Exception as e:
            _set_status(f"Bluetooth: disconnected · {e}")
            await asyncio.sleep(5)

def _on_state_changed(state):
    global _latest_payload, _state_changed_event, _ble_loop
    new_payload = state_to_payload(state)
    
    if new_payload != _latest_payload:
        _latest_payload = new_payload
        
        if _state_changed_event and _ble_loop:
            _ble_loop.call_soon_threadsafe(_state_changed_event.set)

def run_bluetooth_client():
    register_state_callback(_on_state_changed)
    
    initial = get_latest_state()
    if initial:
        _on_state_changed(initial)
        
    def thread_func():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_ble_client_task())
        
    t = threading.Thread(target=thread_func, daemon=True)
    t.start()
