# -*- coding: utf-8 -*-
"""Wrap a freshly built .bin into a CPS firmware-loader zip.

The loader expects the archive the OpenGD77 project ships: the image under the
fixed name OpenMDUV380_10W_PLUS.bin, alongside the .gla language files. The
language files never change, so a new build is the old archive with one member
swapped - which is what this does, rather than reinventing the layout.

    python package_fw.py <new.bin> <out.zip> [template.zip]

The template defaults to the newest zip already in firmware/out/.
"""
import os, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "firmware", "out")
IMAGE_NAME = "OpenMDUV380_10W_PLUS.bin"


def newest_template(exclude):
    zips = [os.path.join(OUT_DIR, f) for f in os.listdir(OUT_DIR)
            if f.endswith(".zip") and os.path.join(OUT_DIR, f) != exclude]
    if not zips:
        raise SystemExit("firmware/out/ 里没有可用作模板的 zip")
    return max(zips, key=os.path.getmtime)


def package(bin_path, out_zip, template=None):
    out_zip = os.path.abspath(out_zip)
    template = template or newest_template(out_zip)
    image = open(bin_path, "rb").read()

    with zipfile.ZipFile(template) as src:
        names = src.namelist()
        if IMAGE_NAME not in names:
            raise SystemExit("模板 %s 里没有 %s" % (template, IMAGE_NAME))
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as dst:
            dst.writestr(IMAGE_NAME, image)
            for n in names:
                if n != IMAGE_NAME:
                    dst.writestr(n, src.read(n))
    return template, len(image), len(names)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    tmpl, size, n = package(sys.argv[1], sys.argv[2],
                            sys.argv[3] if len(sys.argv) > 3 else None)
    print("%s\n  固件 %d 字节，共 %d 个成员，语言文件取自 %s"
          % (sys.argv[2], size, n, os.path.basename(tmpl)))
