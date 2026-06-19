# -*- coding: utf-8 -*-
"""260606-14: 다크모드 배경/드로어/썸네일, 툴바 버튼 동일 높이·중앙."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
app = QApplication.instance() or QApplication(sys.argv)
from viewer import theme
from viewer.app import MainWindow
mw = MainWindow()

# 다크 적용 → 상태/배경
mw.apply_theme("dark")
check("theme.is_dark True", theme.is_dark())
bg = mw._mv[0].scene.backgroundBrush().color()
check("메인뷰 배경 어두움", bg.lightness() < 60, f"L={bg.lightness()}")
check("드로어 다크 스타일", "2d2d30" in mw._drawer.styleSheet().lower())

# 라이트 적용 → 배경 흰색
mw.apply_theme("light")
bg2 = mw._mv[0].scene.backgroundBrush().color()
check("라이트 배경 밝음", bg2.lightness() > 200, f"L={bg2.lightness()}")
check("theme.is_dark False", not theme.is_dark())

# 썸네일 카드 다크: 배경 어두운 픽스맵
theme.set_dark(True)
from viewer.widgets.strip import make_card_pixmap
from PyQt6.QtGui import QPixmap
pm = make_card_pixmap(QPixmap(40, 40), "파일명", "p.1", 110, 150)
img = pm.toImage()
c = QColor(img.pixel(2, 2))      # 좌상단(카드 배경)
check("다크 카드 배경 어두움", c.lightness() < 80, f"L={c.lightness()}")
theme.set_dark(False)
pm2 = make_card_pixmap(QPixmap(40, 40), "파일명", "p.1", 110, 150)
c2 = QColor(pm2.toImage().pixel(2, 2))
check("라이트 카드 배경 밝음", c2.lightness() > 200, f"L={c2.lightness()}")

# 툴바 버튼 동일 높이
mv = mw._mv[0]
H = mv.TOOLBAR_H
widths = {
    "prev": mv.btn_prev_page.height() or mv.btn_prev_page.minimumHeight(),
}
heights = [mv.btn_prev_page.minimumHeight(), mv.btn_next_page.minimumHeight(),
           mv.spin_page.minimumHeight(), mv.cmb_fit.minimumHeight(),
           mv.btn_zoom_in.minimumHeight(), mv.btn_zoom_out.minimumHeight(),
           mw.btn_read.minimumHeight(), mw.btn_read_menu.minimumHeight(),
           mw.btn_main_mp3.minimumHeight(), mw.btn_capture.minimumHeight()]
check("모든 툴바 버튼 높이 통일(=H)", all(h == H for h in heights), f"H={H} hs={heights}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
