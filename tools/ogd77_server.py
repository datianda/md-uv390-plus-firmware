# -*- coding: utf-8 -*-
"""Local control panel for a TYT MD-UV390 running OpenGD77.

Serves a browser UI on 127.0.0.1 and talks to the radio over its USB CDC
serial port. Nothing leaves this machine.

    python ogd77_server.py            # then open http://127.0.0.1:8390

All serial access is serialised behind one lock; the radio is opened lazily
and reopened if it is unplugged and plugged back in.
"""
import json, os, sys, threading, time, traceback, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ogd77 import find_port, FLASH, EEPROM, MCU_ROM, FLASH_SECURITY
from ogd77_write import (ChannelEditor, parse_channel, decode_bcd_freq,
                         encode_bcd_freq, CH_SIZE)
from ogd77_screen import png_bytes, inject_key, inject_func, KEYS

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
BACKUP_DIR = os.path.join(HERE, "..", "backup")
PORT = 8390

VFO_A, VFO_B = 0x07590, 0x075C8
BANKS = {"flash": FLASH, "eeprom": EEPROM, "rom": MCU_ROM, "security": FLASH_SECURITY}

_lock = threading.Lock()
_radio = None


def radio():
    """Lazily open the radio, reopening after an unplug."""
    global _radio
    if _radio is not None:
        try:
            if _radio.ser.is_open:
                return _radio
        except Exception:
            pass
        _radio = None
    _radio = ChannelEditor()
    return _radio


def drop():
    global _radio
    try:
        if _radio:
            _radio.close()
    except Exception:
        pass
    _radio = None


# --------------------------------------------------------------------------
# API handlers: each takes the parsed JSON body and returns a dict.
# --------------------------------------------------------------------------
def api_status(_):
    port = find_port()
    if not port:
        return {"connected": False, "reason": "未检测到电台 (VID 1FC9 / PID 0094)"}
    r = radio()
    info = r.firmware_info()
    return {"connected": True, "port": r.port, "info": info}


def api_channels(_):
    r = radio()
    return {"channels": r.list_channels()}


def api_channel_update(body):
    idx = int(body["index"])
    fields = {k: body[k] for k in ("name", "rx", "tx", "rxtone", "txtone")
              if k in body and body[k] != ""}
    for k in ("rx", "tx"):
        if k in fields:
            fields[k] = float(fields[k])
    for k in ("rxtone", "txtone"):
        if k in fields:
            fields[k] = None if fields[k] in ("none", "None", None) else float(fields[k])
    if not fields:
        raise ValueError("没有要修改的字段")
    before, after = radio().update_channel(idx, backup_dir=BACKUP_DIR, **fields)
    return {"index": idx, "before": before, "after": after, "verified": True}


def api_vfo(_):
    r = radio()
    out = {}
    for key, addr in (("A", VFO_A), ("B", VFO_B)):
        blk = r.read_region(FLASH, addr, CH_SIZE)
        out[key] = {"rx": decode_bcd_freq(blk[0x10:0x14]),
                    "tx": decode_bcd_freq(blk[0x14:0x18])}
    return {"vfo": out}


def api_screen(body):
    lines = [str(x)[:16] for x in body.get("lines", [])][:4]
    r = radio()
    r.show_screen()
    r.clear_screen()
    for i, line in enumerate(lines):
        r.text(0, i * 16, line)
    r.render()
    return {"shown": lines}


def api_screen_close(_):
    radio().close_screen()
    return {"closed": True}


def api_led(body):
    r = radio()
    n = max(1, min(10, int(body.get("times", 3))))
    for _ in range(n):
        (r.led_red if body.get("color") == "red" else r.led_green)()
    return {"flashed": n}


def api_command(body):
    action = body.get("action")
    r = radio()
    if action == "save":
        r.save_settings(with_vfos=True)
        return {"done": "settings saved"}
    if action == "reboot":
        r.reboot()
        drop()                                 # USB will re-enumerate
        return {"done": "rebooting - the USB port re-enumerates, reconnect in a few seconds"}
    raise ValueError("unknown action: %r" % action)


