# -*- coding: utf-8 -*-
"""Merge the AMBE codec into a built firmware WITHOUT touching the radio.

Replicates exactly what opengd77_stm32_firmware_loader.py does before the DFU
download (read donor @0xC2C7C, XOR-decrypt, splice at 0x6937C), so the merge
can be verified offline. It never opens a USB device and never encodes the
image for flashing - the output is a plain, inspectable image.

    python merge_codec_offline.py <built.bin> <donor.bin> <out.bin>
"""
import importlib.util, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CODEC_OFF, CODEC_LEN, DONOR_OFF = 0x6937C, 0x48BB0, 0xC2C7C

args = sys.argv[1:]                          # read args BEFORE clearing argv
if len(args) < 3:
    sys.exit(__doc__)
built, donor, out = args[:3]

spec = importlib.util.spec_from_file_location(
    "loader", os.path.join(HERE, "opengd77_stm32_firmware_loader.py"))
loader = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]                     # keep the module's argparse quiet
spec.loader.exec_module(loader)
CIPHER = loader.MD9600_ENCODE_CIPHER

fw = bytearray(open(built, "rb").read())
with open(donor, "rb") as f:
    f.seek(DONOR_OFF)
    enc = bytearray(f.read(CODEC_LEN))

print("固件      %s  (%d 字节)" % (os.path.basename(built), len(fw)))
print("donor     %s  (%d 字节)" % (os.path.basename(donor), os.path.getsize(donor)))
print("取出密文  donor 偏移 0x%X, %d 字节" % (DONOR_OFF, len(enc)))
if len(enc) != CODEC_LEN:
    sys.exit("!! donor 太短，取不满 %d 字节" % CODEC_LEN)

before = Counter(fw[CODEC_OFF:CODEC_OFF + CODEC_LEN]).most_common(2)
shift = CODEC_OFF % 1024
for j in range(len(enc)):
    enc[j] ^= CIPHER[(j + shift) % 1024]

if len(fw) < CODEC_LEN + CODEC_OFF:
    sys.exit("!! 固件太小，放不下编解码器")
fw[CODEC_OFF:CODEC_OFF + CODEC_LEN] = enc

after = Counter(fw[CODEC_OFF:CODEC_OFF + CODEC_LEN])
open(out, "wb").write(fw)
print()
print("合并前该区字节分布  %s" % [("%02X" % k, v) for k, v in before])
print("合并后不同字节值    %d 种" % len(after))
print("合并后最常见        %s" % [("%02X" % k, v) for k, v in after.most_common(3)])
print("仍为 0xFF 的字节    %d / %d" % (after.get(0xFF, 0), CODEC_LEN))
print()
print("写出 %s (%d 字节)" % (out, len(fw)))
