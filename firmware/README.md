# Codex display firmware

This build targets the ESP32-C3 + 240×240 ST7789 setup used by
`sketch_oct05a`. It shows only two screens:

1. An animated terminal character, with standing and laptop poses.
2. Codex context, five-hour, and weekly usage.

Both Bluetooth LE and Wi-Fi carry the same small `CD2` text packet. BLE works
without Wi-Fi. After connecting over USB, use **Set up Wi-Fi** in Display Studio
to scan for nearby 2.4 GHz networks and enter the password. If the display scan
fails, the app can show cached networks seen by the computer's NetworkManager;
the display may have a different reception range. The ESP32 saves the credentials
in its local preferences without encryption and reconnects after restarting.
The desktop broadcasts usage on UDP port 4210; the computer and display need
to be on the same network, and the network must permit broadcasts. Wi-Fi setup
itself uses USB; it is not wireless pairing.

Upload `../sketch_oct05a/sketch_oct05a.ino` with USB CDC On Boot enabled and a
large application partition such as Huge APP. Install the Python dependencies
and start the desktop app:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
python3 run.py --gui
```

The app automatically connects to a single Espressif USB device or a port you
previously selected, and reconnects after unplugging. For other USB adapters,
open **Display studio**, select the ESP32 port, and press **Connect** once.
The connection stays active when you close the studio and while the main app
remains open. Use **Edit layout & animation** to position the gauge and title,
or import a GIF or image. Choose colors, visible usage values, and screen
timings, then press **Send to display**. The app uploads a drawing scene and
the display confirms and saves it. Later scene changes do not require another
firmware upload. The design is also saved locally as `display_design.json`.

The animation importer supports the first 12 frames at 32×32 pixels and uses a
single adjustable frame time. Images are scaled up on the display. The current
editor exposes a movable usage gauge, an alternative bar layout, a title, and a
movable animation. A future editor can build more layouts using the engine's
drawing primitives. The default desktop character is static until a GIF is
imported. New imports are enlarged to 192×192 pixels; in **Edit layout &
animation**, **Fill display — crop image edges** can remove letterbox bands and
zoom an existing image, at the cost of cropping its outer edges.

The battery icon appears on newly sent scenes even when the sensor is disabled;
it shows `--` until a reading is available. Enable **Battery (GPIO1, 2:1 divider)** only if battery voltage is connected to
ADC GPIO1 through the 2:1 resistor divider assumed in the original sample. Do not
connect a single-cell battery directly to an ESP32 ADC pin; a charged cell can
exceed the input range. The displayed percentage is an approximate 3.3–4.2 V
voltage estimate, not a fuel-gauge measurement. Without verified battery wiring,
leave the option off; a floating ADC can produce misleading readings.

If the display reports storage unavailable, use **Initialize storage** and
confirm the warning. Formatting is only offered when the display cannot mount
its SPIFFS partition, and erases files on that partition. Close Arduino Serial
Monitor before connecting: only one program can use the USB port at a time.
Live Codex usage is sent over USB while the main app remains connected.

The GUI also starts BLE and Wi-Fi delivery. Headless alternatives are
`python3 run.py --watch --ble --wifi` or `python3 run.py --watch --wifi ESP32_IP`.
