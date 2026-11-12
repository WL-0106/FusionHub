# -*- coding: utf-8 -*-
"""把 PDF 指定页整页渲染成 PNG，用于查图片形式的脚注。"""
import sys
import pdfplumber
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(BASE, "docs", "RU系列串口通讯说明.pdf")
OUT = os.path.join(BASE, "docs", "imgs")

pages = [int(x) for x in sys.argv[1:]] or [7]

with pdfplumber.open(PDF) as pdf:
    for pno in pages:
        page = pdf.pages[pno - 1]
        im = page.to_image(resolution=200)
        fp = os.path.join(OUT, "page%d_full.png" % pno)
        im.save(fp)
        print("saved", fp)
