# -*- coding: utf-8 -*-
"""Read and refresh the radio's satellite TLEs over USB.

    python sat.py list                  # what is loaded, and how stale it is
    python sat.py dump keps.txt         # write them out as standard 2-line TLEs
    python sat.py refresh [--yes]       # re-fetch the same satellites' elements
    python sat.py addfm  [--yes]        # fill empty slots with FM repeater satellites

A TLE is a snapshot of an orbit, not a description of it: the model drifts away
from reality at roughly a minute of pass time per week of age, so a prediction
made from a month-old element set can put a low pass on the wrong side of the
sky. The radio has no idea how old its own elements are and never says - this
does the arithmetic.

Storage, for reference (firmware side: codeplug.c, satellite.c):

  SPI flash + 128 KiB starts "OpenGD77" + 12 bytes, then a chain of blocks, each
  {int32 dataType; int32 dataLength;} followed by its data. Satellite TLEs are
  dataType 3: 25 fixed-size records of 100 bytes.

  Inside a record the two TLE lines are NIBBLE-PACKED - each byte holds two
  indices into "0123456789. +-*" - so line 1 is 12 bytes for 24 characters and
  line 2 is 28 bytes for 56. What is stored is not the original TLE text but the
  fields the propagator wants, already stripped of checksums and column padding.
"""
import os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ogd77 import Radio, FLASH

CUSTOM_BASE = 128 * 1024          # FLASH_ADDRESS_OFFSET
TYPE_SATELLITE_TLE = 3
NUM_SATELLITES = 25
REC_SIZE = 100                    # sizeof(codeplugSatelliteData_t)
NIBBLES = "0123456789. +-*"


def unpack_tle(raw):
    """Nibble-packed bytes -> the digit string the propagator parses."""
    out = []
    for b in raw:
        out.append(NIBBLES[b >> 4])
        out.append(NIBBLES[b & 0x0F])
    return "".join(out)


def pack_tle(text, nbytes):
    """The inverse. Pads with spaces, which decompress back to spaces."""
    text = text.ljust(nbytes * 2)[:nbytes * 2]
    out = bytearray()
    for i in range(0, len(text), 2):
        hi, lo = NIBBLES.index(text[i]), NIBBLES.index(text[i + 1])
        out.append((hi << 4) | lo)
    return bytes(out)


def find_block(radio, want_type):
    """Walk the custom-data chain. Returns (address, length) of the block's data."""
    head = radio.read_region(FLASH, CUSTOM_BASE, 12)
    if head[:8] != b"OpenGD77":
        raise IOError("自定义数据区没有 OpenGD77 魔数（读到 %r）" % head[:8])

    addr = 12
    while addr < 0x10000:
        hdr = radio.read_region(FLASH, CUSTOM_BASE + addr, 8)
        dtype, dlen = struct.unpack("<ii", hdr)
        if dtype == want_type:
            return (CUSTOM_BASE + addr + 8), dlen
        if dlen in (0, -1):                     # 0xFFFFFFFF reads as -1 signed
            break
        addr += 8 + dlen
    return None, 0


def epoch_to_unix(year2, day_of_year):
    """TLE epoch -> unix seconds. Year is 2 digits; these elements are all post-2000."""
    year = 2000 + year2
    start = time.mktime((year, 1, 1, 0, 0, 0, 0, 1, 0)) - time.timezone
    return start + (day_of_year - 1.0) * 86400.0


def parse_records(blob):
    sats = []
    for i in range(NUM_SATELLITES):
        rec = blob[i * REC_SIZE:(i + 1) * REC_SIZE]
        if len(rec) < REC_SIZE:
            break
        name = rec[0:8].decode("ascii", "replace").rstrip("\x00 ").rstrip()
        if not name or rec[0] in (0x00, 0xFF):
            continue

        l1 = unpack_tle(rec[8:20])
        l2 = unpack_tle(rec[20:48])
        rx1, tx1 = struct.unpack("<II", rec[48:56])

        try:
            year2 = int(l1[0:2])
            doy = float(l1[2:14])
        except ValueError:
            year2, doy = None, None

        sats.append({
            "index": i, "name": name, "l1": l1, "l2": l2,
            "rx": rx1, "tx": tx1,
            "epoch": (epoch_to_unix(year2, doy) if year2 is not None else None),
        })
    return sats