def api_hotspot(_):
    """Push the radio into MMDVM hotspot mode.

    usb_com.c: while settingsUsbMode == USB_MODE_CPS, a first byte of 0xE0
    (MMDVM_FRAME_START) switches settingsUsbMode to USB_MODE_HOTSPOT and pushes
    the hotspot UI -- provided hotspotType != HOTSPOT_TYPE_OFF in the radio's
    settings. Sending the MMDVM "get version" frame is the least intrusive way
    to trigger it.

    After this the CPS protocol is gone until the radio leaves hotspot mode, so
    the panel drops its connection.
    """
    r = radio()
    r.ser.reset_input_buffer()
    r.ser.write(bytes([0xE0, 0x03, 0x00]))      # MMDVM_GET_VERSION
    reply = r.ser.read(32)
    hexs = " ".join("%02X" % b for b in reply) or "(无响应)"

    # A bare 0x2D ('-') is the CPS ACK: the firmware fell through to the CPS
    # handler, i.e. hotspotType is still HOTSPOT_TYPE_OFF and the mode did not
    # change. Say so plainly instead of leaving the user guessing.
    if reply == b"-":
        return {"switched": False, "sent": "E0 03 00 (MMDVM_GET_VERSION)", "reply": hexs,
                "note": "电台回的是 CPS 的 ACK（2D = '-'），说明没有切换。\n"
                        "原因：Menu → Options → General Options → Hotspot 还是 Off。\n"
                        "把它改成 MMDVM（配 Pi-Star / MMDVMHost）或 BlueDV，再点一次。"}
    drop()
    return {"switched": True, "sent": "E0 03 00 (MMDVM_GET_VERSION)", "reply": hexs,
            "note": "电台屏幕顶部应出现 Hotspot。热点模式下本控制端无法通信，"
                    "要退出得重启电台。"}


def api_aes_key(body):
    """Write an AES-256 key into a slot. Requires an ENABLE_AES firmware."""
    keyid = int(body.get("keyid", 1))
    if body.get("generate"):
        import secrets
        key = secrets.token_bytes(32)
    else:
        txt = "".join(str(body.get("key", "")).split()).replace("-", "")
        try:
            key = bytes.fromhex(txt)
        except ValueError:
            raise ValueError("密钥必须是 64 个十六进制字符")
        if len(key) != 32:
            raise ValueError("密钥必须是 64 个十六进制字符（32 字节），当前 %d 字节" % len(key))
    reply = radio().set_aes_key(keyid, key)
    return {"keyid": keyid,
            "key": key.hex().upper(),
            "generated": bool(body.get("generate")),
            "reply": reply.hex() if reply else "(无响应)",
            "acked": bool(reply)}


def api_aes_txkey(body):
    txkey = int(body.get("txkey", 0))
    reply = radio().set_aes_tx_key(txkey)
    return {"txkey": txkey,
            "encrypted_tx": txkey != 0,
            "reply": reply.hex() if reply else "(无响应)",
            "acked": bool(reply)}


def api_bandlog_status(_):
    return radio().band_log_status()


def api_bandlog_run(body):
    on = bool(body.get("on"))
    ok, reason, raw = radio().band_log_run(on)
    return {"on": on, "accepted": ok, "reply": raw.hex() if raw else "(无响应)",
            "note": (reason or "")}


def api_bandlog_export(body):
    """Read the log region back and decode it. Only as much as asked for: the
    whole 2 MB takes minutes over the CPS protocol at 32 bytes a request."""
    import bandlog
    length = int(str(body.get("length", 0x20000)), 0)
    length = max(0x1000, min(length, bandlog.BAND_LOG_SIZE))
    r = radio()

    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, "bandlog_%s.bin" % time.strftime("%Y%m%d-%H%M%S"))
    r.dump(FLASH, bandlog.BAND_LOG_ADDRESS, length, path, "bandlog")

    with open(path, "rb") as f:
        records = bandlog.parse(f.read())

    return {"path": os.path.abspath(path), "bytes": length,
            "summary": bandlog.summarise(records),
            # The samples are what the heat map draws; everything else is small.
            "records": [{k: v for k, v in rec.items() if k != "samples"} for rec in records],
            "samples": [rec["samples"] for rec in records]}


