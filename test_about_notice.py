# -*- coding: utf-8 -*-
"""261008-17(마스터 SOT §14.3): 정보 창의 저작권·라이선스·오픈소스 고지.

사용자 지시: "도움말 정보에 개발자에게 모든 권한이 있다는 일반적으로 적는 내용을 포함 … (오픈 소스를 사용한 것도 고려해서)"
사용자 결정: 저작권 + GNU AGPL v3 배포 명시('All rights reserved' 는 쓰지 않는다 — PyQt6 GPL·PyMuPDF AGPL).

A. 저작권·AGPL v3·소스 위치·무보증 고지가 있다 · 'All rights reserved' 는 없다
B. requirements.txt 의 패키지가 모두 오픈소스 고지에 있다(동봉과 고지가 어긋나지 않게)
C. 실측한 라이선스 — kiwipiepy LGPL v3, PyQt6 GPL v3, PyMuPDF AGPL v3, FFmpeg GPL v3 · 동봉하지 않는 qpdf 는 없다
D. 실제 '정보' 창이 이 본문을 쓰고 링크를 열 수 있으며, 길어도 스크롤되는 창이다
"""
import os, sys, re
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from viewer import about
    html = about.about_html("9.9.9")
    # ── A ──
    chk("Copyright © 2026 KDJ" in html and "저작권은 개발자에게" in html, "A 저작권 표시")
    chk("AGPL" in html and about.SOURCE_URL in html, "A AGPL v3 배포 조건과 소스 위치")
    chk("보증" in html and "있는 그대로" in html, "A 무보증 고지")
    chk("all rights reserved" not in html.lower(), "A 'All rights reserved' 는 쓰지 않는다(GPL·AGPL 구성요소)")
    chk("v9.9.9" in html, "A 버전 표시")

    # ── B ──
    here = os.path.dirname(os.path.abspath(__file__))
    req = set()
    for ln in open(os.path.join(here, "requirements.txt"), encoding="utf-8"):
        ln = ln.split("#", 1)[0].strip()
        m = re.match(r"([A-Za-z0-9_.\-]+)", ln)
        if m:
            req.add(m.group(1).lower())
    miss = sorted(req - about.required_packages())
    chk(not miss, "B requirements.txt 의 패키지가 모두 고지에 있다", str(miss))

    # ── C ──
    lic = {n: l for n, l, _w, _p in about.OSS}
    chk(lic.get("kiwipiepy · kiwipiepy_model") == "LGPL v3", "C kiwipiepy 는 LGPL v3(종전 MIT 로 잘못 적힘)")
    chk(lic.get("PyQt6") == "GPL v3" and lic.get("PyMuPDF · MuPDF") == "AGPL v3", "C PyQt6 GPL v3 · PyMuPDF AGPL v3")
    chk(lic.get("FFmpeg") == "GPL v3" and "Qt 6" in lic, "C FFmpeg(GPL v3 빌드)·Qt 가 고지에 있다")
    chk("qpdf" not in html.lower(), "C 동봉하지 않는 qpdf 는 없다(분할기 분리 260913)")

    # ── D ──
    from viewer.app import MainWindow
    from PyQt6.QtWidgets import QDialog, QTextBrowser
    seen = {}
    QDialog.exec = lambda self: (seen.update(
        text=self.findChild(QTextBrowser, "aboutText").toPlainText(),
        links=self.findChild(QTextBrowser, "aboutText").openExternalLinks(),
        h=self.height()), 0)[1]
    mw = MainWindow(); mw._skip_save_on_close = True
    mw._show_about()
    t_ = seen.get("text", "")
    chk("Copyright © 2026 KDJ" in t_ and "AGPL" in t_ and "kiwipiepy" in t_, "D '정보' 창이 viewer.about 본문을 쓴다")
    chk(bool(seen.get("links")), "D 링크를 눌러 열 수 있다")
    chk(0 < seen.get("h", 0) <= 700, "D 창 높이가 화면에 들어간다(고지는 스크롤)", str(seen.get("h")))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
