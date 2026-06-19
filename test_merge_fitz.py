# -*- coding: utf-8 -*-
"""260606-23: fitz 병합(손상 PDF+이미지) 견고성, 카드 2줄 파일명·번호."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def ck(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

import fitz
t = tempfile.mkdtemp()
# 작은 PDF 2p
p1 = os.path.join(t, "a.pdf"); d = fitz.open()
for i in range(2):
    pg = d.new_page(); pg.insert_text((72, 72), f"A{i}")
d.save(p1); d.close()
# 이미지 1장
from PyQt6.QtGui import QImage
img = os.path.join(t, "s.png"); im = QImage(80, 100, QImage.Format.Format_RGB32); im.fill(0xAABBCC); im.save(img)

# fitz 병합: (손상 가능)아스팔트 + a.pdf + 이미지
ASP = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
out = os.path.join(t, "merged.pdf")
out_doc = fitz.open()
total = 0
try:
    items = []
    if os.path.exists(ASP):
        items.append(("pdf", ASP))
    items.append(("pdf", p1))
    items.append(("img", img))
    for kind, path in items:
        if kind == "pdf":
            src = fitz.open(path); out_doc.insert_pdf(src); total += src.page_count; src.close()
        else:
            pix = fitz.Pixmap(path)
            page = out_doc.new_page(width=pix.width, height=pix.height)
            page.insert_image(fitz.Rect(0, 0, pix.width, pix.height), filename=path); total += 1
    out_doc.save(out, garbage=4, deflate=True)
    out_doc.close()
    dd = fitz.open(out); npg = dd.page_count; dd.close()
    ck("fitz 병합 성공(손상 PDF+이미지)", npg == total and npg > 0, f"npg={npg} total={total}")
except Exception as e:
    ck(f"fitz 병합 ({e})", False)

# 카드: 2줄 파일명, 번호는 아이템 텍스트
from viewer.widgets.strip import make_card_pixmap, MiniStrip
from PyQt6.QtGui import QPixmap
pm = make_card_pixmap(QPixmap(60, 80), "아주아주긴파일명입니다테스트1234", "p.2", 110, 150)
ck("카드 렌더(2줄)", not pm.isNull())

from viewer.resources_path import resource_path
ms = MiniStrip("🖼")
ms.add_item(resource_path("icon.png"), kind="image", label="파일에이", prepend=False)
ms.add_item(resource_path("icon.png"), kind="image", label="파일비", page_index=1, prepend=False)
texts = [ms.list.item(i).text() for i in range(ms.list.count())]
ck("아이템 텍스트=번호(파일명 아님)", texts == ["1", "2"], f"{texts}")
ck("리스트 높이 = CARD_H+38", ms.list.maximumHeight() == ms.CARD_H + 22 + 16,
   f"h={ms.list.maximumHeight()} CARD_H={ms.CARD_H}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
