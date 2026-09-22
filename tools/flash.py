# -*- coding: utf-8 -*-
"""Flash a firmware image over DFU.

    python flash.py --list                     # just show the DFU device
    python flash.py ../firmware/out/X.bin --verify   # what is actually on the radio?
    python flash.py ../firmware/out/X.bin --yes

进 DFU 不用再动手了（2026-09-22 起）。本脚本用 CPS 0x9C：擦掉 app 的首扇区，
电台复位后只能进 DFU，实测 1 秒内就枚举出来。要固件带 ENABLE_DIAG。

早先这里走的是 0x9F（改写初始 SP 字的有效位），那条**不行** —— 这颗 STM32
拒绝重编程一个已编程的字，HAL 却返回 HAL_OK、错误码 0，字纹丝不动。
0x9C 用擦除绕开了这个限制。详见 reboot_to_dfu() 的注释，三条路都记在那儿。

What it does once the radio is in DFU: hands the image to the upstream loader,
which does the AMBE codec merge and the encrypted download exactly as the CPS
firmware loader does, then waits for the CDC port to come back and prints what
the radio reports.

Two things this deliberately does NOT do differently from upstream: the codec
merge and the image encoding. Both are quirks of TYT's bootloader (the image is
XORed with MDUV380_ENCODE_CIPHER, and the download is preceded by two vendor
0x91 commands that standard DfuSe tools do not send), so the proven code path is
the only sane one to use.

RECOVERY: a download that dies half way leaves the radio in DFU, not bricked -
the bootloader lives at 0x08000000 and nothing here writes below 0x0800C000.
Re-run this, or flash from CPS the usual way (which needs the STTub30 driver
back).
"""
import argparse, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOADER = os.path.join(HERE, "..", "firmware", "OpenGD77-AES256", "MDUV380_firmware",
                      "tools", "opengd77_stm32_firmware_loader.py")
DONOR = os.path.join(HERE, "..", "210525 MD-9600  V4 firmware for PLL2571",
                     "MD9600-CSV(2571V5)-V26.45.bin")
DFU_VID, DFU_PID = 0x0483, 0xDF11
CDC_VID, CDC_PID = 0x1FC9, 0x0094


def _backend():
    """pyusb needs a native libusb; the pip package ships one but is not on PATH."""
    import libusb_package
    return libusb_package.get_libusb1_backend()


def _loader_env():
    """The loader finds libusb itself, so put the packaged DLL where it can."""
    import libusb_package
    env = dict(os.environ)
    dll_dir = os.path.dirname(str(libusb_package.find_library("libusb-1.0")))
    env["PATH"] = dll_dir + os.pathsep + env.get("PATH", "")
    return env


def usb_present(vid, pid):
    import usb.core
    return usb.core.find(idVendor=vid, idProduct=pid, backend=_backend()) is not None


