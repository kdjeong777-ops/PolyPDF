# -*- coding: utf-8 -*-
"""260606-8: 2분할 메인 뷰어(활성 창 라우팅·창별 캡쳐) 검증."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow, HistoryItem
mw = MainWindow()

# 구조
check("두 메인뷰 존재", hasattr(mw, "_mv") and len(mw._mv) == 2)
check("기본 활성=0", mw._active_pane == 0)
check("두번째 창 기본 숨김", mw._panes[1].isHidden())
check("main_view 프로퍼티=활성창", mw.main_view is mw._mv[0])
# 4단 불변(splitter 자식 수)
check("가로 splitter 자식 4개 유지", mw.splitter.count() == 4)

# 활성 전환
mw.act_split.setChecked(True)       # 2분할 켜기
check("2분할 켜면 오른쪽 창 표시", not mw._panes[1].isHidden() and mw._split_on)
mw._set_active_pane(1)
check("활성 전환 → main_view=오른쪽", mw.main_view is mw._mv[1] and mw._active_pane == 1)
mw._set_active_pane(0)
check("활성 복귀 → main_view=왼쪽", mw.main_view is mw._mv[0])

# 두 PDF 로드(활성 창에 로드)
A = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
B = r"C:/Claude/MPDF/HM.pdf"
import os.path as _p
if _p.exists(A) and _p.exists(B):
    mw._set_active_pane(0)
    mw._load_main(HistoryItem(A, 0, "", "bookmark"))
    mw._set_active_pane(1)
    mw._load_main(HistoryItem(B, 0, "", "bookmark"))
    app.processEvents()
    f0 = mw._mv[0].current_file(); f1 = mw._mv[1].current_file()
    check("왼쪽 창 = A", f0 and _p.basename(f0) == _p.basename(A), f0)
    check("오른쪽 창 = B", f1 and _p.basename(f1) == _p.basename(B), f1)
    check("두 창이 서로 다른 PDF", f0 != f1)

    # 창별 캡쳐: 각 창을 캡쳐 → 공용 스크린샷 패널에 누적
    import viewer.app as appmod
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    n0 = mw.shot_strip.list.count()
    mw.action_screenshot(view=mw._mv[0])
    mw.action_screenshot(view=mw._mv[1])
    app.processEvents()
    check("창별 캡쳐 2건 누적", mw.shot_strip.list.count() >= n0 + 2,
          f"{n0}->{mw.shot_strip.list.count()}")
else:
    print("  SKIP 두 PDF 로드(파일 없음)")

# 토글 끄면 단일·활성 0
mw.act_split.setChecked(False)
check("2분할 끄면 오른쪽 숨김+활성0", mw._panes[1].isHidden() and mw._active_pane == 0
      and not mw._split_on)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
