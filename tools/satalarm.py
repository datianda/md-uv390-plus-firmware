# -*- coding: utf-8 -*-
"""Read the radio's satellite alarm state (CPS 0x98, ENABLE_SAT_ALERT builds).

Read-only, so it can be polled without disturbing what it measures - which is the
whole point. The three numbers that decide whether a pass alert fires live only in
RAM, and inferring them from the screen cost hours and got two of them wrong.
"""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ogd77 import Radio

ALARM_NAMES = {0: "NONE", 1: "CLOCK", 2: "SATELLITE", 3: "CANCELLED"}


def read_alarm(radio):
    radio.ser.reset_input_buffer()
    radio.ser.write(b"C" + bytes([0x98, 0, 0]))
    radio.ser.flush()
    time.sleep(0.1)
    r = radio.ser.read(12)
    if len(r) < 12:
        raise IOError("0x98 回应太短 (%s)。固件没开 ENABLE_SAT_ALERT？" % r.hex())
    import struct as _s
    atype = r[1]
    alarm_t, now_t = _s.unpack("<II", r[2:10])
    stage, menu = r[10], r[11]
    return atype, alarm_t, now_t, stage, menu

STAGES = {0: "从未跑过", 1: "守卫1: 未布防/未到点", 2: "守卫2: 在卫星屏",
          3: "超时放弃", 4: "已到点, 准备通知", 5: "通知已发出"}


def show(radio):
    atype, at, now, stage, menu = read_alarm(radio)
    fmt = lambda t: time.strftime("%H:%M:%S", time.gmtime(t)) if 1e9 < t < 4e9 else "??"
    print("  alarmType    = %d (%s)" % (atype, ALARM_NAMES.get(atype, "?")))
    print("  alarmTime    = %-12u  %s UTC" % (at, fmt(at)))
    print("  dateTimeSecs = %-12u  %s UTC" % (now, fmt(now)))
    if atype == 2:
        d = int(at) - int(now)
        print("  -> 距闹钟 %+d 秒（%+.1f 分钟）" % (d, d / 60.0))
    print("  tick 阶段    = %d (%s)" % (stage, STAGES.get(stage, "?")))
    print("  当前菜单号   = %d" % menu)
    print("  主机真实时间 = %s UTC" % time.strftime("%H:%M:%S", time.gmtime()))
    return atype, at, now


if __name__ == "__main__":
    with Radio() as r:
        show(r)
