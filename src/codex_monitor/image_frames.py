"""Prepare small desktop-owned image frames for the display engine."""

from PyQt6.QtCore import Qt


def encode_rgb565(image):
    if image.width() != 32 or image.height() != 32:
        raise ValueError("Animation frames must be 32×32 pixels")
    pixels = []
    for y in range(32):
        for x in range(32):
            c = image.pixelColor(x, y)
            value = ((c.red() >> 3) << 11) | ((c.green() >> 2) << 5) | (c.blue() >> 3)
            pixels.append(f"{value:04X}")
    return "".join(pixels)


def fill_square(images):
    """Remove uniform edge bands and fill 32×32, cropping edges if needed."""
    if not images:
        return []
    first = images[0]
    if any(im.width() != 32 or im.height() != 32 for im in images):
        raise ValueError("Animation frames must be 32×32 pixels")
    corners = [first.pixelColor(x, y) for x, y in ((0, 0), (31, 0), (0, 31), (31, 31))]
    bg = corners[0]
    distance = lambda c: abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue())
    box = (0, 0, 32, 32)
    if all(distance(c) <= 48 for c in corners):
        xs, ys = [], []
        for image in images:
            for y in range(32):
                for x in range(32):
                    if distance(image.pixelColor(x, y)) > 60:
                        xs.append(x); ys.append(y)
        if xs:
            box = (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    result = []
    for image in images:
        cropped = image.copy(*box)
        scaled = cropped.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
        result.append(scaled.copy((scaled.width() - 32) // 2, (scaled.height() - 32) // 2, 32, 32))
    return result
