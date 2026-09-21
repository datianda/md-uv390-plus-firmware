# -*- coding: utf-8 -*-
"""Read-only MMDVM probe for an OpenGD77 radio in hotspot mode.

Frame: 0xE0 | length | type | payload...
Only GET_VERSION (0x00) and GET_STATUS (0x01) are sent - both are queries,
neither keys the transmitter.
"""
import sys, time, serial
from ogd77 import find_port

FRAME_START = 0xE0
GET_VERSION, GET_STATUS = 0x00, 0x01
ACK, NAK = 0x70, 0x7F
MODES = {0: "Idle", 1: "D-Star", 2: "DMR", 3: "YSF", 4: "P25",
         5: "NXDN", 6: "POCSAG", 7: "M17", 98: "CW", 99: "Lockout"}


def xfer(ser, type_, payload=b"", wait=0.4):
    frame = bytes([FRAME_START, 3 + len(payload), type_]) + payload
    ser.reset_input_buffer()
    ser.write(frame)
    time.sleep(wait)
    return ser.read(256)


def show(label, raw):
    print("  %-12s %d 字节: %s" % (label, len(raw),
          " ".join("%02X" % b for b in raw[:24]) + (" ..." if len(raw) > 24 else "")))
    return raw


port = sys.argv[1] if len(sys.argv) > 1 else find_port()
if not port:
    sys.exit("找不到串口")
print("串口: %s\n" % port)
ser = serial.Serial(port, 115200, timeout=1.0)

print("[GET_VERSION]")
raw = show("原始", xfer(ser, GET_VERSION))
if len(raw) > 4 and raw[0] == FRAME_START and raw[2] == GET_VERSION:
    print("  协议版本  %d" % raw[3])
    print("  标识字符串 %r" % raw[4:raw[1]].decode("ascii", "replace"))
    print("  -> 热点模式已生效，MMDVM 链路正常")
elif raw == b"-":
    print("  回的是 CPS 的 ACK -> 电台不在热点模式")
else:
    print("  未识别的响应")

print("\n[GET_STATUS]")
raw = show("原始", xfer(ser, GET_STATUS))
if len(raw) > 5 and raw[0] == FRAME_START and raw[2] == GET_STATUS:
    modes, state = raw[3], raw[4]
    flags = raw[5] if len(raw) > 5 else 0
    print("  支持的模式位 0x%02X" % modes)
    print("  当前状态     %s (%d)" % (MODES.get(state, "未知"), state))
    print("  TX 中        %s" % ("是" if flags & 0x01 else "否"))
    print("  ADC 溢出     %s" % ("是" if flags & 0x02 else "否"))
ser.close()
