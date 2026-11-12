# -*- coding: utf-8 -*-
import sys, io
import pdfplumber

src = r"F:\WorkBuddy\2026-09-21-18-04-59\RU_Power_Supply_Tool\docs\RU系列串口通讯说明.pdf"
out = r"F:\WorkBuddy\2026-09-21-18-04-59\RU_Power_Supply_Tool\docs\RU_protocol_raw.txt"

buf = []
with pdfplumber.open(src) as pdf:
    buf.append("PAGES=%d" % len(pdf.pages))
    for i, page in enumerate(pdf.pages):
        buf.append("\n" + "=" * 30 + " PAGE %d " % (i + 1) + "=" * 30)
        try:
            t = page.extract_text() or ""
        except Exception as e:
            t = "ERR:%s" % e
        buf.append(t)
        try:
            tables = page.extract_tables()
        except Exception as e:
            tables = []
        for ti, tb in enumerate(tables):
            buf.append("--- TABLE %d.%d ---" % (i + 1, ti + 1))
            for row in tb:
                buf.append(" | ".join("" if c is None else str(c).replace("\n", " ") for c in row))

with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(buf))
print("written", out, len("\n".join(buf)))
