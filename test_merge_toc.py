# -*- coding: utf-8 -*-
"""260606-24: 병합 책갈피 — 기존 TOC 재사용+페이지 오프셋 보정, 정규화."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def ck(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()

# 정규화
norm = mw._normalize_toc([[2, "x", 5], [3, "y", 6], [1, "z", 7]])
ck("정규화 첫 level=1", norm[0][0] == 1, f"{norm}")
ck("정규화 level<=직전+1", all(norm[i][0] <= norm[i-1][0] + 1 for i in range(1, len(norm))))

import fitz
t = tempfile.mkdtemp()
# A: 3쪽 + TOC, B: 2쪽 무TOC
a = os.path.join(t, "a.pdf"); da = fitz.open()
for i in range(3): da.new_page().insert_text((72, 72), f"A{i}")
da.set_toc([[1, "A제목", 1], [2, "A하위", 2]]); da.save(a); da.close()
b = os.path.join(t, "b.pdf"); db = fitz.open()
for i in range(2): db.new_page().insert_text((72, 72), f"B{i}")
db.save(b); db.close()

# 병합 [B, A] → A의 책갈피는 +2 오프셋
out_doc = fitz.open(); merged = []; offset = 0
for path in (b, a):
    src = fitz.open(path); n = src.page_count
    emb = src.get_toc(simple=True) or []
    for lvl, title, pg in emb:
        merged.append([max(1, lvl), title, offset + max(1, min(n, pg))])
    out_doc.insert_pdf(src); offset += n; src.close()
out = os.path.join(t, "m.pdf")
if merged: out_doc.set_toc(mw._normalize_toc(merged))
out_doc.save(out); out_doc.close()

dd = fitz.open(out); toc = dd.get_toc(simple=True); npg = dd.page_count; dd.close()
ck("병합 5쪽", npg == 5)
titles = {tt: pg for lvl, tt, pg in toc}
ck("A제목 페이지=3(오프셋+2)", titles.get("A제목") == 3, f"toc={toc}")
ck("A하위 페이지=4", titles.get("A하위") == 4, f"toc={toc}")

# 메서드 존재
ck("_gen_source_bookmarks", callable(getattr(mw, "_gen_source_bookmarks", None)))
ck("_normalize_toc", callable(getattr(mw, "_normalize_toc", None)))
# 무TOC 디지털 PDF 생성 시도(예외 없이 list 반환)
g = mw._gen_source_bookmarks(b)
ck("_gen_source_bookmarks 무TOC → list", isinstance(g, list))

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
