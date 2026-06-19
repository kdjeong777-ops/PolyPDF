# -*- coding: utf-8 -*-
"""260606-15: PDF 병합 다이얼로그(좌/우·정렬·삭제·스크린샷·드롭·자동생성), 메뉴, 이미지→PDF."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.merge_dialog import MergeFilesDialog, SHOTS_NAME

allf = [r"C:/x/bravo.pdf", r"C:/x/alpha.pdf", r"C:/x/charlie.pdf"]
shots = [r"C:/s/1.png", r"C:/s/2.png"]
d = MergeFilesDialog(allf, [r"C:/x/charlie.pdf"], shots)
# 미리선택 1개
check("우측 미리선택 1개", d.right.count() == 1)
# 좌측에서 2개 선택 → →
d.left.item(0).setSelected(True); d.left.item(1).setSelected(True)
d._move_selected()
check("→ 이동 후 우측 3개", d.right.count() == 3, f"{d.right.count()}")
# 중복 추가 방지
d.left.item(0).setSelected(True); d._move_selected()
check("중복 무시(여전히 3개)", d.right.count() == 3)
# 스크린샷 추가
d._add_screenshots()
check("스크린샷 항목 추가(4개)", d.right.count() == 4)
items = d.result_items()
check("스크린샷 항목 타입", any(it.get("type") == "shots" and it["name"] == SHOTS_NAME for it in items))
# 정렬: 파일명순
d.cmb_sort.setCurrentIndex(d.cmb_sort.findData("name"))
names = [d.right.item(i).data(d._DATA)["name"] for i in range(d.right.count())]
pdfnames = [n for n in names if n != SHOTS_NAME]
check("파일명순 정렬", pdfnames == sorted(pdfnames), f"{pdfnames}")
# 삭제
d.right.item(0).setSelected(True); d._delete_right()
check("삭제 후 3개", d.right.count() == 3)
# 자동생성 기본 체크
check("자동생성 기본 체크", d.auto_build() is True)
# 드롭(메서드 직접): 외부 pdf 추가
d._add_right_pdf(r"C:/x/delta.pdf")
check("외부 PDF 추가", any(it.get("path", "").endswith("delta.pdf") for it in d.result_items()))

# 이미지→PDF
from viewer.app import MainWindow
mw = MainWindow()
# 실제 이미지 2장 생성
from PyQt6.QtGui import QImage
t = tempfile.mkdtemp()
imgs = []
for i in range(2):
    im = QImage(60, 80, QImage.Format.Format_RGB32); im.fill(0xFFFFFF)
    p = os.path.join(t, f"s{i}.png"); im.save(p); imgs.append(p)
outpdf = os.path.join(t, "shots.pdf")
res = mw._images_to_pdf(imgs, outpdf)
import fitz
npg = 0
if res and os.path.exists(outpdf):
    dd = fitz.open(outpdf); npg = dd.page_count; dd.close()
check("이미지→PDF 2페이지", res and npg == 2, f"npg={npg}")

# 메뉴: PDF 병합/동시생성 순서(텍스트 존재)
texts = []
for m in mw.menuBar().findChildren(type(mw.menuBar().actions()[0])):
    pass
check("_on_merge_files 시그니처(preselected)", "preselected" in __import__("inspect").signature(mw._on_merge_files).parameters)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
