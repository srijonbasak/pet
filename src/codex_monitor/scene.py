"""Compile desktop display choices into portable, bounded drawing commands."""

from dataclasses import dataclass
from pathlib import Path

DESIGN_FILE = Path(__file__).resolve().parents[2] / "display_design.json"


@dataclass(frozen=True)
class SceneDesign:
    usage_style: str = "gauge"
    show_battery: bool = False
    gauge_x: int = 120
    gauge_y: int = 108
    gauge_radius: int = 88
    title: str = ""
    title_x: int = 12
    title_y: int = 12
    image_x: int = 24
    image_y: int = 24
    image_scale: int = 6
    frame_ms: int = 200
    frames: tuple = ()  # RGB565, 32 x 32, four hexadecimal digits per pixel


def build_scene(settings, design):
    if design.usage_style not in ("gauge", "bars"):
        raise ValueError("Unknown usage layout")
    if not (0 <= design.gauge_x <= 240 and 0 <= design.gauge_y <= 240 and
            30 <= design.gauge_radius <= 100 and
            design.gauge_radius <= design.gauge_x <= 239 - design.gauge_radius and
            design.gauge_radius <= design.gauge_y <= 239 - design.gauge_radius):
        raise ValueError("Keep the whole gauge inside the 240×240 screen")
    if not (0 <= design.title_x <= 230 and 0 <= design.title_y <= 230):
        raise ValueError("Title position must fit inside the screen")
    if not (1 <= design.image_scale <= 6 and 0 <= design.image_x <= 240 - 32 * design.image_scale
            and 0 <= design.image_y <= 240 - 32 * design.image_scale):
        raise ValueError("Keep the whole animation inside the 240×240 screen")
    if not 80 <= design.frame_ms <= 2000 or len(design.frames) > 12:
        raise ValueError("Animations support up to 12 frames, at 80–2000 ms per frame")
    safe_title = ''.join(c if 32 <= ord(c) < 127 and c != '|' else ' ' for c in design.title)[:34]
    lines = [f"S|A|{settings.background}", "S|U|FFFFFF"]
    if design.usage_style == "gauge":
        lines.append(f"G|U|{design.gauge_x}|{design.gauge_y}|{design.gauge_radius}|{settings.accent}")
    else:
        y = 60
        for bit, binding in ((2, 'five'), (4, 'week'), (1, 'context')):
            if settings.widgets & bit:
                lines.append(f"B|U|30|{y}|180|{settings.accent}|{binding}")
                y += 55
    if safe_title.strip():
        lines.append(f"T|U|{design.title_x}|{design.title_y}|1|34445A|{safe_title}")
    if design.frames:
        for i, pixels in enumerate(design.frames):
            if len(pixels) != 4096 or any(c not in '0123456789ABCDEF' for c in pixels):
                raise ValueError("Invalid animation frame")
            lines.append(f"I|A|{i}|{len(design.frames)}|{design.frame_ms}|{design.image_x}|"
                         f"{design.image_y}|{design.image_scale}|{pixels}")
    else:
        # The default character is desktop-owned drawing data, not firmware.
        for x, y, w, h, color in ((38, 35, 164, 120, '30415C'), (56, 54, 128, 80, '050912'),
                                  (80, 155, 80, 40, '30415C'), (86, 195, 24, 25, '30415C'),
                                  (130, 195, 24, 25, '30415C')):
            lines.append(f"R|A|{x}|{y}|{w}|{h}|{color}")
        lines.append(f"T|A|93|88|3|{settings.accent}|...")
    # The icon is always visible; show_battery controls the optional sensor.
    rgb = tuple(int(settings.background[i:i + 2], 16) for i in (0, 2, 4))
    icon_color = "FFFFFF" if (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) < 128000 else "34445A"
    lines.extend((f"D|A|182|10|{icon_color}", "D|U|182|10|34445A"))
    data = ('\n'.join(lines) + '\n').encode('ascii')
    if len(data) > 60000:
        raise ValueError("Scene is too large for the display")
    return data


def scene_hash(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value
