# -*- coding: utf-8 -*-
"""다국어 SOT §4 · 화면 디자인 SOT §2.14 — 환경설정 창의 언어 칸 자리와 가로 스크롤 (261009-10 → 261107-12)

A. 처음 고른 항목은 '일반' 이고 그 쪽 첫 묶음이 '언어 / Language'(언어 콤보) — 어느 언어 화면에서도 첫 화면에 보인다.
   외부 언어팩은 '고급 › 관리' 쪽.
B. 내장 팩 **모든 언어**(ko + 팩)에서 기본 크기로 열었을 때 **어느 쪽에도 가로 스크롤바가 없다**.
C. 창은 최소 640×480 이고 화면보다 넓어지지 않는다.
D(261009-14). 녹화 장치 이름이 길어도(실제 PC) '발표 녹화' 쪽에 가로 스크롤이 생기지 않는다.

실제 글꼴로 재야 폭이 맞다 — 오프스크린 플랫폼에 Windows 글꼴 폴더를 준다(없으면 Qt 기본 글꼴로 잰다).
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QScrollArea, QGroupBox
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_i18n_settings_%d" % os.getpid())
app.setFont(QFont("Malgun Gothic", 9))
from viewer import i18n
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


import shutil
from viewer import settings_store
try:
    langs = ["ko"] + [c for c, _n, _s in i18n.available_languages() if c != "ko"]
    from viewer.app import MainWindow
    from viewer.widgets.settings_dialog import SettingsDialog
    for code in langs:
        i18n.install(None, code)
        mw = MainWindow(); mw._skip_save_on_close = True
        d = SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="general")
        # 261009-14: 실제 PC 처럼 녹화 장치 이름이 길게 들어 있어도(설치본 화면에서만 가로 스크롤이 났다)
        _long = "마이크 배열(Realtek(R) Audio) — Intel® 스마트 사운드 기술 디지털 마이크용 장치 이름이 긴 경우"
        for _cb in (d.rec.cmb_mic, d.rec.cmb_sys):
            _cb.addItem(_long); _cb.setEditText(_long)
        d.show(); app.processEvents()
        content = d._scrolls["general"].widget()
        groups = [g for g in content.findChildren(QGroupBox) if g.parent() is content and g.isVisibleTo(d)]
        first = min(groups, key=lambda g: g.y()) if groups else None
        chk(d.current_page() == "general" and first is not None and first.isAncestorOf(d.cmb_language),
            "A [%s] 일반 쪽 첫 묶음이 언어" % code, first.title() if first else "묶음 없음")
        chk(d._scrolls["manage"].widget().isAncestorOf(d.chk_ext_lang), "A [%s] 외부 언어팩은 관리 쪽" % code)
        bad = []
        for pid in d.page_ids():
            if d._page_items[pid].isHidden():
                continue
            d.open_page(pid); app.processEvents()
            sc = d._scrolls[pid]
            if sc.horizontalScrollBar().isVisible():
                bad.append("%s 내용 %d > 보이는 폭 %d" % (pid, sc.widget().minimumSizeHint().width(), sc.viewport().width()))
        chk(not bad, "B [%s] 기본 크기에서 어느 쪽에도 가로 스크롤바가 없다(D 긴 장치 이름 포함)" % code, str(bad))
        _scr = d.screen().availableGeometry().width() if d.screen() else 1920
        chk(d.width() >= 640 and d.height() >= 480 and d.width() < _scr, "C [%s] 창은 640×480 이상, 화면보다 좁다" % code,
            "%dx%d" % (d.width(), d.height()))
        d.close(); mw.close(); app.processEvents()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    i18n.install(None, "ko")
    shutil.rmtree(str(settings_store.settings_dir()), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
