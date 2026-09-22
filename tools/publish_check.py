# -*- coding: utf-8 -*-
"""发布闸门：扫一遍要公开的仓库，发现不该外流的东西就拒绝。

    python tools/publish_check.py release/md-uv390-plus-firmware

为什么要有这个
--------------
发行仓库是**手工同步**的 —— 从主工作目录挑文件拷过去，全靠人记得哪些不能拷。
`.gitignore` 只在文件没被 `git add -f` 时才管用，而且它拦不住"名字看着无害、
内容不该外流"的文件。CI 里已经有一条断言检查固件 .bin 的 codec 窗口是空的，
这个脚本是同一个思路，只不过管的是**整个仓库的内容**。

管什么
------
1. **AMBE codec**（TYT 的版权）—— 固件里那段必须是空的，codec blob 不能进仓库
2. **整片 flash 备份 / 扇区导出**（每台机器的校准数据不一样，属于你的设备指纹）
3. **中文点阵字库**（从别人的字体生成的，见 FLASH-MAP.md）和任何字体文件本身
4. **BA7IQE 的源码树**（`reference/`）—— 那是别人的 fork，我们只是拿来看的
5. **令牌**（Gitee / GitHub）

检查的是 **git 已跟踪的文件**（也就是真会被推出去的东西），不是工作区，
因为 `.gitignore` 忽略掉的文件本来就不会推。外加一条：已跟踪但又被 .gitignore
声明要忽略的文件会单独报出来 —— 那说明有人 `-f` 强加过。
"""
import os
import re
import subprocess
import sys

CJK_FONT_MAGIC = b"CJKF"
CODEPLUG_HINTS = (b"OpenGD77", b"MD-UV")

# 名字就不该出现在公开仓库里的
BAD_EXT = {".bin", ".dfu", ".ttf", ".ttc", ".otf", ".bdf", ".pcf", ".hzk"}
# 只针对 blob 本身。`codec_bin.S` 是上游的 2 行存根（.incbin 指向一个不在仓库里的
# 文件），它必须留下否则编不过 —— 早期这条规则写成 `codec_bin` 就会误伤它。
BAD_PATH_RE = re.compile(
    r"(^|/)(reference|backup)/|ba7iqe|codec_bin_section|cjkfont.*\.bin$|flash_full",
    re.IGNORECASE)

TOKEN_RE = re.compile(
    rb"(gitee|github)[^\n]{0,40}(token|secret|password)[^\n]{0,8}[:=][^\n]{0,8}"
    rb"[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}",
    re.IGNORECASE)

TEXT_EXT = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".html", ".css",
            ".js", ".c", ".h", ".s", ".ld", ".cfg", ".bat", ".sh", ".gitignore"}


def tracked_files(repo):
    out = subprocess.check_output(["git", "-C", repo, "ls-files", "-z"])
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def ignored_but_tracked(repo, files):
    """.gitignore 说要忽略、却还是被跟踪的 —— 说明有人 git add -f 过。"""
    if not files:
        return []
    proc = subprocess.run(["git", "-C", repo, "check-ignore", "--stdin"],
                          input="\n".join(files).encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return [p for p in proc.stdout.decode("utf-8").splitlines() if p]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    repo = os.path.abspath(sys.argv[1])
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit("不是 git 仓库: %s" % repo)

    files = tracked_files(repo)
    problems = []

    for rel in files:
        full = os.path.join(repo, rel)
        ext = os.path.splitext(rel)[1].lower()

        if ext in BAD_EXT:
            problems.append((rel, "后缀 %s 不该进公开仓库" % ext))
            continue
        if BAD_PATH_RE.search(rel):
            problems.append((rel, "路径命中禁止名单"))
            continue

        if not os.path.isfile(full):
            continue
        size = os.path.getsize(full)

        with open(full, "rb") as fh:
            head = fh.read(4096)

        if head[:4] == CJK_FONT_MAGIC:
            problems.append((rel, "是中文字库 blob（magic CJKF）"))
            continue
        if size >= 8 * 1024 * 1024 and b"\x00" in head:
            problems.append((rel, "%.1f MB 的二进制，像是整片 flash 备份" % (size / 1048576.0)))
            continue

        if ext in TEXT_EXT or ext == "":
            with open(full, "rb") as fh:
                body = fh.read(1024 * 1024)
            m = TOKEN_RE.search(body)
            if m:
                problems.append((rel, "疑似令牌: %s..." % m.group(0)[:24].decode("latin-1")))

    for rel in ignored_but_tracked(repo, files):
        problems.append((rel, ".gitignore 说要忽略却被跟踪 —— 有人 git add -f 过"))

    print("扫描 %s" % repo)
    print("已跟踪文件 %d 个" % len(files))
    if problems:
        print("\n拒绝发布，%d 处问题：\n" % len(problems))
        for rel, why in problems:
            print("  %-60s %s" % (rel, why))
        sys.exit(1)
    print("通过：没有发现 codec blob、flash 备份、字库、字体、参考源码或令牌。")


if __name__ == "__main__":
    main()
