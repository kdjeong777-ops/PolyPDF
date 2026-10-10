# -*- coding: utf-8 -*-
"""261010-6: 책갈피 자동 생성 창 — 겹침·잘림 없음(화면 디자인 SOT §2.14·§2.15, 다국어 SOT §6 '폭').

화면 점검(`release_test.py checks --ui`)에서: '추출 모드' 의 라디오가 흐르는 줄로 둘째 줄에 넘어가는데 창이 그 높이를
주지 않아 '스캔/이미지 (OCR)' 가 아래 체크박스와 겹쳤고(ko 125px·en 144px), 줄바꿈 안내 두 개의 둘째 줄이 잘렸고,
영어에서 체크박스 글자가 오른쪽에서 잘렸다. 최상위 창은 줄바꿈 높이(heightForWidth)를 스스로 맞추지 않는다.

A. ko·en 에서 실제 창(기존 책갈피 있는 PDF)을 띄워 — 보이는 위젯끼리 겹치지 않는다
B. 줄바꿈 라벨은 지금 폭에서 필요한 높이를 받는다
C. 체크박스·라디오 글자가 잘리지 않는다
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
from PyQt6.QtWidgets import QApplication, QLabel, QCheckBox, QRadioButton, QWidget, QGroupBox
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_i18n_bmk_%d" % os.getpid())
app.setFont(QFont("Malgun Gothic", 9))
from viewer import i18n
import test_fixtures as fx
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def leaves(dlg):
    """보이는 '말단' 위젯(묶음 상자·빈 컨테이너 제외)과 창 좌표 사각형."""
    out = []
    for w in dlg.findChildren(QWidget):
        if not w.isVisible() or isinstance(w, QGroupBox) or w.parentWidget() is None:
            continue
        if type(w) is QWidget or w.metaObject().className() in ("QWidget", "QDialogButtonBox"):
            continue
        if any(isinstance(c, QWidget) and c.isVisible() for c in w.children()
               if not isinstance(w, (QLabel, QCheckBox, QRadioButton))) and not isinstance(w, (QLabel, QCheckBox, QRadioButton)):
            continue                     # 안에 다른 위젯이 있는 것(콤보·스핀 등의 속 부품을 품은 것)은 그 자체만 본다
        r = w.rect().translated(w.mapTo(dlg, w.rect().topLeft()))
        out.append((w, r))
    return out


pdf = str(fx.text_pdf())                  # 책갈피(TOC) 12개 — '기존 책갈피' 묶음이 보인다
try:
    from viewer.widgets.bookmarker_dialog import BookmarkerDialog
    for code in ("ko", "en"):
        i18n.install(None, code)
        dlg = BookmarkerDialog(default_pdf=__import__("pathlib").Path(pdf))
        dlg.show(); pump(0.5)
        chk(dlg.grp_exist.isVisible(), "[%s] 기존 책갈피 묶음이 보인다(시험 조건)" % code)
        items = [(w, r) for w, r in leaves(dlg) if isinstance(w, (QLabel, QCheckBox, QRadioButton))
                 or w.metaObject().className() in ("QLineEdit", "QPushButton", "QSpinBox")]
        over = []
        for i, (a, ra) in enumerate(items):
            for b, rb in items[i + 1:]:
                if a.isAncestorOf(b) or b.isAncestorOf(a):
                    continue
                x = ra.intersected(rb)
                if x.width() > 2 and x.height() > 2:
                    over.append("%s↔%s" % ((getattr(a, "text", lambda: "")() or "")[:16],
                                           (getattr(b, "text", lambda: "")() or "")[:16]))
        chk(not over, "A [%s] 보이는 위젯끼리 겹치지 않는다" % code, str(over[:4]))
        short = ["%s %d<%d" % (l.text()[:20], l.height(), l.heightForWidth(l.width()))
                 for l in dlg.findChildren(QLabel)
                 if l.isVisible() and l.wordWrap() and l.heightForWidth(l.width()) > l.height() + 1]
        chk(not short, "B [%s] 줄바꿈 라벨이 필요한 높이를 받는다" % code, str(short))
        cut = ["%s %d<%d" % (b.text()[:20], b.width(), b.sizeHint().width())
               for b in dlg.findChildren((QCheckBox, QRadioButton))
               if b.isVisible() and b.sizeHint().width() > b.width() + 1]
        chk(not cut, "C [%s] 체크박스·라디오 글자가 잘리지 않는다" % code, str(cut))
        dlg.close(); app.processEvents()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    i18n.install(None, "ko")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
