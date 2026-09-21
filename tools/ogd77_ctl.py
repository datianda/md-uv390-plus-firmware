# -*- coding: utf-8 -*-
"""OpenGD77 command channel ('C' frames).

Frame is fixed 23 bytes, response is a single ACK byte ('-'):

  offset 0   'C'
  offset 1   command   0=show CPS screen 1=clear 2=display 3=render
                       5=close CPS screen 6=control option
  offset 2   x  /  control option
  offset 3   y  /  \
  offset 4   font     |  (union with uint32 LE timestamp at offset 3)
  offset 5   align    |
  offset 6   inverted /
  offset 7   message[16]

Control options (command 6):
  0 save settings (not VFOs)   1 reboot        2 save settings + VFOs
  3 flash green LED            4 flash red LED 5 re-init codec
  6 re-init sound              7 set date/time 10 delay 10ms

None of this touches Flash. The CPS screen is a temporary takeover of the
display; close_screen() (or a power cycle) restores normal operation.
"""
import struct, time
from ogd77 import Radio

SHOW, CLEAR, DISPLAY, RENDER, CLOSE, CONTROL = 0, 1, 2, 3, 5, 6
SET_AES_KEY, SET_AES_TX_KEY = 0x80, 0x81   # only present in an ENABLE_AES build
BAND_LOG_RUN, BAND_LOG_STATUS = 0x8C, 0x8D # only present in an ENABLE_BAND_LOG build
SAVE_SETTINGS, REBOOT, SAVE_ALL = 0, 1, 2
LED_GREEN, LED_RED = 3, 4
INIT_CODEC, INIT_SOUND, SET_DATETIME, DELAY_10MS = 5, 6, 7, 10
FONT = 3


