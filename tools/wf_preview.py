# -*- coding: utf-8 -*-
"""Render the radio's live waterfall through both colour ramps, side by side.

The point is to compare a palette change WITHOUT reflashing. The waterfall the
radio is showing right now was drawn from a 64-entry table, so every pixel in
that band can be mapped back to the level that produced it; those levels are the
real measured band data, and re-rendering them through a different ramp shows
exactly what the new firmware would have drawn from the same sweep.

    python wf_preview.py [out.png]

Requires the radio to be in VFO sweep mode (long-press # with no release).
"""
import sys
from PIL import Image, ImageDraw
from ogd77_screen import Screen, to_image

WF_Y0, WF_H, W = 50, 28, 160        # VFO_WF_START_Y / VFO_WF_HEIGHT_Y
LEVELS = 64                          # VFO_WF_LEVELS


def rainbow(level):
    """The old palette: uiVFOMode.c's jet ramp."""
    v = (level * 255) // (LEVELS - 1)
    if   v <  42: c = (0, 0, v * 3)
    elif v <  85: c = (0, (v - 42) * 6, 127 + (v - 42) * 3)
    elif v < 128: c = (0, 255, 255 - (v - 85) * 6)
    elif v < 170: c = ((v - 128) * 6, 255, 0)
    elif v < 213: c = (255, 255 - (v - 170) * 6, 0)
    else:         c = (255, (v - 213) * 6, (v - 213) * 6)
    return tuple(min(x, 255) for x in c)


def sequential(level):
    """The new palette: one hue, black -> blue -> white."""
    v = (level * 255) // (LEVELS - 1)
    if v < 85:
        return (0, 0, v * 3)
    g = ((v - 85) * 3) // 2
    return (min(g, 255), min(g, 255), 255)


def gamma(level):
    """The square law the new firmware applies before the ramp."""
    return (level * level) // (LEVELS - 1)


def quantise(c):
    """888 -> 565 -> 888, so the lookup matches what the panel actually stores."""
    r, g, b = c
    return (((r >> 3) * 255) // 31, ((g >> 2) * 255) // 63, ((b >> 3) * 255) // 31)


def read_levels(img):
    """Map each waterfall pixel back to the level that drew it."""
    lookup = {}
    for l in range(LEVELS):
        lookup.setdefault(quantise(rainbow(l)), l)

    px = img.load()
    rows, misses = [], 0
    for y in range(WF_Y0, WF_Y0 + WF_H):
        row = []
        for x in range(W):
            l = lookup.get(px[x, y])
            if l is None:
                misses += 1
                l = 0
            row.append(l)
        rows.append(row)
    return rows, misses


def render(rows, out, scale=3):
    gap, label = 10, 16
    h = WF_H * scale
    img = Image.new("RGB", (W * scale, label + h + gap + label + h), "#12100e")
    d = ImageDraw.Draw(img)

    for i, (title, fn, pre) in enumerate((("BEFORE  rainbow, linear", rainbow, lambda l: l),
                                          ("AFTER   one hue, squared", sequential, gamma))):
        top = label + i * (h + gap + label)
        d.text((2, top - 11), title, fill="#8b8681")
        for y, row in enumerate(rows):
            for x, l in enumerate(row):
                d.rectangle([x * scale, top + y * scale,
                             (x + 1) * scale - 1, top + (y + 1) * scale - 1],
                            fill=fn(pre(l)))
    img.save(out)
    return img.size


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "../backup/waterfall-before-after.png"
    with Screen() as s:
        img = to_image(s, 1)
    rows, misses = read_levels(img)
    flat = sorted(l for r in rows for l in r)
    n = len(flat)
    size = render(rows, out)
    print("%s  %dx%d" % (out, size[0], size[1]))
    print("  %d 个像素，%d 个不在调色板上（电台没在扫频？）" % (n, misses))
    print("  level 中位 %d，95%% %d，最大 %d  ->  加平方律后 %d / %d / %d"
          % (flat[n // 2], flat[int(n * .95)], flat[-1],
             gamma(flat[n // 2]), gamma(flat[int(n * .95)]), gamma(flat[-1])))