def cmd_list(radio):
    addr, dlen = find_block(radio, TYPE_SATELLITE_TLE)
    if addr is None:
        print("电台里没有卫星 TLE 数据块")
        return 1
    print("TLE 块 @ 0x%X，%d 字节" % (addr, dlen))

    blob = b"".join(radio.read_region(FLASH, addr + o, min(512, dlen - o))
                    for o in range(0, min(dlen, NUM_SATELLITES * REC_SIZE), 512))
    sats = parse_records(blob)
    now = time.time()

    print("\n%-9s %-11s %-11s %s" % ("卫星", "下行 MHz", "上行 MHz", "TLE 历元"))
    print("-" * 58)
    for s in sats:
        if s["epoch"] is None:
            age = "解析失败"
        else:
            days = (now - s["epoch"]) / 86400.0
            age = "%s  %.1f 天前" % (time.strftime("%m-%d %H:%M", time.gmtime(s["epoch"])), days)
        print("%-9s %-11.4f %-11.4f %s"
              % (s["name"], s["rx"] / 1e6, s["tx"] / 1e6, age))
    print("\n共 %d 颗" % len(sats))
    return 0


def cmd_dump(radio, path):
    addr, dlen = find_block(radio, TYPE_SATELLITE_TLE)
    if addr is None:
        print("电台里没有卫星 TLE 数据块")
        return 1
    blob = b"".join(radio.read_region(FLASH, addr + o, min(512, dlen - o))
                    for o in range(0, min(dlen, NUM_SATELLITES * REC_SIZE), 512))
    with open(path, "w", encoding="utf-8") as f:
        for s in parse_records(blob):
            f.write("%s\n  L1 %s\n  L2 %s\n" % (s["name"], s["l1"], s["l2"]))
    print("已写出 %s" % path)
    return 0


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"

# The radio stores an 8-character name, and for most satellites that string appears
# somewhere in CelesTrak's, so a substring match finds them. These are the ones where
# it does not, because the catalogue uses a different designator entirely.
ALIASES = {
    "AO-91":    "RADFXSAT (FOX-1B)",
    "PO-101":   "DIWATA-2B",
    "LilacSat": "LILACSAT-2",
    "UmKA-1":   "UMKA 1 (RS40S)",
}


def fetch_tles(url=CELESTRAK):
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as r:
        text = r.read().decode("ascii", "replace")

    out, lines = {}, [l.rstrip() for l in text.splitlines() if l.strip()]
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out[name] = (l1, l2)
    return out


def encode_from_tle(l1, l2):
    """Standard TLE text -> the radio's two packed fields.

    The column numbers are the TLE format's, verified against what the radio already
    had stored: its line 1 is exactly cols 19-20 + 21-32 + 34-43 concatenated, and its
    line 2 is the six orbital elements plus the revolution number, each copied from its
    own columns with the separating spaces dropped. Nothing is reformatted - the
    firmware parses these as text with atof(), so the field widths are the format.
    """
    p1 = l1[18:20] + l1[20:32] + l1[33:43]
    p2 = (l2[8:16] + l2[17:25] + l2[26:33] + l2[34:42] +
          l2[43:51] + l2[52:63] + l2[63:68] + " ")

    if len(p1) != 24 or len(p2) != 56:
        raise ValueError("TLE 列宽不对: L1=%d L2=%d" % (len(p1), len(p2)))
    return pack_tle(p1, 12), pack_tle(p2, 28)


def match_name(radio_name, catalogue):
    if radio_name in ALIASES:
        return ALIASES[radio_name] if ALIASES[radio_name] in catalogue else None

    want = radio_name.upper().replace(" ", "")
    for name in catalogue:
        if want in name.upper().replace(" ", ""):
            return name
    return None


