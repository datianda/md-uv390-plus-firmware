# -*- coding: utf-8 -*-
"""Wrap the artifact page source into a standalone local HTML file.

The artifact platform injects <!doctype>, charset, viewport and a small reset.
Opened from disk there is none of that, so a UTF-8 page renders as mojibake on
a zh-CN Windows. This adds the missing wrapper.
"""
import io, os, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "uv390-card.html"
DST = sys.argv[2] if len(sys.argv) > 2 else "../UV390操作卡.html"

HEAD = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  :root{color-scheme:light dark;
        padding-top:env(safe-area-inset-top,0px);
        padding-bottom:env(safe-area-inset-bottom,0px)}
  body{margin:0; font:14px system-ui,-apple-system,sans-serif; background:#fafaf9}
  img{max-width:100%}
  [hidden]{display:none!important}
</style>
'''
TAIL = "\n</body>\n</html>\n"

body = io.open(SRC, encoding="utf-8").read()
# the source starts with <title>/<link>/<style>; those belong in <head>
cut = body.index("<header")
io.open(DST, "w", encoding="utf-8", newline="\n").write(
    HEAD + body[:cut] + "</head>\n<body>\n" + body[cut:] + TAIL)
print("wrote %s  (%d bytes)" % (os.path.abspath(DST), os.path.getsize(DST)))
