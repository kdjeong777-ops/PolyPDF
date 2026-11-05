# -*- coding: utf-8 -*-
"""미리보기 창의 쪽 이동은 모두 미리보기 아래 가운데 — 공통 `PageNav` (261105-27, 사용자 지시 '전체 통일' — 디자인 SOT §2.20).

창마다(인쇄·병합 파일 미리보기·다단 설정·병합 미리보기·크롭·가림·발표 보기 설정·목차 검토):
A. 쪽 이동이 공통 `PageNav` 하나다
B. 그 묶음이 미리보기 **아래**에 있고, 가운데 = 미리보기 가운데(±2px) — 옆에 다른 단추가 있어도
C. ❯ 를 누르면 다음 쪽(시트), 칸에 쓰면 그 쪽으로 간다(칸을 쓰지 않는 발표 보기 설정은 ❯ 만)
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QColor
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_preview_nav_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "미리보기 쪽 이동", echo=False)   # 마스터 §14.7.2 의 6 — 뜨는 모달은 닫는다
import test_fixtures
from viewer.widgets.page_nav import PageNav

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(n=8):
    for _ in range(n):
        app.processEvents()


def check(name, dlg, preview, editable=True, ready=None):
    dlg.resize(1100, 760); dlg.show(); pump()
    if ready:
        ready(); pump()
    navs = [w for w in dlg.findChildren(PageNav) if w.isVisible()]
    chk(len(navs) == 1, "A %s 쪽 이동은 공통 PageNav 하나" % name, str(len(navs)))
    if len(navs) != 1:
        return
    nav = navs[0]
    ny = nav.mapTo(dlg, QPoint(0, 0)).y()
    pb = preview.mapTo(dlg, QPoint(0, 0)).y() + preview.height()
    d = (nav.mapTo(dlg, QPoint(0, 0)).x() + nav.width() / 2.0) - (preview.mapTo(dlg, QPoint(0, 0)).x() + preview.width() / 2.0)
    chk(ny >= pb - 1 and abs(d) <= 2, "B %s 미리보기 아래 가운데" % name, "nav y %d / 미리보기 아래 %d, 가로 차이 %.1f" % (ny, pb, d))
    t0 = nav.text()
    nav.btn_next.click(); pump()
    chk(nav.text() != t0, "C %s ❯ 로 다음" % name, "%r → %r" % (t0, nav.text()))
    if editable:
        nav.spin.setValue(1); nav.spin.editingFinished.emit(); pump()
        chk(nav.text().split(" / ")[0].endswith("1"), "C %s 칸에 1 → 첫 쪽" % name, nav.text())
    dlg.close(); pump(2)


pdf = str(test_fixtures.text_pdf())          # 30쪽

from viewer.widgets.print_dialog import PrintScopeDialog
d = PrintScopeDialog(8, 2, 0, 0, None, preset_api=None, sample=pdf)
check("인쇄", d, d.preview)

from viewer.widgets import merge_dialog as md
d = md.MergeFilesDialog([pdf], [], [], None)
check("병합 파일 미리보기", d, d.preview.canvas, ready=lambda: d.left.item(0).setSelected(True))

from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
d = TwoUpSettingsDialog({}, None, sample=pdf)
check("다단 설정", d, d.preview.canvas)

from viewer.widgets.merge_preview import MergePreviewDialog
d = MergePreviewDialog({"make_cover": False, "make_toc": False, "make_divider": False, "nup": 2}, pdf)
check("병합 미리보기", d, d.widget.canvas)

from viewer.widgets.crop_dialog import CropDialog
d = CropDialog(pdf, current_page=0)
check("크롭", d, d.canvas)

from viewer.widgets.redact_dialog import RedactDialog
d = RedactDialog(path=pdf)
check("가림", d, d.view)

from viewer.widgets.view_settings_dialog import ViewSettingsDialog
pm = QPixmap(200, 280); pm.fill(QColor("white"))
d = ViewSettingsDialog(page_no=1, global_crop=(0, 0, 0, 0), page_crop=(0, 0, 0, 0), has_page_crop=False,
                       oddeven=(False, (0, 0), (0, 0)), preview_pages=[0],
                       renderer=lambda p, dpi: pm, pages_for=lambda p: [p],
                       step=lambda cur, dd: (cur + dd) if 0 <= cur + dd < 5 else None)
check("발표 보기 설정", d, d.preview, editable=False)

from viewer.widgets.toc_review_dialog import TocReviewDialog
rows = [{"title": t, "toc_page": None, "page": p, "level": 0, "src": "font"} for t, p in [("가", 2), ("나", 5)]]
d = TocReviewDialog(pdf, rows, method="font")
check("목차 검토", d, d.pv_scroll, ready=lambda: d.table.setCurrentCell(0, 1))

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
