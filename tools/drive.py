# -*- coding: utf-8 -*-
"""Drive the radio's UI over USB and capture what it shows.

Needs an ENABLE_KEY_INJECTION firmware. Takes a sequence of steps and writes a
screenshot after each one, which is what makes a UI change checkable without a
person watching the radio.

    python drive.py out-prefix green down down green ...
    python drive.py shot out.png            # just capture

Steps: a key name (see ogd77_screen.KEYS), optionally with `:`-suffixed
modifiers joined by `+`: `long`, `hold` (long press with no release, needed to
enter VFO sweep), `sk1`, `sk2`. So `green:sk2` is the save gesture and
`hash:hold` enters the sweep.
`wait:<seconds>`, or `shot` to capture without pressing anything. A screenshot
is written after every step unless --quiet.
"""
import sys, time
from ogd77_screen import Screen

SETTLE = 0.35   # the UI redraws from the main loop, so give it a frame or two


def run(steps, prefix, quiet=False, scale=3):
    shots = []
    with Screen() as s:
        for n, step in enumerate(steps):
            if step.startswith("wait:"):
                time.sleep(float(step.split(":", 1)[1]))
            elif step == "shot":
                pass
            else:
                name, _, mods = step.partition(":")
                m = mods.split("+") if mods else []
                s.key(name, long_press=(("long" in m) or ("hold" in m)),
                      hold=("hold" in m), sk1=("sk1" in m), sk2=("sk2" in m))
                time.sleep(SETTLE)

            if not quiet:
                path = "%s_%02d_%s.png" % (prefix, n, step.replace(":", "-"))
                s.save_png(path, scale)
                shots.append(path)
                print("  %-12s -> %s" % (step, path))
    return shots


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    if not args:
        sys.exit(__doc__)

    if args[0] == "shot":
        with Screen() as s:
            print(s.save_png(args[1] if len(args) > 1 else "screen.png"))
    else:
        run(args[1:], args[0], quiet)
