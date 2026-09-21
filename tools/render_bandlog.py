# -*- coding: utf-8 -*-
"""Render a band log dump to a PNG.

The control panel draws this in the browser; this is the same data and the same
ramp for when you just want a file - or when, as here, the browser cannot be
driven from the session. Useful on its own for dropping a survey into notes.

    python render_bandlog.py <dump.bin> [out.png] [--dark]
"""
import sys, time
from PIL import Image, ImageDraw
import bandlog

# Sequential = one hue, light->dark. RSSI is a magnitude, so no rainbow: a
# rainbow ramp is perceptually non-uniform and invents structure that is not in
# the data. (The radio's own waterfall keeps its rainbow - different medium,
# glanced at rather than read.)
RAMP = ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7","#3987e5",
        "#2a78d6","#256abf","#1c5cab","#184f95","#104281","#0d366b"]


def scale(records):
    """Low/high ends of the colour ramp.

    NOT min/max. A sweep that was interrupted mid-pass leaves a row padded with
    zeros, and one such row drags the low end to 0 - which pushes the real noise
    floor into the middle of the ramp and makes everything above it, signals
    included, read as the same dark blue. Percentiles over the non-zero samples
    put the noise floor at the light end where it belongs, so the few bins that
    are actually busy are the ones that stand out.
    """
    vals = sorted(v for r in records for v in r["samples"] if v > 0)
    if not vals:
        return 0, 1
    # The low end is the MEDIAN, not a low percentile. Band noise swings over
    # most of the useful range, so anchoring at the bottom of it paints the
    # whole plot in speckle and a real carrier is just one more grain among
    # thousands. Clamping everything at or below the median to the lightest
    # step gives a calm floor for the busy bins to stand out from - the same
    # thing the radio's own noise-floor control does for the sweep trace.
    lo = vals[len(vals) // 2]
    hi = vals[min(len(vals) - 1, int(len(vals) * 0.995))]
    return lo, max(lo + 1, hi)


def render(records, path, dark=False):
    if not records:
        raise SystemExit("没有记录可画")

    rows, bins = len(records), records[0]["bins"]
    cw, ch = 5, max(6, min(22, 320 // rows))
    padL, padT, padR, padB = 62, 10, 12, 34
    W, H = padL + bins * cw + padR, padT + rows * ch + padB

    surface = "#1a1a19" if dark else "#fcfcfb"
    ink = "#8b97a5" if dark else "#6d7886"
    img = Image.new("RGB", (W, H), surface)
    d = ImageDraw.Draw(img)

    lo, hi = scale(records)
    span = max(1, hi - lo)

    def colour(v):
        i = round(((v - lo) / span) * (len(RAMP) - 1))
        i = max(0, min(len(RAMP) - 1, i))
        # On a dark ground the LIGHTEST step has to mean "strongest", or the
        # weak cells are the ones that stand out.
        return RAMP[(len(RAMP) - 1 - i) if dark else i]

    for y, rec in enumerate(records):          # newest at the top
        for x, v in enumerate(rec["samples"]):
            d.rectangle([padL + x*cw, padT + y*ch,
                         padL + (x+1)*cw - 1, padT + (y+1)*ch - 1], fill=colour(v))

    d.line([(padL, padT), (padL, padT + rows*ch), (padL + bins*cw, padT + rows*ch)],
           fill=ink, width=1)

    s = bandlog.summarise(records)
    d.text((padL, H - 24), "%.4f" % s["startMHz"], fill=ink)
    d.text((padL + bins*cw - 48, H - 24), "%.4f" % s["stopMHz"], fill=ink)
    d.text((padL + bins*cw//2 - 12, H - 24), "MHz", fill=ink)

    for y, rec in enumerate(records):
        if (y % max(1, rows // 8)) == 0 and rec["epoch"]:
            d.text((4, padT + y*ch), time.strftime("%H:%M:%S", time.gmtime(rec["epoch"])), fill=ink)

    # The lightest steps sit close to the surface by design, so the scale is
    # spelled out rather than left to the colour alone.
    lx, ly = padL, H - 12
    for i in range(len(RAMP)):
        d.rectangle([lx + i*12, ly, lx + (i+1)*12 - 1, ly + 8], fill=colour(lo + (i/(len(RAMP)-1))*span))
    d.text((lx + len(RAMP)*12 + 8, ly - 1), "RSSI %d - %d   (%d sweeps x %d bins)" % (lo, hi, rows, bins), fill=ink)

    img.save(path)
    return W, H


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dark = "--dark" in sys.argv
    if not args:
        sys.exit(__doc__)
    src = args[0]
    out = args[1] if len(args) > 1 else src.rsplit(".", 1)[0] + (".dark.png" if dark else ".png")
    recs = bandlog.parse(open(src, "rb").read())
    w, h = render(recs, out, dark)
    print("%s  (%dx%d, %d 条记录)" % (out, w, h, len(recs)))
