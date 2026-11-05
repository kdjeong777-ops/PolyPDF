# -*- coding: utf-8 -*-
"""쪽 이동은 본문 창 가운데 아래(상태 줄), 맞춤 콤보는 내용 폭 (261105-26, 사용자 지시 — 디자인 SOT §2.9.2).

A. 1단: 쪽 이동 묶음(‹ 칸 / 전체 ›)이 상태 줄에 있고 가운데 = 본문 창 가운데(±1px) — 창 폭 여럿. 본문 툴바에는 없다
B. 2단: 두 묶음 모두 그 창 가운데 아래(±2px) — 261105-29. 오른쪽 고정 칸(진행 막대·가벼운 넘김·맞춤 콤보 …)이 넓어져
   겹치면 오른쪽 묶음은 겹치지 않을 만큼만 왼쪽으로 밀린다
G. 처음 그릴 때부터 가운데 — 창을 띄우고 문서를 연 직후(자리 맞추기 타이머를 기다리기 전) ±2px (261105-29)
H. 파일을 바꿔 전체 쪽 수 자릿수가 달라도('/ 6' ↔ '/ 487') 가운데 ±2px, 묶음 폭이 그대로 (261105-29)
C. 겹치지 않는다 — 묶음 ↔ 오른쪽 고정 칸·왼쪽 'N개 PDF', 좁은 창(820px)도. 임시 메시지가 떠도 묶음은 보인다
D. 맞춤 콤보 폭 = 가장 긴 항목 글 + 안 여백(왼쪽 6 + 화살표 자리 DROP_PAD_RIGHT + 테두리) — 사진 모드 '원래 크기' 도
E. 사진 모드에서도 묶음은 본문 창 가운데 아래
F. 쪽 이동 단추·칸이 그대로 일한다(› 누르면 다음 쪽, 칸에 쓰면 그 쪽) — 단축키·입력 처리기는 MainView 그대로
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, QRect
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_page_nav_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "쪽 이동 자리", echo=False)   # 마스터 §14.7.2 의 6 — 뜨는 모달은 닫는다
from viewer.app import MainWindow
from viewer.widgets import icons, page_nav_bar
import test_fixtures

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(n=6):
    from PyQt6.QtTest import QTest
    for _ in range(n):
        app.processEvents()
        QTest.qWait(page_nav_bar.RELAYOUT_MS + 5)    # 자리 맞추기는 RELAYOUT_MS 뒤 한 번 — 그만큼 기다린다


def rect_in(w, mw):
    return QRect(w.mapTo(mw, QPoint(0, 0)), w.size())


def mid(w, mw):
    return w.mapTo(mw, QPoint(0, 0)).x() + w.width() / 2.0


def right_fixed(mw):
    """상태 줄 오른쪽 고정 칸 중 보이는 것 — 쪽 이동 칸 밖."""
    host = mw.page_nav_host
    out = []
    from PyQt6.QtWidgets import QWidget
    for w in mw.status.findChildren(QWidget):
        if w.parentWidget() is mw.status and w is not host and w.isVisible() and w is not mw._bk_count \
                and w.x() > host.x():
            out.append(w)
    return out


def quick():
    """타이머를 기다리지 않고 이벤트만 — '처음 그릴 때' 자리를 본다."""
    for _ in range(3):
        app.processEvents()


import tempfile, fitz
_tmp = tempfile.mkdtemp(prefix="pagenav_")
def blank_pdf(n):
    p = os.path.join(_tmp, "p%d.pdf" % n)
    d = fitz.open()
    for _ in range(n):
        d.new_page()
    d.save(p); d.close()
    return p
pdf6, pdf487 = blank_pdf(6), blank_pdf(487)

# G — 처음 그릴 때부터 가운데
mw = MainWindow()
mw.resize(1600, 900)
mv0, mv1 = mw._mv
mv0.load_document(pdf6)
mw.show()
quick()
d = mid(mv0.page_nav, mw) - mid(mv0, mw)
chk(mv0.page_nav.isVisible() and abs(d) <= 2, "G 창을 띄운 직후(타이머 전) 묶음 가운데 = 본문 창 가운데", "차이 %.1f" % d)
pump()
pdf = str(test_fixtures.text_pdf())
mv0.load_document(pdf)
pump()
st = mw.status

# H — 파일마다 자릿수가 달라도 그 자리
w_nav = mv0.page_nav.width()
for p, label in ((pdf6, "/ 6"), (pdf487, "/ 487"), (pdf6, "/ 6"), (pdf, "/ 30")):
    mv0.load_document(p); quick()
    d = mid(mv0.page_nav, mw) - mid(mv0, mw)
    chk(mv0.lbl_page_total.text() == label and abs(d) <= 2 and mv0.page_nav.width() == w_nav,
        "H %s 파일로 바꾼 직후 가운데·묶음 폭 그대로" % label,
        "차이 %.1f 폭 %d→%d" % (d, w_nav, mv0.page_nav.width()))
pump()

# A — 1단
chk(mv0._toolbar.indexOf(mv0.btn_prev_page) < 0 and mv0._toolbar.indexOf(mv0.spin_page) < 0,
    "A 본문 툴바에 쪽 이동이 없다")
chk(st.isAncestorOf(mv0.page_nav) and mv0.page_nav.isVisible(), "A 쪽 이동 묶음은 상태 줄에 보인다")
for wd in (1920, 1600, 1300, 1000):
    mw.resize(wd, 900); pump()
    d = mid(mv0.page_nav, mw) - mid(mv0, mw)
    chk(abs(d) <= 1, "A 1단 %dpx 묶음 가운데 = 본문 창 가운데" % wd, "차이 %.1f" % d)
chk(not mv1.page_nav.isVisible(), "A 1단에서는 오른쪽 창 묶음을 숨긴다")
chk(rect_in(mv0.page_nav, mw).right() < rect_in(mw.cmb_fit, mw).left(),
    "A 쪽 이동은 맞춤 콤보·+ 0 − 보다 왼쪽(상태 줄 고정 칸 맨 앞)")

# B — 2단
mw.act_split.setChecked(True); pump()
mv1.load_document(pdf); pump()
for wd in (1920, 1600, 1300):
    mw.resize(wd, 900); pump()
    d = mid(mv0.page_nav, mw) - mid(mv0, mw)
    chk(abs(d) <= 2, "B 2단 %dpx 왼쪽 묶음 가운데 = 왼쪽 창 가운데" % wd, "차이 %.1f" % d)
    r1 = rect_in(mv1.page_nav, mw)
    d1 = mid(mv1.page_nav, mw) - mid(mv1, mw)
    others = [rect_in(w, mw) for w in right_fixed(mw)]
    edge = min([o.left() for o in others] or [mw.width()])
    ok_pos = abs(d1) <= 2 or (d1 < 0 and 0 < edge - r1.right() <= page_nav_bar.EDGE_GAP + 8)   # 가운데, 아니면 겹치지 않을 만큼만 밀림(+ 상태 막대 칸 간격)
    chk(mv1.page_nav.isVisible() and ok_pos and not any(r1.intersects(o) for o in others),
        "B 2단 %dpx 오른쪽 묶음 가운데 = 오른쪽 창 가운데(겹치면 그만큼만 왼쪽), 오른쪽 칸과 겹치지 않음" % wd,
        "차이 %.1f 오른쪽 칸까지 %d" % (d1, edge - r1.right()))
    chk(r1.left() > rect_in(mv0.page_nav, mw).right(), "B 2단 %dpx 두 묶음이 겹치지 않는다" % wd)
# 오른쪽 고정 칸이 넓어지면(진행 막대) 겹치지 않을 만큼만 왼쪽으로
mw.resize(1300, 900); pump()
mw.progress.setMaximumWidth(16777215); mw.progress.setFixedWidth(560); mw.progress.setVisible(True); pump()
r1 = rect_in(mv1.page_nav, mw); pr = rect_in(mw.progress, mw)
d1 = mid(mv1.page_nav, mw) - mid(mv1, mw)
chk(d1 < -2 and 0 < pr.left() - r1.right() <= 14 and r1.left() > rect_in(mv0.page_nav, mw).right(),
    "B 오른쪽 칸이 넓으면 오른쪽 묶음은 겹치지 않을 만큼만 왼쪽으로", "차이 %.1f 간격 %d" % (d1, pr.left() - r1.right()))
mw.progress.setVisible(False); mw.progress.setMinimumWidth(0); mw.progress.setMaximumWidth(220)
mw.resize(1600, 900); pump()
d1 = mid(mv1.page_nav, mw) - mid(mv1, mw)
chk(abs(d1) <= 2, "B 진행 막대가 사라지면 오른쪽 묶음은 다시 그 창 가운데(1600px)", "차이 %.1f" % d1)

# C — 겹침·좁은 창·임시 메시지
for split in (True, False):
    mw.act_split.setChecked(split); pump()
    mw.resize(820, 900); pump()
    navs = [mv0.page_nav] + ([mv1.page_nav] if split else [])
    rs = [rect_in(n, mw) for n in navs]
    others = [rect_in(w, mw) for w in right_fixed(mw)]
    hit = [(a, b) for a in rs for b in others if a.intersects(b)]
    chk(all(n.isVisible() for n in navs) and not hit and all(r.right() < mw.width() for r in rs),
        "C 820px %s 묶음이 오른쪽 칸과 겹치지 않고 창 안" % ("2단" if split else "1단"), str(hit))
    bk = rect_in(mw._bk_count, mw)
    chk(rs[0].left() > bk.left() + 100, "C 820px 왼쪽 메시지 자리를 남긴다", "%d %d" % (rs[0].left(), bk.left()))
mw.resize(1600, 900); pump()
st.showMessage("아주 긴 진행 메시지 " * 20, 5000); pump()
chk(mv0.page_nav.isVisible(), "C 임시 메시지가 떠도 쪽 이동은 보인다")
st.clearMessage(); pump()

# D — 맞춤 콤보 폭
cmb = mw.cmb_fit
def want_w():
    fm = cmb.fontMetrics()
    return max(fm.horizontalAdvance(cmb.itemText(i)) for i in range(cmb.count())) + 6 + icons.DROP_PAD_RIGHT + 2
chk(abs(cmb.width() - want_w()) <= 2, "D 맞춤 콤보 폭 = 가장 긴 항목 + 안 여백", "폭 %d 기대 %d" % (cmb.width(), want_w()))

# E — 사진 모드
mw._set_photo_mode(True); pump()
d = mid(mv0.page_nav, mw) - mid(mv0, mw)
chk(mv0.page_nav.isVisible() and abs(d) <= 1, "E 사진 모드 묶음 가운데 = 본문 창 가운데", "차이 %.1f" % d)
chk(abs(cmb.width() - want_w()) <= 2, "D 사진 모드('원래 크기' 더함) 콤보 폭도 내용에 맞춤", "폭 %d 기대 %d" % (cmb.width(), want_w()))
mw._set_photo_mode(False); quick()
mv0.load_document(pdf6); quick()
d = mid(mv0.page_nav, mw) - mid(mv0, mw)
chk(abs(d) <= 2, "H 사진 모드에서 돌아와 파일을 연 직후에도 가운데", "차이 %.1f" % d)
pump()

# F — 동작 그대로
mv0.load_document(pdf); pump()
mv0.go_to_page(0) if hasattr(mv0, "go_to_page") else None
pump()
p0 = mv0.current_page()
mv0.btn_next_page.click(); pump(20)
chk(mv0.current_page() == p0 + 1, "F › 누르면 다음 쪽", "%d→%d" % (p0, mv0.current_page()))
mv0.spin_page.setValue(5); mv0._on_spin_edited(); pump(20)
chk(mv0.current_page() == 4, "F 쪽 칸에 5 → 5쪽", str(mv0.current_page()))

mw.close()
print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
