# -*- coding: utf-8 -*-
"""261009-14: 책갈피창 머리 단추·정렬 콤보가 잘리지 않는다 — 다국어 SOT §6 '폭' · 화면 디자인 SOT §2.8.4.

설치본·자동 캡처에서: 정렬 콤보 '수정일 순' 이 '수정일' 로(실제 화면 배율 150%), 영어 'Keep Selected' 가 'Keep Selec',
'Cancel' 이 'Cance' 로 잘렸다. 콤보는 '글자 폭 + 34px' 로 폭을 정해 화살표·여백이 모자랐고, 편집 단추 줄은 한 줄 고정이라
좁은 패널에서 단추를 글자 폭 아래로 눌렀다(디자인 SOT §2.8.4 '단추 줄은 FlowLayout' 위반).

A. ko·en 으로 실제 MainWindow 를 띄워 책갈피창을 **좁게**(170px) 둔 편집 모드에서 —
   글자가 있는 단추는 글자 폭이 다 들어가고, 정렬 콤보는 자기 크기(가장 긴 항목 + 화살표)를 받는다
B. 줄이 바뀐 단추가 아래 트리에 가리지 않는다(단추 아래 끝 ≤ 트리 위 끝)
실제 글꼴로 잰다(QT_QPA_FONTDIR).
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_i18n_panel_%d" % os.getpid())
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
    from viewer.app import MainWindow
    for code in ("ko", "en"):
        i18n.install(None, code)
        mw = MainWindow(); mw._skip_save_on_close = True
        mw.resize(1200, 800); mw.show()
        bt = mw.bookmark_tree
        bt.set_edit_mode(True)
        sp = bt.parentWidget()
        while sp is not None and not hasattr(sp, "setSizes"):
            sp = sp.parentWidget()
        if sp is not None:
            n = sp.count(); sizes = [170] + [max(100, (1200 - 170) // max(1, n - 1))] * (n - 1)
            sp.setSizes(sizes[:n])
        t0 = time.time()
        while time.time() - t0 < 0.6:
            app.processEvents(); time.sleep(0.01)
        clipped = []
        for b in bt.findChildren(QPushButton):
            if not b.isVisible() or not b.text().strip():
                continue
            need = b.fontMetrics().horizontalAdvance(b.text().strip()) + (b.iconSize().width() if not b.icon().isNull() else 0) + 6
            if need > b.width():
                clipped.append("%s %d<%d" % (b.text().strip(), b.width(), need))
        chk(not clipped, "A [%s] 좁은 책갈피창(편집 모드)에서 단추 글자가 잘리지 않는다" % code, str(clipped))
        cb = bt._sort_combo
        chk(cb.width() >= cb.sizeHint().width(), "A [%s] 정렬 콤보가 자기 크기(가장 긴 항목 + 화살표)를 받는다" % code,
            "%d < %d" % (cb.width(), cb.sizeHint().width()))
        tree_top = bt.tree.mapTo(bt, bt.tree.rect().topLeft()).y()
        hidden = [b.text().strip() for b in bt.findChildren(QPushButton)
                  if b.isVisible() and b.text().strip() and b.mapTo(bt, b.rect().bottomLeft()).y() > tree_top]
        chk(not hidden, "B [%s] 줄이 바뀐 단추가 트리에 가리지 않는다" % code, str(hidden))
        # C(261010-6, 화면 점검): 머리의 단추·콤보끼리 겹치지 않는다 — 정렬 줄('수정일 순' ↔ '📁 폴더')과
        #   편집 1행('트리' ↔ 책갈피명 수정)이 한 줄 고정이라 좁은 패널에서 서로 덮었다.
        from PyQt6.QtWidgets import QComboBox
        heads = [w for w in bt.findChildren((QPushButton, QComboBox))
                 if w.isVisible() and not bt.tree.isAncestorOf(w)]
        rects = [(w, w.geometry().translated(w.parentWidget().mapTo(bt, w.parentWidget().rect().topLeft())))
                 for w in heads]
        over = ["%s↔%s" % (a.text() if hasattr(a, "text") and not isinstance(a, QComboBox) else a.currentText(),
                           b.text() if not isinstance(b, QComboBox) else b.currentText())
                for i, (a, ra) in enumerate(rects) for b, rb in rects[i + 1:] if ra.intersected(rb).width() > 1
                and ra.intersected(rb).height() > 1]
        chk(not over, "C [%s] 좁은 책갈피창 머리의 단추·콤보가 서로 겹치지 않는다" % code, str(over))
        # 뷰어 모드(편집 아님)의 정렬 줄도
        bt.set_edit_mode(False)
        for _ in range(30):
            app.processEvents(); time.sleep(0.01)
        heads = [w for w in bt.findChildren((QPushButton, QComboBox))
                 if w.isVisible() and not bt.tree.isAncestorOf(w)]
        rects = [(w, w.geometry().translated(w.parentWidget().mapTo(bt, w.parentWidget().rect().topLeft())))
                 for w in heads]
        over = [i for i, (a, ra) in enumerate(rects) for b, rb in rects[i + 1:]
                if ra.intersected(rb).width() > 1 and ra.intersected(rb).height() > 1]
        chk(not over, "C [%s] 뷰어 모드에서도 겹치지 않는다" % code, str(len(over)))
        mw.close(); app.processEvents()
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