def wait_for(vid, pid, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if usb_present(vid, pid):
            return True
        time.sleep(0.5)
    print("!! 等了 %d 秒没等到%s (%04x:%04x)" % (timeout, what, vid, pid))
    return False


def reboot_to_dfu():
    """CPS 0x9C：擦掉 app 的首扇区，电台复位后只能进 DFU。成功返回 True。

    固件里有三条自动进 DFU 的路，这里用的是唯一实测能成的那条：

      0x9F  改写 app 的初始 SP 字，清掉有效位。**不行** —— 这颗 STM32 拒绝重编程
            一个已编程的字，而 HAL_FLASH_Program 照样返回 HAL_OK、错误码为 0，
            字却纹丝不动。这个脚本以前就卡在这条路上。
      0x9D  在 GPIOE 上伪造 PTT + 顶键跳进 bootloader。不留任何持久状态，
            但实测**没有回应、USB 也没重新枚举**，电台直接从总线上掉了
            （断电即恢复，没有损坏）。
      0x9C  **擦除**整个首扇区（0x0800C000 起 16 KB，即 app 的向量表）再复位。
            实测 1 秒内 DFU 就出现了。0x9F 失败的原因是"不能改写已编程的字"，
            而擦除绕开了这个限制 —— 这正是它该成功的道理。

    0x9C 是**持久**的：擦掉之后电台只会进 DFU，直到有人把那个扇区写回去。
    所以它只该紧挨着刷机用 —— 也就是这里。刷机本来就会重写这个扇区。
    不会变砖：扇区 0-2 是 bootloader，从不被碰，永远能起到 DFU。

    ACK 经常收不到（复位只延后 500 ms，回应容易赶不及），所以**不以回应为准**，
    只看 DFU 设备有没有出现。
    """
    sys.path.insert(0, HERE)
    from ogd77 import Radio

    if usb_present(DFU_VID, DFU_PID):
        print(" *  电台已经在 DFU 模式")
        return True

    try:
        with Radio() as r:
            r.ser.reset_input_buffer()
            r.ser.write(b"C" + bytes([0x9C, 0, 0]))
            r.ser.flush()
            time.sleep(0.2)
            r.ser.read(2)          # ACK 可有可无，见上
    except Exception as e:
        print("!! 送 0x9C 失败：%s" % e)
        print("   —— 请手动进 DFU：关机，按住 SK1 + PTT 再开机。")
        return False

    if wait_for(DFU_VID, DFU_PID, 25, "DFU 设备"):
        return True

    print("!! 0x9C 之后 DFU 没出现。固件是不是没开 ENABLE_DIAG？")
    print("   —— 请手动进 DFU：关机，按住 SK1 + PTT 再开机。")
    return False


CODEC_OFF, CODEC_LEN, DONOR_OFF = 0x6937C, 0x48BB0, 0xC2C7C
APP_BASE = 0xC000            # the app's offset in the MCU-ROM read region


def merged_image(image):
    """The bytes the loader should have written: the .bin with the AMBE codec spliced
    in, exactly as opengd77_stm32_firmware_loader.py does it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("loader", LOADER)
    loader = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, [sys.argv[0]]        # keep the module's argparse quiet
    try:
        spec.loader.exec_module(loader)
    finally:
        sys.argv = saved

    fw = bytearray(open(image, "rb").read())
    with open(DONOR, "rb") as f:
        f.seek(DONOR_OFF)
        enc = bytearray(f.read(CODEC_LEN))

    shift = CODEC_OFF % 1024
    for j in range(len(enc)):
        enc[j] ^= loader.MD9600_ENCODE_CIPHER[(j + shift) % 1024]
    fw[CODEC_OFF:CODEC_OFF + CODEC_LEN] = enc
    return bytes(fw)


def verify(image, chunks=4, size=2048):
    """Read the running image back out of flash and compare it with what we sent.

    Worth the few seconds: the radio's own "build date" is the timestamp of whichever
    object last got recompiled, so on an incremental build it happily reports the
    PREVIOUS build and there is no other way to tell what is actually on the radio.
    This compares the bytes.
    """
    sys.path.insert(0, HERE)
    from ogd77 import Radio, MCU_ROM

    want = merged_image(image)
    spots = [0] + [((len(want) - size) * (i + 1)) // chunks for i in range(chunks)]
    bad = []

    with Radio() as r:
        for off in spots:
            got = r.read_region(MCU_ROM, APP_BASE + off, size)
            if got != want[off:off + size]:
                bad.append(off)

    if bad:
        print("!! 回读校验不一致，偏移 %s" % ", ".join("0x%X" % b for b in bad))
        return False
    print(" *  回读校验通过（%d 处 x %d 字节）" % (len(spots), size))
    return True


def flash(image):
    cmd = [sys.executable, LOADER, "-f", image, "-m", "MD-UV380", "-s", DONOR]
    print(" *  " + " ".join(cmd[1:]))
    return subprocess.call(cmd, env=_loader_env())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image", nargs="?", help="要刷的 .bin（未合并 codec 的原始产物）")
    ap.add_argument("--list", action="store_true", help="只列出 DFU 设备，不刷")
    ap.add_argument("--dfu", action="store_true", help="只把电台送进 DFU，不刷")
    ap.add_argument("--yes", action="store_true", help="确认要写入（没有这个就只做检查）")
    ap.add_argument("--verify", action="store_true",
                    help="只把电台里跑的镜像跟这个 .bin 比一比，不刷")
    a = ap.parse_args()

    if a.list:
        return subprocess.call([sys.executable, LOADER, "-l"], env=_loader_env())

    if a.dfu:
        return 0 if reboot_to_dfu() else 1

    if a.verify:
        if not a.image:
            ap.error("要跟哪个 .bin 比？")
        return 0 if verify(a.image) else 1

    if not a.image:
        ap.error("要刷哪个 .bin？")
    if not os.path.isfile(a.image):
        sys.exit("找不到 %s" % a.image)
    if not os.path.isfile(DONOR):
        sys.exit("找不到 donor：%s" % DONOR)

    size = os.path.getsize(a.image)
    print("固件   %s (%d 字节)" % (a.image, size))
    print("donor  %s" % os.path.basename(DONOR))
    if not a.yes:
        print("\n这是预检，没有写入任何东西。确认无误后加 --yes 再跑一次。")
        return 0

    if not reboot_to_dfu():
        return 1
    rc = flash(a.image)
    if rc != 0:
        print("!! 烧录器返回 %d。电台应该还停在 DFU，可以直接重跑，或用 CPS 刷。" % rc)
        return rc

    if wait_for(CDC_VID, CDC_PID, 30, "电台重新枚举"):
        time.sleep(2)
        sys.path.insert(0, HERE)
        from ogd77 import Radio
        with Radio() as r:
            info = r.firmware_info()
        # Reported, not trusted: this timestamp comes from whichever object last got
        # recompiled, so an incremental build reports the previous one. verify() is
        # what actually says which image is on the radio.
        print(" *  电台回来了：%s  自报编译于 %s（增量构建时可能是旧值）"
              % (info.get("firmware"), info.get("build_date")))
        return 0 if verify(a.image) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
