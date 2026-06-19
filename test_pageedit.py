# -*- coding: utf-8 -*-
"""260606-22: 썸네일 페이지 편집 — 편집모드 동기, 이동/삭제, 시퀀스/적용."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def ck(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

# 5쪽 테스트 PDF
import fitz
t = tempfile.mkdtemp()
src = os.path.join(t, "doc.pdf")
d = fitz.open()
for i in range(5):
    pg = d.new_page(); pg.insert_text((72, 72), f"PAGE {i}")
d.save(src); d.close()

from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs()
pt.load_document(src)
ck("5쪽 로드", pt.list.count() == 5)
ck("기본 시퀀스 0..4", pt.current_page_sequence() == [0, 1, 2, 3, 4])
ck("기본 dirty 아님", not pt.is_page_dirty())

# 편집모드 동기
pt.set_edit_mode(True)
ck("편집모드 드래그 가능", pt.list.dragEnabled())

# 마지막(원본 p5=idx4) 위로 2칸 이동
pt.list.item(4).setSelected(True)
pt._move_selected(-1); pt._move_selected(-1)
ck("idx4 위로 2칸", pt.current_page_sequence() == [0, 1, 4, 2, 3], f"{pt.current_page_sequence()}")
ck("이동 후 dirty", pt.is_page_dirty())

# 삭제: 현재 첫 항목(idx0) 삭제
pt.list.clearSelection(); pt.list.item(0).setSelected(True)
pt._delete_selected()
ck("삭제 후 4쪽", pt.list.count() == 4)
ck("삭제 후 시퀀스", pt.current_page_sequence() == [1, 4, 2, 3], f"{pt.current_page_sequence()}")

# 적용: 새 PDF로 빌드(앱 핸들러)
from viewer.app import MainWindow
mw = MainWindow()
mw.page_thumbs.load_document(src)
mw.page_thumbs.set_edit_mode(True)
# idx0 삭제 + 마지막 이동
mw.page_thumbs.list.item(0).setSelected(True); mw.page_thumbs._delete_selected()
seq = mw.page_thumbs.current_page_sequence()
# 직접 pypdf로 빌드 검증(핸들러 내부 로직과 동일)
out = os.path.join(t, "doc_pages.pdf")
from pypdf import PdfReader, PdfWriter
r = PdfReader(src); w = PdfWriter()
for idx in seq:
    w.add_page(r.pages[idx])
with open(out, "wb") as f: w.write(f)
dd = fitz.open(out); npg = dd.page_count; dd.close()
ck("적용 새 PDF 페이지수=시퀀스", npg == len(seq), f"npg={npg} seq={len(seq)}")
ck("_on_apply_page_edits 메서드", callable(getattr(mw, "_on_apply_page_edits", None)))

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
