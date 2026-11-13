# -*- coding: utf-8 -*-
"""다크 모드의 해시태그 단추 — '#' 거르기 단추 켜짐 색·태그 편집 창 칩 (디자인 SOT §2.5 '태그 켜짐'·'태그 칩'·§2.11, 261114-1).

사용자 보고: "다크모드에서 해시태그 관련 버튼 오류" — 책갈피창 '#1' 단추가 흰 상자에 흐린 회색 글자. 원인: 켜짐 바탕만
`#e3efff` 로 고정하고 글자는 테마색(다크 = 밝은 회색)이었다. 태그 편집 창 칩도 밝은 색만 있었다.
실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 다크에서 '#균열' 로 거르면 단추 = 바탕 #1456c4·글자 흰색 굵게, 그린 그림의 바탕 화소도 어둡고 파랗다(흰 상자 아님)
B. 켜진 채 라이트로 바꾸면 라이트 쌍(#e3efff·#1456c4)으로 다시 칠한다, 거르기를 풀면 기본
C. 다크에서 연 태그 편집 창 칩은 다크 값(밝은 바탕 #f7f7f7·#f3f8ff 없음)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtGui import QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_dark_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "다크 해시태그 단추", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(sec=0.2):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents(); time.sleep(0.01)


try:
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump(0.4)
    bt = mw.bookmark_tree
    mw.apply_theme("dark"); pump()

    # A
    bt.search_edit.setText("#균열"); pump()
    ss = bt.btn_tag.styleSheet().replace(" ", "").lower()
    chk(bt.btn_tag.text() == "#1" and "background:#1456c4" in ss and "color:#ffffff" in ss and "bold" in ss,
        "A 다크 켜짐 — 바탕 #1456c4·글자 흰색 굵게", ss)
    img = bt.btn_tag.grab().toImage()
    c = QColor(img.pixel(4, img.height() // 2))                  # 글자 없는 왼쪽 가운데
    chk(c.lightness() < 200 and c.blue() > c.red() + 60, "A 그린 단추 바탕이 파랗다(흰 상자 #e3efff 가 아님)", c.name())

    # B
    mw.apply_theme("light"); pump()
    ss = bt.btn_tag.styleSheet().replace(" ", "").lower()
    chk("background:#e3efff" in ss and "color:#1456c4" in ss, "B 켜진 채 라이트로 — 라이트 쌍으로 다시 칠함", ss)
    mw.apply_theme("dark"); pump()
    chk("background:#1456c4" in bt.btn_tag.styleSheet().replace(" ", "").lower(), "B 다시 다크로 — 다크 쌍")
    bt.search_edit.setText(""); pump()
    chk(bt.btn_tag.text() == "#" and bt.btn_tag.styleSheet() == "", "B 거르기를 풀면 테마 기본")

    # C
    from viewer.widgets.tag_edit_dialog import TagEditDialog
    dlg = TagEditDialog("a.pdf", ["가족"], ["가족", "보고서"], mw)
    sheets = " ".join(b.styleSheet().lower() for b in dlg.findChildren(QPushButton))
    chk(sheets and "#f7f7f7" not in sheets and "#f3f8ff" not in sheets and "#fffaf0" not in sheets,
        "C 다크에서 연 태그 편집 창 칩에 밝은 바탕이 없다", sheets[:200])
    chk("#1f3556" in sheets or "#3a3a3d" in sheets, "C 다크 칩 토큰을 쓴다", sheets[:200])
    dlg.reject()
    mw.apply_theme("light"); pump()
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
