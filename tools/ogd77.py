# -*- coding: utf-8 -*-
"""OpenGD77 serial control for the TYT MD-UV390 (and relatives).

Protocol per qdmr's opengd77_interface (GPL). USB CDC, VID 1FC9 / PID 0094.
Baud rate is irrelevant on a CDC port.

  read request  : 'R' | cmd(1) | address(4, big-endian) | length(2, big-endian)
  read response : 'R' | length(2, BIG-endian) | payload

THIS MODULE IS READ-ONLY. It never writes to the radio.

Usage:
  python ogd77.py info                        firmware / model / flash serial
  python ogd77.py ping                        liveness check
  python ogd77.py dump flash 0x8f000 0x400 cal.bin
  python ogd77.py screen screen.bin
  python ogd77.py --port COM13 info
"""
import struct, sys, serial, serial.tools.list_ports

FLASH, EEPROM, MCU_ROM = 1, 2, 5
DISPLAY_BUFFER, WAV_BUFFER, AMBE_BUFFER = 6, 7, 8
FIRMWARE_INFO, FLASH_SECURITY = 9, 0x0A

BLOCK = 32
RADIO_TYPE = {0: "Radioddity GD-77", 1: "GD-77S", 2: "Baofeng DM-1801",
              3: "RD-5R", 4: "DM-1801A", 5: "TYT MD-9600",
              6: "TYT MD-UV380/UV390", 7: "TYT MD-380",
              8: "Baofeng DM-1701", 9: "TYT MD-2017", 10: "DM-1701 RGB"}


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x1FC9 and p.pid == 0x0094:
            return p.device
    return None


class Radio(object):
    def __init__(self, port=None, timeout=3.0):
        self.port = port or find_port()
        if not self.port:
            raise IOError("OpenGD77 radio not found (VID 1FC9 / PID 0094). "
                          "Is it plugged in, powered on, and is the CPS closed?")
        self.ser = serial.Serial(self.port, 115200, timeout=timeout)

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---- low level --------------------------------------------------------
    def _read(self, cmd, addr, length):
        self.ser.reset_input_buffer()
        self.ser.write(b"R" + bytes([cmd]) + struct.pack(">IH", addr, length))
        head = self.ser.read(3)
        if len(head) != 3 or head[0:1] != b"R":
            self._resync()
            raise IOError("bad response header at 0x%05X: %r" % (addr, head))
        # Verified on MD-UV390: the response length is BIG-endian, always.
        # (A little-endian guess with a ">4096 fall back to big-endian" rule
        #  silently breaks for length 16: 0x0010 BE reads as 4096 LE.)
        n = struct.unpack(">H", head[1:3])[0]
        if n != length:
            self._resync()
            raise IOError("region %d rejected 0x%05X (header says %d bytes, "
                          "asked %d)" % (cmd, addr, n, length))
        body = self.ser.read(n)
        if len(body) != n:
            self._resync()
            raise IOError("short read at 0x%05X: wanted %d got %d"
                          % (addr, n, len(body)))
        return body

    def _resync(self):
        """Drain whatever the device is still sending after a bad exchange."""
        old = self.ser.timeout
        try:
            self.ser.timeout = 0.25
            while self.ser.read(256):
                pass
        finally:
            self.ser.timeout = old

    def read_region(self, cmd, addr, length, progress=None):
        out = bytearray()
        while len(out) < length:
            out += self._read(cmd, addr + len(out), min(BLOCK, length - len(out)))
            if progress:
                progress(len(out), length)
        return bytes(out[:length])

    # ---- read-only operations --------------------------------------------
    def ping(self):
        """'C' 0xFE. Verified on MD-UV390: the ACK is a single byte, '-' (0x2D)."""
        self.ser.reset_input_buffer()
        self.ser.write(b"C" + bytes([0xFE]))
        r = self.ser.read(1)
        return r == b"-", r

    def firmware_info(self):
        raw = self._read(FIRMWARE_INFO, 0, 46)
        if len(raw) < 46:
            raise IOError("firmware info too short (%d bytes)" % len(raw))
        sv, rt = struct.unpack("<II", raw[0:8])
        rev = raw[8:24].split(b"\x00")[0].decode("ascii", "replace")
        date = raw[24:40].split(b"\x00")[0].decode("ascii", "replace")
        ser_no, feat = struct.unpack("<IH", raw[40:46])
        return {"struct_version": sv,
                "radio_type": rt,
                "radio_name": RADIO_TYPE.get(rt, "unknown (%d)" % rt),
                "firmware": rev,
                "build_date": date,
                "flash_serial": "0x%08X" % ser_no,
                "features": "0x%04X" % feat,
                "inverted_display": bool(feat & 0x01),
                "extended_callsign_db": bool(feat & 0x02),
                "voice_prompts_loaded": bool(feat & 0x04)}

    def dump(self, region, addr, length, path, label="read"):
        def prog(done, total):
            sys.stdout.write("\r  %s %d/%d bytes (%d%%)" %
                             (label, done, total, done * 100 // total))
            sys.stdout.flush()
        data = self.read_region(region, addr, length, prog)
        sys.stdout.write("\n")
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    def screengrab(self, path="screen.bin"):
        return self.dump(DISPLAY_BUFFER, 0, 1024, path, "screen")


if __name__ == "__main__":
    args = sys.argv[1:]
    port = None
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1]
        del args[i:i + 2]
    cmd = args[0] if args else "info"

    with Radio(port) as r:
        print("port: %s" % r.port)
        if cmd == "info":
            print("")
            for k, v in r.firmware_info().items():
                print("  %-22s %s" % (k, v))
        elif cmd == "ping":
            ok, raw = r.ping()
            print("  %s (raw %r)" % ("ACK" if ok else "unexpected reply", raw))
        elif cmd == "dump":
            region = {"flash": FLASH, "eeprom": EEPROM, "rom": MCU_ROM}[args[1]]
            r.dump(region, int(args[2], 0), int(args[3], 0), args[4], args[1])
            print("  wrote -> %s" % args[4])
        elif cmd == "screen":
            r.screengrab(args[1] if len(args) > 1 else "screen.bin")
        else:
            print(__doc__)
