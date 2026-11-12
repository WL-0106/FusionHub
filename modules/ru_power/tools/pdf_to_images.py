# -*- coding: utf-8 -*-
import os, io
import pdfplumber
from PIL import Image

src = r"F:\WorkBuddy\2026-09-21-18-04-59\RU_Power_Supply_Tool\docs\RU系列串口通讯说明.pdf"
outdir = r"F:\WorkBuddy\2026-09-21-18-04-59\RU_Power_Supply_Tool\docs\imgs"
os.makedirs(outdir, exist_ok=True)

log = []
with pdfplumber.open(src) as pdf:
    for i, page in enumerate(pdf.pages):
        imgs = page.images
        log.append("page %d images=%d" % (i + 1, len(imgs)))
        for j, im in enumerate(imgs):
            try:
                data = im["stream"].get_data()
            except Exception as e:
                log.append("  img %d get_data err %s" % (j, e))
                continue
            name = "p%02d_%d" % (i + 1, j + 1)
            try:
                pil = Image.open(io.BytesIO(data))
                w, h = pil.size
                log.append("  %s size=%sx%s mode=%s bytes=%d" % (name, w, h, pil.mode, len(data)))
                if max(w, h) < 1400:
                    sc = 1400.0 / max(w, h)
                    pil = pil.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
                if pil.mode not in ("RGB", "L"):
                    pil = pil.convert("RGB")
                fp = os.path.join(outdir, name + ".png")
                pil.save(fp)
                log.append("    saved " + fp)
            except Exception as e:
                fp = os.path.join(outdir, name + ".bin")
                with open(fp, "wb") as f:
                    f.write(data)
                log.append("    raw saved %s (open err %s)" % (fp, e))

print("\n".join(log))
