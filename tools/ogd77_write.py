# -*- coding: utf-8 -*-
"""OpenGD77 write channel.

EEPROM bank  ('X' | 04 | addr BE4 | len BE2 | data)  -> direct write, byte
granular, NO sector erase.  Channels 1-128, zones and settings live here.

FLASH bank needs select-sector / fill-buffer / commit-4KB and is NOT
implemented here on purpose - a partial buffer erases the rest of the sector.

Verified channel record layout (0x38 bytes each):
    +0x00  name[16]      0xFF padded
    +0x10  rx freq       4 byte BCD little-endian, units of 10 Hz
    +0x14  tx freq       4 byte BCD little-endian
    +0x20  rx CTCSS      2 byte BCD little-endian, FFFF = none
    +0x22  tx CTCSS      2 byte BCD little-endian, FFFF = none

Channel bank 0: 0x10 byte bitmap at 0x3780, records from 0x3790.
"""
import struct
from ogd77 import Radio, EEPROM, FLASH
from ogd77_ctl import Control

WRITE_EEPROM = 4
BANK0_BITMAP = 0x3780
BANK0_BASE = 0x3790
CH_SIZE = 0x38
NAME_LEN = 16


def channel_addr(index):
    """Byte address of channel record `index` (0-based) in the EEPROM bank."""
    if not 0 <= index < 128:
        raise ValueError("channel bank 0 holds indices 0-127")
    return BANK0_BASE + index * CH_SIZE


def decode_name(blk):
    return blk[:NAME_LEN].split(b"\xff")[0].split(b"\x00")[0].decode("ascii", "replace")


def decode_bcd_freq(b):
    """4 byte BCD little-endian, units of 10 Hz -> MHz float."""
    digits = ""
    for byte in reversed(b):
        digits += "%02X" % byte
    return int(digits) / 100000.0


class Writer(Control):
    """Writes require programming mode. Always use `with w.prog_mode():`.

    qdmr's write_start sequence, verified necessary on the MD-UV390: without
    SHOW_CPS_SCREEN the radio ACKs the write but keeps serving its cached
    copy, so the change silently does not stick.
    """

    def prog_mode(self, label=("Claude", "writing", "codeplug")):
        writer = self

        class _Ctx(object):
            def __enter__(self):
                writer.show_screen()
                writer.clear_screen()
                for i, line in enumerate(label[:4]):
                    writer.text(0, i * 16, line)
                writer.render()
                writer.led_red()
                writer.save_settings(with_vfos=True)
                return writer

            def __exit__(self, *a):
                writer.close_screen()
                return False
        return _Ctx()

    def write_eeprom(self, addr, data):
        if len(data) > 32:
            raise ValueError("max 32 bytes per write request")
        frame = b"X" + bytes([WRITE_EEPROM]) + struct.pack(">IH", addr, len(data)) + data
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        resp = self.ser.read(2)
        if resp[:1] != b"X" or resp[1:2] != bytes([WRITE_EEPROM]):
            raise IOError("write at 0x%05X not acknowledged (got %r)" % (addr, resp))
        return True

    def read_channel(self, index):
        return self.read_region(EEPROM, channel_addr(index), CH_SIZE)

    def set_channel_name(self, index, name):
        """Overwrite only the 16 byte name field. Nothing else is touched."""
        raw = name.encode("ascii")
        if len(raw) > NAME_LEN:
            raise ValueError("channel name max %d ASCII chars" % NAME_LEN)
        self.write_eeprom(channel_addr(index), raw.ljust(NAME_LEN, b"\xff"))
        return True


# ---------------------------------------------------------------------------
# Flash sector write.
#
# On the MD-UV390 there is NO EEPROM chip: reading bank 2 (EEPROM) and bank 1
# (FLASH) at the same offset returns identical bytes, and WRITE_EEPROM is a
# no-op that still ACKs. Codeplug edits must go through the flash sector path:
#
#   'X' | 01 | sector[3]                       select 4KB sector (addr // 4096)
#   'X' | 02 | addr BE4 | len BE2 | data       fill sector buffer, <=32 B/req
#   'X' | 03                                   erase + program the whole sector
#
# Step 3 rewrites all 4096 bytes, so the buffer must be filled with the FULL
# current sector content, not just the bytes being changed.
# ---------------------------------------------------------------------------
SECTOR_SIZE = 0x1000
SET_FLASH_SECTOR, WRITE_SECTOR_BUFFER, WRITE_FLASH_SECTOR = 1, 2, 3


