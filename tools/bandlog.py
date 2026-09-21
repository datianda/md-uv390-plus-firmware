# -*- coding: utf-8 -*-
"""Decode the MD-UV390 band occupancy log out of SPI flash.

The firmware writes one record per sweep pass into the last 2 MB of the 16 MB
flash. Layout mirrors application/include/functions/bandLog.h exactly:

    magic       uint32   "BLOG"
    version     uint8
    flags       uint8    bit0 = has fix, bit1 = 3D fix
    numBins     uint8
    mode        uint8    trxGetMode() at capture time
    epoch       uint32   RTC seconds, UTC
    centreFreq  uint32   10 Hz units
    stepFreq    uint32   10 Hz units per bin
    latitude    int32    1e-7 degrees, 0 when no fix
    longitude   int32
    ...then numBins bytes of RSSI

The log is cyclic, so a dump can contain a partly-overwritten tail. Records are
found by scanning for the magic and sanity-checking what follows, rather than
trusting the dump to start on a boundary.
"""
import struct

BAND_LOG_ADDRESS = 0x0E00000        # 14 MB
BAND_LOG_SIZE = 2 * 1024 * 1024
MAGIC = b"BLOG"
HEADER_FMT = "<4sBBBBIIIii"
HEADER_LEN = struct.calcsize(HEADER_FMT)   # 28

FLAG_HAS_FIX = 1 << 0
FLAG_3D_FIX = 1 << 1
MODES = {0: "None", 1: "Analog", 2: "DMR"}


def parse(blob):
    """Return the records found in a raw dump, oldest position first.

    Skips anything that is not a plausible record, which covers both the blank
    0xFF tail and the seam where the cyclic buffer wrapped over older data.
    """
    out = []
    i = 0
    end = len(blob)

    while i + HEADER_LEN <= end:
        if blob[i:i + 4] != MAGIC:
            i += 1                      # not aligned to a record; walk forward
            continue

        (_, version, flags, numBins, mode, epoch,
         centre, step, lat, lon) = struct.unpack_from(HEADER_FMT, blob, i)

        # A stale magic left over from overwritten data would otherwise produce
        # a record made of neighbouring garbage.
        if (version != 1) or (numBins == 0) or (i + HEADER_LEN + numBins > end):
            i += 1
            continue

        samples = list(blob[i + HEADER_LEN:i + HEADER_LEN + numBins])
        span = step * numBins                       # 10 Hz units
        out.append({
            "epoch": epoch,
            "mode": MODES.get(mode, str(mode)),
            "hasFix": bool(flags & FLAG_HAS_FIX),
            "is3D": bool(flags & FLAG_3D_FIX),
            "lat": (lat / 1e7) if (flags & FLAG_HAS_FIX) else None,
            "lon": (lon / 1e7) if (flags & FLAG_HAS_FIX) else None,
            "centreMHz": centre / 100000.0,
            "startMHz": (centre - (span // 2)) / 100000.0,
            "stopMHz": (centre + (span // 2)) / 100000.0,
            "stepHz": step * 10,
            "bins": numBins,
            "samples": samples,
            "peak": max(samples),
            "peakBin": samples.index(max(samples)),
        })
        i += HEADER_LEN + numBins

    return out


def summarise(records):
    if not records:
        return {"count": 0}

    epochs = [r["epoch"] for r in records if r["epoch"]]
    fixes = [r for r in records if r["hasFix"]]
    return {
        "count": len(records),
        "firstEpoch": (min(epochs) if epochs else None),
        "lastEpoch": (max(epochs) if epochs else None),
        "startMHz": min(r["startMHz"] for r in records),
        "stopMHz": max(r["stopMHz"] for r in records),
        "bins": records[0]["bins"],
        "withFix": len(fixes),
        "lat": (fixes[-1]["lat"] if fixes else None),
        "lon": (fixes[-1]["lon"] if fixes else None),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("用法: python bandlog.py <dump.bin>")
    recs = parse(open(sys.argv[1], "rb").read())
    s = summarise(recs)
    print("记录数 %d" % s["count"])
    if s["count"]:
        print("频率范围 %.5f - %.5f MHz, %d 个 bin" % (s["startMHz"], s["stopMHz"], s["bins"]))
        print("带定位的记录 %d 条" % s["withFix"])