class Control(Radio):
    def _cmd(self, command, x=0, y=0, font=0, align=0, inverted=0, msg=b""):
        frame = (b"C" + bytes([command, x, y, font, align, inverted])
                 + msg[:16].ljust(16, b"\x00"))
        assert len(frame) == 23, len(frame)
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        r = self.ser.read(1)
        if r != b"-":
            raise IOError("command %d not acknowledged (got %r)" % (command, r))
        return True

    # -- LED (harmless, visible) -------------------------------------------
    def led_green(self):  return self._cmd(CONTROL, x=LED_GREEN)
    def led_red(self):    return self._cmd(CONTROL, x=LED_RED)

    # -- temporary screen takeover -----------------------------------------
    def show_screen(self):  return self._cmd(SHOW)
    def clear_screen(self): return self._cmd(CLEAR)
    def render(self):       return self._cmd(RENDER)
    def close_screen(self): return self._cmd(CLOSE)

    def text(self, x, y, s, align=1, inverted=0):
        return self._cmd(DISPLAY, x=x, y=y, font=FONT, align=align,
                         inverted=inverted, msg=s.encode("ascii", "replace"))

    def message(self, lines, hold=0.0, align=1):
        """Draw up to 4 ASCII lines on the radio, then optionally hold."""
        self.show_screen()
        self.clear_screen()
        for i, line in enumerate(lines[:4]):
            self.text(0, i * 16, line, align=align)
        self.render()
        if hold:
            time.sleep(hold)

    # -- settings / reboot (NOT called by the demo) -------------------------
    def save_settings(self, with_vfos=True):
        return self._cmd(CONTROL, x=SAVE_ALL if with_vfos else SAVE_SETTINGS)

    def reboot(self):
        return self._cmd(CONTROL, x=REBOOT)

    def set_datetime(self, epoch_utc):
        frame = (b"C" + bytes([CONTROL, SET_DATETIME])
                 + struct.pack("<I", int(epoch_utc)) + b"\x00" * 16)
        assert len(frame) == 23, len(frame)
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        return self.ser.read(1) == b"-"

    # -- AES key management (ENABLE_AES firmware only) ----------------------
    # These two subcommands are added by the AES build's cpsHandleCommand and
    # are NOT the fixed 23-byte command frame: 0x80 carries a slot plus the raw
    # 32-byte key, 0x81 just a slot. A stock (non-AES) firmware does not know
    # them, which is what makes the reply worth showing to the caller.
    def _aes_raw(self, payload, read=64, wait=0.15):
        self.ser.reset_input_buffer()
        self.ser.write(payload)
        self.ser.flush()
        time.sleep(wait)
        return self._strip_nmea(self.ser.read(read))

    @staticmethod
    def _strip_nmea(buf):
        """Drop any NMEA the GPS is streaming onto the same port.

        In GPS modes NMEA and Log the firmware writes GPS sentences to this very
        CDC port (gps.c gates it on `>= GPS_MODE_ON_NMEA`), so a reply can arrive
        with sentences packed around it - the symptom is a reply like
        '2d 24 47 4e 54 58 54 2c' where 0x2D is the ACK and the rest is
        '$GNTXT,'. Reading a fixed byte count would otherwise mistake that data
        for the response, and at a different moment could swallow half a
        sentence and misparse the reply entirely.

        Sentences start with '$' and end at CR/LF, so they can be excised
        without knowing the command's own framing.
        """
        out = bytearray()
        i = 0
        while i < len(buf):
            if buf[i:i + 1] == b"$":
                j = i
                while (j < len(buf)) and (buf[j] not in (0x0D, 0x0A)):
                    j += 1
                while (j < len(buf)) and (buf[j] in (0x0D, 0x0A)):
                    j += 1
                i = j
                continue
            out.append(buf[i])
            i += 1
        return bytes(out)

    def set_aes_key(self, keyid, key):
        if not (0 <= keyid <= 15):
            raise ValueError("密钥槽必须是 0-15")
        if len(key) != 32:
            raise ValueError("AES-256 密钥必须是 32 字节（64 个十六进制字符）")
        self.show_screen()
        try:
            return self._aes_raw(b"C" + bytes([SET_AES_KEY, keyid]) + key)
        finally:
            self.close_screen()

    # -- band occupancy log (ENABLE_BAND_LOG firmware only) -----------------
    # bandLogResult_t in bandLog.h. Reported by the radio so the host states the
    # actual reason instead of guessing at the likeliest one.
    BAND_LOG_REASONS = {
        0: None,
        1: "GPS 设成了 Log 模式 —— NMEA 日志和频段日志共用同一块 flash，不能同时开。",
        2: "Flash 不是 16MB 的型号，没有日志区。",
        3: "擦除日志区的第一个扇区失败。",
    }

    def band_log_run(self, on):
        """Start or stop logging. Returns (ok, reason, raw).

        A single-byte reply is the generic CPS ACK, which means the firmware has
        no 0x8C command at all - i.e. it was not built with ENABLE_BAND_LOG.
        That is a different failure from the radio refusing, and saying so saves
        a hunt through settings that are not the problem."""
        r = self._aes_raw(b"C" + bytes([BAND_LOG_RUN, (1 if on else 0)]), read=8)

        if len(r) < 2:
            return False, ("电台不认识这条命令（只回了通用 ACK）。"
                           "当前固件没有编译 ENABLE_BAND_LOG。"), r

        code = r[1]
        if code == 0:
            return True, None, r
        return False, self.BAND_LOG_REASONS.get(code, "未知原因（代码 %d）" % code), r

    def band_log_status(self):
        r = self._aes_raw(b"C" + bytes([BAND_LOG_STATUS]), read=16)
        if len(r) < 10:
            raise IOError("状态响应过短 (%d 字节)：固件可能没开 ENABLE_BAND_LOG" % len(r))
        running = bool(r[1])
        used, cap = struct.unpack("<II", r[2:10])
        return {"running": running, "used": used, "capacity": cap,
                "percent": (round((used * 100.0) / cap, 2) if cap else 0)}

    def set_aes_tx_key(self, txkey):
        if not (0 <= txkey <= 15):
            raise ValueError("发射密钥槽必须是 0-15（0 = 关闭加密发射）")
        self.show_screen()
        try:
            return self._aes_raw(b"C" + bytes([SET_AES_TX_KEY, txkey]))
        finally:
            self.close_screen()