def api_key(body):
    """Press a key on the radio from the browser.

    Needs an ENABLE_KEY_INJECTION firmware. The radio cannot tell us so directly
    for a key (it answers every command with the same ACK), so a wrong build just
    means nothing happens on screen - which the mirror makes obvious.
    """
    name = str(body.get("key", ""))
    if name not in KEYS:
        raise ValueError("未知按键 %r" % name)
    long_press, hold = bool(body.get("long")), bool(body.get("hold"))
    sk1, sk2 = bool(body.get("sk1")), bool(body.get("sk2"))
    inject_key(radio(), name, long_press or hold, hold, sk1, sk2)
    return {"pressed": name, "long": long_press or hold, "hold": hold,
            "sk1": sk1, "sk2": sk2}


def api_func(body):
    """Inject a FUNC_* UI event - reaches handlers no key sequence can."""
    code = int(body.get("code"), 0) if isinstance(body.get("code"), str) else int(body.get("code"))
    ok, raw = inject_func(radio(), code)
    if not ok:
        raise ValueError("固件未开 ENABLE_KEY_INJECTION（回应 %s）" % raw.hex())
    return {"func": code}


def api_backup(body):
    bank = BANKS[body.get("bank", "flash")]
    addr = int(str(body.get("addr", "0x8f000")), 0)
    length = int(str(body.get("length", "0x400")), 0)
    label = "".join(c for c in body.get("label", "dump") if c.isalnum() or c in "-_")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, "%s_0x%05X_%d.bin" % (label or "dump", addr, length))
    n = radio().dump(bank, addr, length, path, label)
    return {"bytes": n, "path": os.path.abspath(path)}


ROUTES = {
    "/api/status":       api_status,
    "/api/channels":     api_channels,
    "/api/channel":      api_channel_update,
    "/api/vfo":          api_vfo,
    "/api/screen":       api_screen,
    "/api/screen/close": api_screen_close,
    "/api/led":          api_led,
    "/api/command":      api_command,
    "/api/hotspot":      api_hotspot,
    "/api/bandlog/status": api_bandlog_status,
    "/api/bandlog/run":    api_bandlog_run,
    "/api/bandlog/export": api_bandlog_export,
    "/api/aes/key":      api_aes_key,
    "/api/aes/txkey":    api_aes_txkey,
    "/api/key":          api_key,
    "/api/func":         api_func,
    "/api/backup":       api_backup,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenGD77Panel/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _dispatch(self, path, body):
        fn = ROUTES.get(path)
        if not fn:
            return self._send(404, {"error": "no such endpoint: %s" % path})
        try:
            with _lock:
                self._send(200, {"ok": True, "data": fn(body)})
        except Exception as e:
            drop()
            traceback.print_exc()
            self._send(200, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/mirror":
            # PNG, not JSON: a full frame is 40 KB of pixels and base64 in a JSON
            # envelope would make it 55 KB of string for the browser to decode on
            # every refresh, when <img src> already does this for free.
            scale = parse_qs(urlparse(self.path).query).get("scale", ["3"])[0]
            try:
                with _lock:
                    raw = png_bytes(radio(), max(1, min(6, int(scale))))
                return self._send(200, raw, "image/png")
            except Exception as e:
                drop()
                return self._send(503, str(e).encode("utf-8"), "text/plain; charset=utf-8")
        if path.startswith("/api/"):
            return self._dispatch(path, {})
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(UI_DIR, rel))
        if not full.startswith(UI_DIR) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8"}.get(
                     os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(200, {"ok": False, "error": "请求体不是合法 JSON"})
        self._dispatch(urlparse(self.path).path, body)


if __name__ == "__main__":
    url = "http://127.0.0.1:%d/" % PORT
    print("OpenGD77 控制端")
    print("  串口: %s" % (find_port() or "未检测到电台"))
    print("  界面: %s" % url)
    print("  按 Ctrl+C 停止\n")
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("!! 无法监听 %d 端口: %s" % (PORT, e))
        print("!! 多半是已经有一个控制端在跑了 —— 浏览器直接开 %s 就行，" % url)
        print("!! 不用再启动第二个。要换端口就改本文件顶部的 PORT。")
        sys.exit(1)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        drop()