class FlashWriter(Writer):
    def _wr(self, frame, cmd):
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        resp = self.ser.read(2)
        if resp[:1] != b"X" or resp[1:2] != bytes([cmd]):
            raise IOError("cmd %d not acknowledged (got %r)" % (cmd, resp))
        return True

    def set_sector(self, addr):
        sec = addr // SECTOR_SIZE
        return self._wr(b"X" + bytes([SET_FLASH_SECTOR,
                                      (sec >> 16) & 0xFF, (sec >> 8) & 0xFF, sec & 0xFF]),
                        SET_FLASH_SECTOR)

    def fill_buffer(self, addr, data):
        return self._wr(b"X" + bytes([WRITE_SECTOR_BUFFER])
                        + struct.pack(">IH", addr, len(data)) + data,
                        WRITE_SECTOR_BUFFER)

    def commit_sector(self):
        return self._wr(b"X" + bytes([WRITE_FLASH_SECTOR]), WRITE_FLASH_SECTOR)

    def read_sector(self, addr, progress=None):
        base = (addr // SECTOR_SIZE) * SECTOR_SIZE
        return base, self.read_region(FLASH, base, SECTOR_SIZE, progress)

    def write_sector(self, base, data, progress=None):
        if len(data) != SECTOR_SIZE:
            raise ValueError("need exactly %d bytes" % SECTOR_SIZE)
        self.set_sector(base)
        for off in range(0, SECTOR_SIZE, 32):
            self.fill_buffer(base + off, data[off:off + 32])
            if progress:
                progress(off + 32, SECTOR_SIZE)
        self.commit_sector()
        return True


# ---------------------------------------------------------------------------
# Field encoders (inverse of decode_bcd_freq).
# ---------------------------------------------------------------------------
def encode_bcd_freq(mhz):
    """MHz float -> 4 byte BCD little-endian, units of 10 Hz."""
    digits = "%08d" % int(round(float(mhz) * 100000))
    if len(digits) != 8:
        raise ValueError("frequency out of range: %r" % mhz)
    return bytes(int(digits[i:i + 2], 16) for i in (6, 4, 2, 0))


def decode_bcd_tone(b):
    """2 byte BCD little-endian tone -> Hz float, or None."""
    if b == b"\xff\xff" or b == b"\x00\x00":
        return None
    return int("%02X%02X" % (b[1], b[0])) / 10.0


def encode_bcd_tone(hz):
    """Hz float (or None) -> 2 byte BCD little-endian."""
    if hz in (None, "", "None"):
        return b"\xff\xff"
    digits = "%04d" % int(round(float(hz) * 10))
    return bytes(int(digits[i:i + 2], 16) for i in (2, 0))


CH_FIELDS = {          # name -> (offset, size, encoder, decoder)
    "name":   (0x00, 16, lambda v: v.encode("ascii").ljust(16, b"\xff"), decode_name),
    "rx":     (0x10, 4,  encode_bcd_freq, decode_bcd_freq),
    "tx":     (0x14, 4,  encode_bcd_freq, decode_bcd_freq),
    "rxtone": (0x20, 2,  encode_bcd_tone, decode_bcd_tone),
    "txtone": (0x22, 2,  encode_bcd_tone, decode_bcd_tone),
}


def parse_channel(blk):
    out = {}
    for k, (off, size, _, dec) in CH_FIELDS.items():
        out[k] = dec(blk[off:off + size])
    return out


class ChannelEditor(FlashWriter):
    def list_channels(self):
        """Return every enabled channel in bank 0, using the 0x10 byte bitmap."""
        bitmap = self.read_region(FLASH, BANK0_BITMAP, 0x10)
        out = []
        for idx in range(128):
            if not (bitmap[idx // 8] >> (idx % 8)) & 1:
                continue
            ch = parse_channel(self.read_channel(idx))
            ch["index"] = idx
            ch["number"] = idx + 1
            out.append(ch)
        return out

    def update_channel(self, index, backup_dir=None, **fields):
        """Read-modify-write one channel's fields via its 4KB sector.

        Returns (before, after). Raises if the read-back does not match, or if
        any byte outside the edited fields changed.
        """
        unknown = set(fields) - set(CH_FIELDS)
        if unknown:
            raise ValueError("unknown field(s): %s" % ", ".join(sorted(unknown)))
        addr = channel_addr(index)
        base, sector = self.read_sector(addr)
        if backup_dir:
            import os, time
            os.makedirs(backup_dir, exist_ok=True)
            # A full read-modify-write-verify cycle takes about a second, so a
            # seconds-resolution stamp lets two edits collide and the second
            # backup overwrite the first. Add milliseconds and the channel.
            t = time.time()
            stamp = "%s.%03d" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(t)),
                                 int((t % 1) * 1000))
            fn = "sector_%02X_ch%03d_%s.bin" % (base // SECTOR_SIZE, index + 1, stamp)
            open(os.path.join(backup_dir, fn), "wb").write(sector)
        off = addr - base
        before = parse_channel(sector[off:off + CH_SIZE])

        new = bytearray(sector)
        touched = []
        for k, v in fields.items():
            fo, size, enc, _ = CH_FIELDS[k]
            new[off + fo:off + fo + size] = enc(v)
            touched.append((off + fo, off + fo + size))

        with self.prog_mode(("Claude", "writing", "channel %d" % (index + 1))):
            self.write_sector(base, bytes(new))

        _, back = self.read_sector(addr)
        if back != bytes(new):
            raise IOError("verification failed: sector read-back differs")
        for i in range(SECTOR_SIZE):          # nothing outside the fields moved
            if back[i] != sector[i] and not any(a <= i < b for a, b in touched):
                raise IOError("collateral change at sector offset +0x%03X" % i)
        return before, parse_channel(back[off:off + CH_SIZE])
