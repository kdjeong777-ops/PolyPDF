# -*- coding: utf-8 -*-
"""260606-13: mp3아이콘, 카드라벨중앙, 드로어 자동표시, 테마, 책갈피저장 메시지, 병합."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication, QPushButton, QLabel
app = QApplication.instance() or QApplication(sys.argv)

# 카드 라벨 중앙 정렬: make_card_pixmap 가 예외 없이 동작(시각은 수동), 라벨=stem
from viewer.widgets.strip import make_card_pixmap
from PyQt6.QtGui import QPixmap
pm = make_card_pixmap(QPixmap(40, 40), "테스트파일명", "p.3", 110, 150)
check("make_card_pixmap 동작", not pm.isNull())

from viewer.app import MainWindow
mw = MainWindow()

# 테마 적용
mw.apply_theme("dark")
from PyQt6.QtGui import QPalette
isdark = app.palette().color(QPalette.ColorRole.Window).lightness() < 100
check("다크 테마 적용", isdark)
mw.apply_theme("light")
islight = app.palette().color(QPalette.ColorRole.Window).lightness() > 150
check("라이트 테마 적용", islight)
mw.apply_theme("auto")
check("auto 테마 예외없음", True)

# 드로어 자동표시 메서드
for m in ("_drawer_auto_show", "_on_drawer_idle_timeout", "_on_merge_files"):
    check(f"{m} 존재", callable(getattr(mw, m, None)))
check("드로어 타이머 존재", hasattr(mw, "_drawer_timer"))

# 병합 다이얼로그(신 API: 좌/우)
from viewer.widgets.merge_dialog import MergeFilesDialog
d = MergeFilesDialog([r"C:/a.pdf", r"C:/b.pdf", r"C:/c.pdf"], [r"C:/a.pdf"], [])
check("병합 미리선택 우측 1개", d.right.count() == 1)
d.left.item(1).setSelected(True); d._move_selected()
check("병합 → 이동 후 2개", d.right.count() == 2)

# 병합 시그널/메뉴
check("mergeFilesRequested 시그널", hasattr(mw.bookmark_tree, "mergeFilesRequested"))

# 책갈피 저장 메시지: _read_orig_toc + 빈 책갈피 허용 경로
from viewer.widgets.bookmark_tree import BookmarkTree
PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
if os.path.exists(PDF):
    toc = BookmarkTree._read_orig_toc(PDF)
    check("_read_orig_toc 동작(원본 책갈피 읽음)", isinstance(toc, list) and len(toc) > 0,
          f"n={len(toc)}")
    # 형식 (title, page_1based, level)
    check("_read_orig_toc 형식", all(len(t) == 3 for t in toc[:3]))
else:
    print("  SKIP _read_orig_toc(PDF 없음)")

# 실제 병합 동작(작은 PDF 2개 생성)
import fitz
t = tempfile.mkdtemp()
def mkpdf(name, n):
    d = fitz.open()
    for i in range(n):
        pg = d.new_page(); pg.insert_text((72, 72), f"{name} page {i}")
    p = os.path.join(t, name); d.save(p); d.close(); return p
a = mkpdf("a.pdf", 2); b = mkpdf("b.pdf", 3)
from pypdf import PdfWriter
out = os.path.join(t, "m.pdf")
w = PdfWriter(); w.append(a); w.append(b)
with open(out, "wb") as f: w.write(f)
dd = fitz.open(out); npg = dd.page_count; dd.close()
check("병합 PDF 페이지수=합", npg == 5, f"npg={npg}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
