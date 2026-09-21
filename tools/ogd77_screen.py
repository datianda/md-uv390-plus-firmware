# -*- coding: utf-8 -*-
"""Read the radio's screen, and drive its keypad, over USB.

Screen reading works on ANY OpenGD77 build: the framebuffer is exposed as read
region 6 (CPS_ACCESS_DISPLAY_BUFFER), so no special firmware is needed. The
whole 160x128 panel comes back in about 1.4 s.

Key injection needs a firmware built with ENABLE_KEY_INJECTION:
    C 0x96 <keycode> <flags>   queue a keypad key
                               (bit0 long, bit1 hold, bit2 SK1, bit3 SK2)
    C 0xA7 <FUNC hi> <FUNC lo> queue a UI FUNCTION event

The function route exists because a key event is not always enough: the UI tests
keys in long else-if chains, so a key with several meanings (FRONT UP is
next-channel, power-up or start-scanning depending on modifiers) gets consumed
by whichever branch matches first. A function event addresses the handler.
"""
import struct
from ogd77 import Radio, DISPLAY_BUFFER

DISPLAY_W, DISPLAY_H = 160, 128
DISPLAY_BYTES = DISPLAY_W * DISPLAY_H * 2

KEY_INJECT, FUNC_INJECT = 0x96, 0xA7

# Flag bits in the 0x96 command's 4th byte, as usbKeyInjectTick() reads them.
# These are NOT the keyboard.h KEY_MOD_* values - an earlier version of this file
# used KEY_MOD_LONG (0x04) here, which the firmware sees as neither bit, so every
# "long press" went out as a short one. It failed quietly, too: long-# opened the
# DTMF entry screen (the short-press action) instead of the sweep.
KEY_INJECT_LONG = 0x01   # emit DOWN|PRESS, hold, then LONG|DOWN, then LONG|UP
KEY_INJECT_HOLD = 0x02   # with LONG: never send the release
KEY_INJECT_SK1  = 0x04   # hold SK1 down for the duration of this key
KEY_INJECT_SK2  = 0x08   # ditto SK2 - this is what "SK2 + Green" needs

# keyboard.h. The keypad digits are their ASCII codes.
KEYS = {
    "up": 1, "down": 2, "left": 3, "right": 4,
    "green": 13, "red": 27, "power": 26, "orange": 28,
    "star": ord("*"), "hash": ord("#"),
    "rotary-": 7, "rotary+": 8,
}
for _d in range(10):
    KEYS[str(_d)] = ord(str(_d))


def decode_native(raw):
    """Framebuffer words -> list of (r, g, b).

    Big-endian RGB565. Both halves of that are easy to get wrong and neither
    shows up on a black-and-white screen, because 0x0000 and 0xFFFF survive both
    a byte swap and a red/blue swap unchanged:

    * BYTE ORDER. displayConvertRGB888ToNative() ends in __builtin_bswap16(), so
      what sits in the buffer is the 565 word with its bytes already swapped for
      the panel. A host reading the bytes back has to swap them again - i.e. read
      big-endian - to get the 565 word.
    * CHANNEL ORDER. The panel type is detected at runtime
      (RGB888_TO_PLATFORM_COLOUR_FORMAT keys off displayLCD_Type); this radio
      reports RGB, not BGR.

    Established by decoding a screen full of waterfall four ways and checking
    each against the 64 colours the firmware's own ramp can emit: big-endian RGB
    put 3200 of 3200 pixels exactly on that palette, the other three managed
    1.6%, 1.6% and 10%. Guessing produces colours that look plausible - an
    earlier little-endian BGR guess rendered this same waterfall in convincing
    blues and greens - so if this ever needs revisiting, re-run that test rather
    than eyeballing a screenshot.
    """
    px = struct.unpack(">%dH" % (len(raw) // 2), raw)
    return [((((v >> 11) & 31) * 255) // 31,
             (((v >> 5) & 63) * 255) // 63,
             ((v & 31) * 255) // 31) for v in px]


# The three below take any Radio, not just a Screen, so the control panel can
# mirror the display through the connection it already has open rather than
# fighting it for the port - only one process can hold the serial device.
def grab(radio):
    """Raw framebuffer bytes."""
    return radio.read_region(DISPLAY_BUFFER, 0, DISPLAY_BYTES)


def to_image(radio, scale=3):
    from PIL import Image

    img = Image.new("RGB", (DISPLAY_W, DISPLAY_H))
    img.putdata(decode_native(grab(radio)))
    if scale != 1:
        img = img.resize((DISPLAY_W * scale, DISPLAY_H * scale), Image.NEAREST)
    return img


def png_bytes(radio, scale=3):
    import io as _io

    buf = _io.BytesIO()
    to_image(radio, scale).save(buf, "PNG")
    return buf.getvalue()


def _raw(radio, payload, read=8, wait=0.08):
    import time

    radio.ser.reset_input_buffer()
    radio.ser.write(payload)
    radio.ser.flush()
    time.sleep(wait)
    return radio.ser.read(read)


def inject_key(radio, name, long_press=False, hold=False, sk1=False, sk2=False):
    """Queue one key press.

    `hold` only means anything with `long_press`, and is for the handlers that
    enter a mode on long-down and tear it back down on the release - uiVFOMode's
    sweep being the one that matters. Send a separate key later to leave.

    `sk1` / `sk2` hold a side button down for the duration of the key. Keys and
    buttons are separate state in the firmware (ev->keys vs ev->buttons), so
    without these the whole "SK2 + Green" family of gestures is unreachable from
    here - which is every save-to-flash in the settings screens.
    """
    if name not in KEYS:
        raise ValueError("未知按键 %r，可用: %s" % (name, ", ".join(sorted(KEYS))))
    flags = ((KEY_INJECT_LONG if long_press else 0) | (KEY_INJECT_HOLD if hold else 0)
             | (KEY_INJECT_SK1 if sk1 else 0) | (KEY_INJECT_SK2 if sk2 else 0))
    return _raw(radio, b"C" + bytes([KEY_INJECT, KEYS[name], flags]))


def inject_func(radio, code):
    """Inject a FUNC_* UI event (menuSystem.h), e.g. 0x8001 = start scanning."""
    r = _raw(radio, b"C" + bytes([FUNC_INJECT, (code >> 8) & 0xFF, code & 0xFF]))
    # The firmware echoes [cmd, 0xA7, hi, lo]; a bare ACK means this build has no
    # ENABLE_KEY_INJECTION.
    return (len(r) >= 4 and r[1] == FUNC_INJECT), r


class Screen(Radio):
    def grab(self):
        return grab(self)

    def save_png(self, path, scale=3):
        to_image(self, scale).save(path)
        return path

    # -- key injection (ENABLE_KEY_INJECTION builds only) -------------------
    def key(self, name, long_press=False, hold=False, sk1=False, sk2=False):
        return inject_key(self, name, long_press, hold, sk1, sk2)

    def func(self, code):
        return inject_func(self, code)


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    with Screen() as s:
        if args and args[0] == "key":
            ok = s.key(args[1], ("long" in args[2:]))
            print("注入 %s%s -> %r" % (args[1], "（长按）" if "long" in args[2:] else "", ok))
        else:
            out = args[0] if args else "screen.png"
            print("已保存 %s" % s.save_png(out))
