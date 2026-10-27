# Codex display firmware

This build targets the ESP32-C3 + 240×240 ST7789 setup used by
`sketch_oct05a`. It shows only two screens:

1. A small animated terminal character sitting at a laptop. It breathes,
   blinks, types with alternating hands, pulses the laptop activity light, and
   gently moves its antenna and curled cable/tail.
2. Codex context, five-hour, and weekly usage in the Codex green palette.

Both Bluetooth LE and Wi-Fi carry the same small `CD2` text packet. BLE works
without Wi-Fi. For Wi-Fi, set `WIFI_SSID` and `WIFI_PASSWORD` near the top of
`codex_display_esp32/codex_display_esp32.ino`; the desktop app broadcasts UDP
updates on port 4210, so no device IP needs to be configured.

Upload the sketch with the same board and `ST7789_ESP32C3` library settings as
the original sample. Then run:

```bash
python3 run.py --gui
```

The GUI starts both BLE and Wi-Fi delivery. Headless alternatives are
`python3 run.py --watch --ble --wifi` or `python3 run.py --watch --wifi ESP32_IP`.
