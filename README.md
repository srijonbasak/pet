# Codex Display Studio

A single desktop workspace for a Codex usage display: live usage, screen design,
animation import, USB connection, Wi-Fi setup, and battery monitoring.

## Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
python3 run.py --gui
```

`run.py` automatically uses the local `.venv`.

## Workspace

- **Overview:** actual context and account-limit values from local Codex data.
- **Design:** gauge or bars, screen mode, visible values, colors, placement and timing.
- **Animations:** import GIFs/images, preview playback, adjust size and position.
- **Device:** automatic USB connection, nearby Wi-Fi networks, credentials and battery settings.

The center canvas previews the selected screen with live usage. Changes are
saved as a local draft in `display_design.json`. **Apply to device** uploads the
scene over USB and shows acknowledged transfer progress. The connection remains
active while navigating between pages.

Images and GIFs can also be dropped directly into the studio. The interface
uses native painted controls and a static canvas grid; it does not run a web
browser or continuously animate the surrounding desktop UI.

The existing scene-engine firmware is in `sketch_oct05a/sketch_oct05a.ino`.
This desktop UI redesign does not require a firmware update if that engine is
already installed. See [firmware setup](firmware/README.md) for initial upload
and battery wiring requirements.

Bluetooth and Wi-Fi currently deliver live usage. USB handles design/asset
uploads, Wi-Fi provisioning, and battery telemetry. BLE configuration controls
are not yet implemented.

Animation import currently supports the first 12 frames at 32×32 source pixels,
scaled by the device up to 192×192. A one-frame image stays still. The preview is
a representation of the layout; hardware fonts and drawing edges can differ.
