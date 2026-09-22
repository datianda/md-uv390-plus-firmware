# -*- coding: utf-8 -*-
"""生成 / 校验 / 烧写 UV390 的中文点阵字库（外部 SPI flash）。

    python tools/cjkfont.py build  --font C:/Windows/Fonts/simhei.ttf
    python tools/cjkfont.py show   backup/cjkfont.bin 主菜单频道
    python tools/cjkfont.py sheet  backup/cjkfont.bin backup/cjkfont.png
    python tools/cjkfont.py flash  backup/cjkfont.bin --yes

为什么自己生成，不用现成的 blob
--------------------------------
BA7IQE 的点阵表注释写着 "Thank LoseHu provide compress chinese character table"，
来源与授权都不清楚，而且那份 blob 本来就不在他的源码包里。我们自己从一份字体文件
生成，**工具进仓库、字库不进仓库** —— 跟 AMBE codec 完全一样的处理：
公开仓库里没有任何别人的二进制，用户拿自己机器上的字体在本地生成。

字体选谁
--------
实测结论（**注意：早先"黑体比宋体清楚"那个结论是错的**，它是在灰度切二值那版
上测的，而那版本身就在丢笔画，比较没有意义）：

改成单色渲染后，**simsun.ttc 14px 最好** —— 宋体自带 12/14/16px 的嵌入式点阵，
单色模式下 FreeType 会直接用那套手工调过的字形，比缩放轮廓强。
12x12 笔画完整但「频」「射」这类密字发挤，14x14 是清晰度和一行字数（10 个）的平衡点。

simhei/simsun 都是微软的字体，**只能自己用，不能随包分发**。
要做可分发版本用文泉驿点阵宋体（WenQuanYi Bitmap Song）的 BDF，工具直接吃。

存储格式
--------
区起点 0x800000（芯片正中间）。实机备份 flash_full_16MB_20260920.bin 显示
0x223000-0xE00000 有 11.86 MB 连续空白，选 8 MB 是为了上下都留 5 MB 余量：
往下离码表/语音提示的 0x223000 很远，往上离频段日志的 0xE00000 也很远。

    0x800000  头 32 字节（其余补满一个 4 KB 扇区）
    0x801000  点阵数据，每字 bytesPerGlyph 字节

点阵排布**直接就是渲染器要的样子**，读出来不用任何解包：

    byte = data[x + (y // 8) * width]      位 = (byte >> (y % 8)) & 1

BA7IQE 把每字压到 16.5 字节（省 25%），代价是浮点乘、17 字节读、还要按奇偶相位
拆半字节。我们有 11.86 MB 空白，省那 27 KB 毫无意义，所以**按字节对齐存**，
固件侧一次 SPI 读就能用。

索引用 GB2312 双字节：offset = (b0-0xB0)*94 + (b1-0xA1)，b0 在 [0xB0,0xF7]、
b1 在 [0xA1,0xFE]，共 72*94 = 6768 个槽。0xD7FA-0xD7FE 那 5 个空洞**不压缩**，
留空槽 —— 省 5 个字不值得多一个分支和一处差一错的风险。

头里带上字号和字数，是为了让固件**从 flash 读几何参数**而不是写死：
换字号只要重生成再烧一次，固件不用重编。BA7IQE 没有头，所以他的固件既分不清
字库在不在，也认不出版本 —— 字库没烧就满屏乱码。
"""
import argparse
import binascii
import io
import os
import struct
import sys
import time

MAGIC = 0x464B4A43             # 'CJKF'
VERSION = 1
ENC_GB2312 = 1
HEADER_SIZE = 32
REGION_BASE = 8 * 1024 * 1024  # 0x800000
DATA_OFFSET = 0x1000           # 头独占一个扇区
REGION_LIMIT = 1024 * 1024     # 给字库留 1 MB