def cmd_refresh(radio, do_write):
    # radio is a ChannelEditor (see __main__): one connection for the whole run,
    # because the radio only accepts one, and opening a second here fails with
    # "could not open port COM13: PermissionError".
    from ogd77_write import SECTOR_SIZE

    addr, dlen = find_block(radio, TYPE_SATELLITE_TLE)
    if addr is None:
        print("电台里没有卫星 TLE 数据块")
        return 1

    blob = b"".join(radio.read_region(FLASH, addr + o, min(512, dlen - o))
                    for o in range(0, min(dlen, NUM_SATELLITES * REC_SIZE), 512))
    sats = parse_records(blob)

    print("正在取 CelesTrak 业余卫星组…")
    cat = fetch_tles()
    print("  取到 %d 颗" % len(cat))
    print()

    now = time.time()
    plan, missing = [], []
    for s in sats:
        hit = match_name(s["name"], cat)
        if hit is None:
            missing.append(s["name"])
            continue
        l1, l2 = cat[hit]
        try:
            p1, p2 = encode_from_tle(l1, l2)
        except ValueError as e:
            missing.append("%s (%s)" % (s["name"], e))
            continue

        new_epoch = epoch_to_unix(int(l1[18:20]), float(l1[20:32]))
        plan.append((s, hit, p1, p2, new_epoch))

    print("%-9s %-22s %-12s %s" % ("电台里", "CelesTrak", "现在", "更新后"))
    print("-" * 62)
    for s, hit, _, _, new_epoch in plan:
        old = ("%.1f 天" % ((now - s["epoch"]) / 86400.0)) if s["epoch"] else "?"
        print("%-9s %-22s %-12s %.1f 天"
              % (s["name"], hit, old, (now - new_epoch) / 86400.0))
    if missing:
        print()
        print("!! 对不上名字、跳过: %s" % ", ".join(missing))

    if not do_write:
        print()
        print("这是预演，什么都没写。确认后加 --yes。")
        return 0

    base, sector = radio.read_sector(addr)
    sector = bytearray(sector)

    # The whole sector, before anything is touched. The TLE block is only 2520 bytes
    # but the sector is 4 KiB and the write is all-or-nothing, so the sector is the
    # unit that has to be recoverable.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backup",
                      "sat_sector_%02X_%s.bin" % (base // SECTOR_SIZE, stamp))
    open(bk, "wb").write(bytes(sector))
    print()
    print("已备份整个扇区 -> %s" % os.path.normpath(bk))

    # Only the two packed element fields are replaced. Name, frequencies and CTCSS
    # stay exactly as they were - this refreshes the orbit, not the channel.
    for s, hit, p1, p2, _ in plan:
        off = (addr - base) + s["index"] * REC_SIZE
        sector[off + 8:off + 20] = p1
        sector[off + 20:off + 48] = p2

    radio.write_sector(base, bytes(sector))
    print("已写入 %d 颗的新星历" % len(plan))

    return 0


# ---------------------------------------------------------------------------
# Adding satellites
# ---------------------------------------------------------------------------
# Frequencies are NOT from memory. Each row below is what two independent public
# sources agree on - SatNOGS DB's transmitter records (db.satnogs.org/api/transmitters,
# status "active", type Transceiver, mode FM) and AMSAT's FM satellite frequency page.
# Where the two disagreed, or where only one listed the satellite, it is not here.
#
# CTCSS is left at 0 for the Tevel constellation ON PURPOSE: neither source states a
# tone for it. A wrong tone is worse than none, because the radio then transmits
# something the satellite ignores and nothing says why - so this leaves the field empty
# and the operator can fill it in once they know.
#
# Deliberately NOT included, though SatNOGS lists their transmitters as active:
#   AO-27 (EYESAT A) and XIWANG-1 (HOPE-1) - neither appears on AMSAT's current FM
#   list, and SatNOGS "active" describes the transmitter record, not whether the
#   satellite is still working.
FM_SATELLITES = [
    # (radio name <=8 chars, CelesTrak name, downlink Hz, uplink Hz, txCTCSS 0.1Hz)
    ("TEVEL2-1", "TEVEL2-1", 436400000, 145970000, 0),
    ("TEVEL2-2", "TEVEL2-2", 436400000, 145970000, 0),
    ("TEVEL2-3", "TEVEL2-3", 436400000, 145970000, 0),
    ("TEVEL2-4", "TEVEL2-4", 436400000, 145970000, 0),
    ("TEVEL2-5", "TEVEL2-5", 436400000, 145970000, 0),
    ("TEVEL2-6", "TEVEL2-6", 436400000, 145970000, 0),
    ("TEVEL2-7", "TEVEL2-7", 436400000, 145970000, 0),
    ("TEVEL2-8", "TEVEL2-8", 436400000, 145970000, 0),
    ("TEVEL2-9", "TEVEL2-9", 436400000, 145970000, 0),
]


def build_record(radio_name, l1, l2, rx_hz, tx_hz, ctcss):
    p1, p2 = encode_from_tle(l1, l2)
    rec = bytearray(REC_SIZE)                      # zero-filled: an unused slot IS zeros
    rec[0:8] = radio_name.encode('ascii')[:8].ljust(8, bytes([0]))
    rec[8:20] = p1
    rec[20:48] = p2
    struct.pack_into("<IIHH", rec, 48, rx_hz, tx_hz, ctcss, 0)
    return bytes(rec)


def cmd_addfm(radio, do_write):
    from ogd77_write import SECTOR_SIZE

    addr, dlen = find_block(radio, TYPE_SATELLITE_TLE)
    if addr is None:
        print("电台里没有卫星 TLE 数据块")
        return 1

    blob = b"".join(radio.read_region(FLASH, addr + o, min(512, dlen - o))
                    for o in range(0, min(dlen, NUM_SATELLITES * REC_SIZE), 512))
    existing = parse_records(blob)
    have = {s["name"].upper() for s in existing}

    # loadKeps() stops at the first record whose name starts with a NUL, so new
    # entries have to be contiguous - a gap would hide everything after it.
    first_free = 0
    for i in range(NUM_SATELLITES):
        if blob[i * REC_SIZE] in (0x00, 0xFF):
            first_free = i
            break
    print("已有 %d 颗，第一个空槽 = %d，可用 %d 个" % (len(existing), first_free, NUM_SATELLITES - first_free))

    print("取 CelesTrak 星历…")
    cat = fetch_tles()

    plan, skip = [], []
    slot = first_free
    for radio_name, cat_name, rx, tx, ct in FM_SATELLITES:
        if radio_name.upper() in have:
            skip.append("%s (已有)" % radio_name)
            continue
        if cat_name not in cat:
            skip.append("%s (CelesTrak 里没有)" % radio_name)
            continue
        if slot >= NUM_SATELLITES:
            skip.append("%s (没槽位了)" % radio_name)
            continue
        l1, l2 = cat[cat_name]
        plan.append((slot, radio_name, cat_name, rx, tx, ct, l1, l2))
        slot += 1

    print()
    print("%-4s %-9s %-11s %-11s %-8s %s" % ("槽", "名称", "下行 MHz", "上行 MHz", "亚音", "星历历元"))
    print("-" * 66)
    now = time.time()
    for sl, nm, cn, rx, tx, ct, l1, l2 in plan:
        ep = epoch_to_unix(int(l1[18:20]), float(l1[20:32]))
        print("%-4d %-9s %-11.4f %-11.4f %-8s %.1f 天前"
              % (sl, nm, rx / 1e6, tx / 1e6, ("%.1f" % (ct / 10.0)) if ct else "无",
                 (now - ep) / 86400.0))
    if skip:
        print()
        print("跳过: %s" % ", ".join(skip))

    if not plan:
        print("没有要加的")
        return 0
    if not do_write:
        print()
        print("这是预演，什么都没写。确认后加 --yes。")
        return 0

    base, sector = radio.read_sector(addr)
    sector = bytearray(sector)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backup",
                      "sat_sector_%02X_%s.bin" % (base // SECTOR_SIZE, stamp))
    open(bk, "wb").write(bytes(sector))
    print()
    print("已备份整个扇区 -> %s" % os.path.normpath(bk))

    for sl, nm, cn, rx, tx, ct, l1, l2 in plan:
        off = (addr - base) + sl * REC_SIZE
        sector[off:off + REC_SIZE] = build_record(nm, l1, l2, rx, tx, ct)

    radio.write_sector(base, bytes(sector))
    print("已写入 %d 颗" % len(plan))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    # ChannelEditor rather than Radio: it is the same connection plus the sector
    # read-modify-write that refresh needs, and the radio allows only one.
    from ogd77_write import ChannelEditor

    with ChannelEditor() as r:
        if args[0] == "list":
            sys.exit(cmd_list(r))
        if args[0] == "dump":
            sys.exit(cmd_dump(r, args[1] if len(args) > 1 else "keps.txt"))
        if args[0] == "refresh":
            sys.exit(cmd_refresh(r, ("--yes" in args)))
        if args[0] == "addfm":
            sys.exit(cmd_addfm(r, ("--yes" in args)))
    sys.exit("未知命令 %r" % args[0])
