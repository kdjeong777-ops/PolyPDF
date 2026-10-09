# -*- coding: utf-8 -*-
"""다국어 SOT §4 · 화면 디자인 SOT §2.14 — 환경설정 창의 언어 칸 자리와 창 폭 (261009-10)

A. '언어 / Language' 묶음이 설정 창 **맨 위**(첫 묶음)이고 언어 콤보·외부 언어팩 체크박스가 그 안에 있다
   — 종전에는 '화면 스타일' 안(스크롤 약 900px 아래)이라 사용자가 찾지 못했다.
B. 내장 팩 **모든 언어**(ko + 팩)에서 기본 크기로 열었을 때 **가로 스크롤바가 없다** — 종전에는 긴 체크박스 글자 하나가
   내용 폭을 652px(영어 758px)로 벌려 480px 창에서 모든 언어가 가로로 밀렸다.
C. 한국어 기본 폭은 종전 그대로(480) — 언어가 길면 그만큼만 넓어진다.

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
        d = SettingsDialog(dict(mw._prefs), parent=mw, host=mw)
        d.show(); app.processEvents()
        sc = d.findChild(QScrollArea); content = sc.widget()
        groups = [g for g in content.findChildren(QGroupBox) if g.parent() is content and g.isVisibleTo(d)]
        first = min(groups, key=lambda g: g.y()) if groups else None
        chk(first is not None and first.isAncestorOf(d.cmb_language) and first.isAncestorOf(d.chk_ext_lang),
            "A [%s] 언어 묶음이 맨 위(첫 묶음)에 있다" % code, first.title() if first else "묶음 없음")
        chk(not sc.horizontalScrollBar().isVisible(),
            "B [%s] 기본 크기에서 가로 스크롤바가 없다" % code,
            "내용 %d > 보이는 폭 %d" % (content.minimumSizeHint().width(), sc.viewport().width()))
        if code == "ko":
            chk(d.width() == 480, "C [ko] 기본 폭은 종전 그대로 480", str(d.width()))
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