GB_LEAD_LO, GB_LEAD_HI = 0xB0, 0xF7
GB_TRAIL_LO, GB_TRAIL_HI = 0xA1, 0xFE
GB_COLS = GB_TRAIL_HI - GB_TRAIL_LO + 1               # 94
GB_ROWS = GB_LEAD_HI - GB_LEAD_LO + 1                 # 72
GB_SLOTS = GB_ROWS * GB_COLS                          # 6768

HEADER_FMT = "<IBBBBBBHIIIII"


def slot_to_gb(slot):
    return bytes([GB_LEAD_LO + slot // GB_COLS, GB_TRAIL_LO + slot % GB_COLS])


def gb_to_slot(b0, b1):
    if not (GB_LEAD_LO <= b0 <= GB_LEAD_HI and GB_TRAIL_LO <= b1 <= GB_TRAIL_HI):
        return None
    return (b0 - GB_LEAD_LO) * GB_COLS + (b1 - GB_TRAIL_LO)


def pack_glyph(bitmap, width, height):
    """bitmap[y][x] -> 渲染器要的列优先字节串。"""
    pages = (height + 7) // 8
    out = bytearray(width * pages)
    for y in range(height):
        row = bitmap[y]
        page = y >> 3
        bit = 1 << (y & 7)
        for x in range(width):
            if row[x]:
                out[x + page * width] |= bit
    return bytes(out)


def unpack_glyph(blob, width, height):
    return [[1 if blob[x + (y >> 3) * width] >> (y & 7) & 1 else 0
             for x in range(width)] for y in range(height)]


def render_truetype(path, px, width, height, threshold, yshift, index, gray=False):
    """
    默认走 **FreeType 单色渲染**（getmask mode="1"），不是"灰度渲染再切门限"。

    这个区别不是细节，是第一版字库缺笔画的**根本原因**：12px 下一条 1 px 的横笔
    经抗锯齿会摊到相邻两行、每行约 50% 灰，两行都够不到门限 128，于是整条笔画
    凭空消失 ——「用」少一横、「言」糊成一团。单色模式让 FreeType 自己做 hinting，
    笔画会被对齐到像素网格上，一条都不会丢。

    --gray 保留老路子只是为了对照，正常别用。
    """
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(path, px, index=index)
    glyphs = {}
    pad = 8

    # ---- 先量整本字库的墨迹范围，再决定往哪摆 -------------------------------
    # 这是第二版的教训：字形的墨迹并不是从第 0 行开始的。simsun 在 px=12 和
    # px=14 下墨迹都落在第 1 行到第 h 行，直接按 bbox 落位就会把**最后一行**挤出
    # 格子 ——「电」丢了竖弯钩变成「申」、「卫」丢了底横变成「卩」、「主」丢了顶点。
    # 与其让人去猜 --yshift，不如量出来自己对齐。
    ink_top, ink_bot, ink_left, ink_right = 1 << 30, -(1 << 30), 1 << 30, -(1 << 30)
    for slot in range(0, GB_SLOTS, 7):                # 抽样足够看出范围
        try:
            ch = slot_to_gb(slot).decode("gb2312")
        except UnicodeDecodeError:
            continue
        bb = font.getbbox(ch)
        m = Image.Image()._new(font.getmask(ch, mode="1"))
        if m.size[0] == 0:
            continue
        ink_top = min(ink_top, bb[1])
        ink_bot = max(ink_bot, bb[1] + m.size[1])
        ink_left = min(ink_left, bb[0])
        ink_right = max(ink_right, bb[0] + m.size[0])

    auto_y = auto_x = 0
    if not gray and ink_bot > -(1 << 30):
        ink_h, ink_w = ink_bot - ink_top, ink_right - ink_left
        auto_y = -ink_top + max(0, (height - ink_h) // 2)
        auto_x = -ink_left + max(0, (width - ink_w) // 2)
        if ink_h > height or ink_w > width:
            print("!! 墨迹 %dx%d 装不进 %dx%d 的格子，会被裁 —— 把 --px 调小一点"
                  % (ink_w, ink_h, width, height))

    clipped = [0]

    for slot in range(GB_SLOTS):
        try:
            ch = slot_to_gb(slot).decode("gb2312")
        except UnicodeDecodeError:
            glyphs[slot] = None                       # 0xD7FA-FE 的空洞
            continue

        if gray:
            canvas = Image.new("L", (width + 2 * pad, height + 2 * pad), 0)
            ImageDraw.Draw(canvas).text((pad, pad + yshift), ch, font=font, fill=255)
            p = canvas.load()
            glyphs[slot] = [[1 if p[x + pad, y + pad] >= threshold else 0
                             for x in range(width)] for y in range(height)]
            continue

        mask = font.getmask(ch, mode="1")
        img = Image.Image()._new(mask).convert("L")
        p = img.load()
        mw, mh = img.size
        bb = font.getbbox(ch)
        ox, oy = bb[0] + auto_x, bb[1] + auto_y + yshift

        grid = [[0] * width for _ in range(height)]
        lost = False
        for y in range(mh):
            ty = y + oy
            for x in range(mw):
                if not p[x, y]:
                    continue
                tx = x + ox
                if (0 <= tx < width) and (0 <= ty < height):
                    grid[ty][tx] = 1
                else:
                    lost = True   # 有墨迹掉到格子外面了
        if lost:
            clipped[0] += 1
        glyphs[slot] = grid

    if clipped[0]:
        print("!! %d 个字有笔画被裁出格子（共 %d）—— 调 --px 或 --yshift"
              % (clipped[0], GB_SLOTS))
    else:
        print("自检：%d 个字全部完整落在 %dx%d 格子里（自动对齐 x%+d y%+d）"
              % (GB_SLOTS, width, height, auto_x, auto_y))
    return glyphs


def render_bdf(path, width, height, yshift):
    """够用就好的 BDF 解析：只取 ENCODING / BBX / BITMAP。"""
    glyphs = {}
    cur = None
    with io.open(path, "r", encoding="latin-1") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("STARTCHAR"):
                cur = {"rows": [], "bbx": None, "enc": None, "reading": False}
            elif cur is None:
                continue
            elif line.startswith("ENCODING"):
                cur["enc"] = int(line.split()[1])
            elif line.startswith("BBX"):
                cur["bbx"] = [int(v) for v in line.split()[1:5]]
            elif line == "BITMAP":
                cur["reading"] = True
            elif line == "ENDCHAR":
                _store_bdf(glyphs, cur, width, height, yshift)
                cur = None
            elif cur["reading"]:
                cur["rows"].append(line)
    return glyphs


def _store_bdf(glyphs, cur, width, height, yshift):
    cp = cur["enc"]
    if cp is None or cp < 0 or cur["bbx"] is None:
        return
    try:
        gb = chr(cp).encode("gb2312")
    except (UnicodeEncodeError, ValueError):
        return
    if len(gb) != 2:
        return
    slot = gb_to_slot(gb[0], gb[1])
    if slot is None:
        return
    bw, bh, bx, by = cur["bbx"]
    # BDF 的 y 原点在基线、向上为正；换算成从上往下的行号
    top = height - (bh + by) - yshift
    grid = [[0] * width for _ in range(height)]
    for i, hexrow in enumerate(cur["rows"][:bh]):
        y = top + i
        if not (0 <= y < height) or not hexrow:
            continue
        val = int(hexrow, 16) >> max(0, len(hexrow) * 4 - bw) if len(hexrow) * 4 > bw \
            else int(hexrow, 16)
        for x in range(bw):
            if 0 <= x + bx < width and (val >> (bw - 1 - x)) & 1:
                grid[y][x + bx] = 1
    glyphs[slot] = grid


def build(args):
    width, height = args.width, args.height
    bpg = width * ((height + 7) // 8)
    ext = os.path.splitext(args.font)[1].lower()
    if ext == ".bdf":
        glyphs = render_bdf(args.font, width, height, args.yshift)
    else:
        glyphs = render_truetype(args.font, args.px or height, width, height,
                                 args.threshold, args.yshift, args.index, args.gray)

    data = bytearray()
    filled = 0
    for slot in range(GB_SLOTS):
        g = glyphs.get(slot)
        if g is None:
            data += b"\x00" * bpg
        else:
            data += pack_glyph(g, width, height)
            if any(any(r) for r in g):
                filled += 1

    if DATA_OFFSET + len(data) > REGION_LIMIT:
        sys.exit("字库超出预留的 %d KB" % (REGION_LIMIT // 1024))

    crc = binascii.crc32(bytes(data)) & 0xFFFFFFFF
    head = struct.pack(HEADER_FMT, MAGIC, VERSION, ENC_GB2312, width, height,
                       bpg, 0, GB_SLOTS, DATA_OFFSET, len(data), crc,
                       int(time.time()), 0)
    assert len(head) == HEADER_SIZE, len(head)

    blob = bytearray(b"\xFF" * DATA_OFFSET)
    blob[:HEADER_SIZE] = head
    blob += data

    out = args.out
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out, "wb") as fh:
        fh.write(blob)

    print("字体    %s" % args.font)
    print("字号    %dx%d，每字 %d 字节（按字节对齐，固件读出即用）" % (width, height, bpg))
    print("字数    %d 槽，其中 %d 个有点阵，%d 个空槽" % (GB_SLOTS, filled, GB_SLOTS - filled))
    print("数据    %d 字节，CRC32 %08X" % (len(data), crc))
    print("整块    %d 字节 -> %s" % (len(blob), out))
    print("烧写到  0x%06X（区内 0x%X 起是点阵）" % (REGION_BASE, DATA_OFFSET))
    if GB_SLOTS - filled > 100:
        print("!! 有 %d 个空槽，超出预期的 5 个 —— 检查这份字体是否覆盖 GB2312 全集"
              % (GB_SLOTS - filled))


def read_header(path):
    with open(path, "rb") as fh:
        head = fh.read(HEADER_SIZE)
    f = struct.unpack(HEADER_FMT, head)
    if f[0] != MAGIC:
        sys.exit("不是字库文件（magic %08X）" % f[0])
    return dict(version=f[1], encoding=f[2], width=f[3], height=f[4],
                bytesPerGlyph=f[5], glyphCount=f[7], dataOffset=f[8],
                dataLength=f[9], crc32=f[10], epoch=f[11])


def load(path):
    h = read_header(path)
    with open(path, "rb") as fh:
        fh.seek(h["dataOffset"])
        data = fh.read(h["dataLength"])
    got = binascii.crc32(data) & 0xFFFFFFFF
    if got != h["crc32"]:
        sys.exit("CRC 不符：头说 %08X，实际 %08X" % (h["crc32"], got))
    return h, data


def show(args):
    h, data = load(args.blob)
    print("%dx%d，每字 %d 字节，%d 槽，CRC %08X，生成于 %s"
          % (h["width"], h["height"], h["bytesPerGlyph"], h["glyphCount"], h["crc32"],
             time.strftime("%Y-%m-%d %H:%M", time.localtime(h["epoch"]))))
    rows = [""] * h["height"]
    for ch in args.text:
        try:
            gb = ch.encode("gb2312")
        except UnicodeEncodeError:
            continue
        if len(gb) != 2:
            continue
        slot = gb_to_slot(gb[0], gb[1])
        if slot is None:
            continue
        off = slot * h["bytesPerGlyph"]
        grid = unpack_glyph(data[off:off + h["bytesPerGlyph"]], h["width"], h["height"])
        for y in range(h["height"]):
            rows[y] += "".join("#" if v else "." for v in grid[y]) + " "
    for r in rows:
        print(r)


def sheet(args):
    from PIL import Image
    h, data = load(args.blob)
    cols = GB_COLS
    rows = (GB_SLOTS + cols - 1) // cols
    cw, chh = h["width"] + 1, h["height"] + 1
    img = Image.new("1", (cols * cw, rows * chh), 0)
    px = img.load()
    for slot in range(GB_SLOTS):
        off = slot * h["bytesPerGlyph"]
        grid = unpack_glyph(data[off:off + h["bytesPerGlyph"]], h["width"], h["height"])
        ox, oy = (slot % cols) * cw, (slot // cols) * chh
        for y in range(h["height"]):
            for x in range(h["width"]):
                if grid[y][x]:
                    px[ox + x, oy + y] = 1
    img.save(args.out)
    print("%d 字 -> %s (%dx%d)" % (GB_SLOTS, args.out, img.width, img.height))


SECTOR = 4096


def flash(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ogd77_write import FlashWriter
    with open(args.blob, "rb") as fh:
        blob = fh.read()
    if len(blob) > REGION_LIMIT:
        sys.exit("超出预留区")

    # write_sector() 一次只吃**一个**扇区（不足一扇区会把该扇区其余部分擦掉），
    # 所以这里补齐到扇区边界再逐扇区推。补的是 0xFF，和擦除态一致。
    pad = (-len(blob)) % SECTOR
    blob += b"\xFF" * pad
    n = len(blob) // SECTOR

    print("往 0x%06X 写 %d 字节（%d 个 4KB 扇区，尾部补 %d 字节 0xFF）"
          % (REGION_BASE, len(blob), n, pad))
    if not args.yes:
        sys.exit("加 --yes 才真写。写之前确认 backup/ 里有整片 flash 备份。")

    with FlashWriter() as w:
        w.prog_mode(("Claude", "writing", "CJK font"))
        for i in range(n):
            base = REGION_BASE + (i * SECTOR)
            w.write_sector(base, blob[i * SECTOR:(i + 1) * SECTOR])
            sys.stdout.write("\r  扇区 %d/%d  0x%06X" % (i + 1, n, base))
            sys.stdout.flush()
    print("\n写完。跑 `verify` 从电台回读校验。")


def verify(args):
    """从电台把字库读回来，和本地文件逐字节比。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ogd77 import Radio, FLASH
    with open(args.blob, "rb") as fh:
        blob = fh.read()
    with Radio() as r:
        got = r.read_region(FLASH, REGION_BASE, len(blob))
    if got == blob:
        print("一致：%d 字节，字库确实在电台的 0x%06X" % (len(blob), REGION_BASE))
        return
    bad = sum(1 for a, b in zip(got, blob) if a != b)
    first = next(i for i, (a, b) in enumerate(zip(got, blob)) if a != b)
    sys.exit("不一致：%d/%d 字节不同，首个差异在 +0x%X" % (bad, len(blob), first))


def main():
    ap = argparse.ArgumentParser(description="UV390 中文点阵字库工具")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="从字体文件生成字库")
    b.add_argument("--font", required=True, help="TTF/TTC/BDF")
    b.add_argument("--index", type=int, default=0, help="TTC 里的第几个字体")
    b.add_argument("--px", type=int, default=0, help="渲染字号，默认等于高度")
    b.add_argument("--width", type=int, default=12)
    b.add_argument("--height", type=int, default=12)
    b.add_argument("--threshold", type=int, default=128, help="灰度二值化门限 1-255")
    b.add_argument("--yshift", type=int, default=0, help="整体上下微调")
    b.add_argument("--gray", action="store_true",
                   help="退回灰度渲染+门限（只为对照；会丢笔画，别用）")
    b.add_argument("--out", default="backup/cjkfont.bin")
    b.set_defaults(func=build)

    s = sub.add_parser("show", help="把几个字打成 ASCII 点阵看看")
    s.add_argument("blob")
    s.add_argument("text")
    s.set_defaults(func=show)

    t = sub.add_parser("sheet", help="导出整本字库的 PNG 大图")
    t.add_argument("blob")
    t.add_argument("out", nargs="?", default="backup/cjkfont.png")
    t.set_defaults(func=sheet)

    f = sub.add_parser("flash", help="烧进电台外部 flash")
    f.add_argument("blob")
    f.add_argument("--yes", action="store_true")
    f.set_defaults(func=flash)

    v = sub.add_parser("verify", help="从电台回读字库并逐字节比对")
    v.add_argument("blob")
    v.set_defaults(func=verify)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
