# -*- coding: utf-8 -*-
"""261107-37: 발표 띠 '단어장' — 단어장 밑줄·뜻 풍선을 발표 화면 위치에 정확히 (발표 SOT §6.2).

검은 칸(=단어)을 그린 PDF 를 발표로 열고, 단어장 쪽 좌표 변환(`StudyMixin._study_disp_rect` — 글자층 회전·OCR dpi)
으로 만든 상자를 공급자로 넘긴다. 발표 변환이 그 상자를 **실제로 그려진 검은 칸** 위로 옮기는지 픽셀로 본다.
A. /Rotate 90 쪽(글자층 좌표 = 회전 전) — 밑줄 상자가 검은 칸과 겹친다, 실제 마우스 이동으로 풍선이 그 단어 바로 아래에
B. 세로 쪽 상하 2분할 — 상부에선 위 단어만, 하부에선 아래 단어만(반쪽 밖은 긋지도 맞히지도 않는다), 좌우 2쪽 + 크롭
C. 스캔 쪽(OCR 픽셀 좌표 @150dpi) — 같은 검사, 화면 채움
D. 단어 위 클릭은 여전히 다음으로 넘김, 누르면 풍선이 숨는다, 빈 곳에선 풍선 없음
E. 꺼져 있으면 공급자를 부르지 않고 아무것도 긋지 않는다 · 단추를 누르면 켜지고 vocabChanged
F. 실제 연결 길 — PresentMixin._presentation_vocab → StudyMixin.vocab_overlay_for(DB 만 대역) → 상자·수준·뜻 풍선
밑줄 모양은 본문과 같은 `vocab_marks.vocab_mark_line`(수준별 색·반투명·상자 바로 아래, 단어장 SOT §11.2).
수정 전 코드: 발표 창에 단어장 인자가 없어 실패 · 바로 전 임시 밑줄(상자 안쪽·한 색)로는 밑줄 검사 6개 실패.
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_presvocab261107_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="presvocab261107_"))
try:
    from viewer.study_controller import StudyMixin
    from viewer.widgets.presentation import PresentationWindow, VOCAB_TIP_DELAY_MS
    disp = lambda w, dpi, rot, rmat: StudyMixin._study_disp_rect(None, w, dpi, rot, rmat)

    # --- A: /Rotate 90 (글자층 좌표는 회전 전 공간) ---
    pa = root / "rot.pdf"
    d = fitz.open(); pg = d.new_page(width=595, height=842)
    RA = fitz.Rect(120, 200, 260, 250)
    pg.draw_rect(RA, color=(0, 0, 0), fill=(0, 0, 0))
    pg.set_rotation(90)
    rmat = pg.rotation_matrix
    d.new_page(width=842, height=595)
    d.save(str(pa)); d.close()
    box_a = disp({"x0": RA.x0, "y0": RA.y0, "x1": RA.x1, "y1": RA.y1}, 0, 90, rmat)

    # --- B: 세로 쪽(상하 2분할) — 위·아래 단어 ---
    pb = root / "split.pdf"
    d = fitz.open(); pg = d.new_page(width=595, height=842)
    RT, RB = fitz.Rect(100, 90, 260, 130), fitz.Rect(300, 720, 470, 760)
    for r in (RT, RB):
        pg.draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0))
    d.new_page(width=595, height=842)
    d.save(str(pb)); d.close()

    # --- C: 스캔 쪽(그림만) + OCR 픽셀 좌표 @150dpi ---
    pc = root / "scan.pdf"
    src = fitz.open(); sp = src.new_page(width=842, height=595)
    RC = fitz.Rect(400, 300, 560, 345)
    sp.draw_rect(RC, color=(0, 0, 0), fill=(0, 0, 0))
    pix = sp.get_pixmap(dpi=150)
    d = fitz.open(); pg = d.new_page(width=842, height=595)
    pg.insert_image(pg.rect, pixmap=pix)
    d.new_page(width=842, height=595)
    d.save(str(pc)); d.close(); src.close()
    k = 150 / 72.0
    box_c = disp({"x0": RC.x0 * k, "y0": RC.y0 * k, "x1": RC.x1 * k, "y1": RC.y1 * k}, 150, 0, None)

    MARKS = {("rot.pdf", 0): [(*box_a, "alpha", "고급")],
             ("split.pdf", 0): [(RT.x0, RT.y0, RT.x1, RT.y1, "top", "초급"), (RB.x0, RB.y0, RB.x1, RB.y1, "bottom")],
             ("scan.pdf", 0): [(*box_c, "gamma")]}
    calls = []

    def resolver(path, page0):
        calls.append((Path(path).name, page0))
        marks = MARKS.get((Path(path).name, page0))
        if not marks:
            return None
        return {"marks": marks, "tips": {m[4]: "<b>%s</b><br>뜻 %s" % (m[4], m[4]) for m in marks}}

    def open_pres(path, vocab=True):
        w = PresentationWindow(str(path), 0, None, vocab=vocab, vocab_resolver=resolver)
        w.resize(1280, 720); w.show(); spin(0.3)
        w._render(); spin(0.2)
        return w

    def dark(img, x, y):
        c = img.pixelColor(int(x), int(y))
        return (c.red() + c.green() + c.blue()) / 3.0 < 80

    def light(img, x, y):
        c = img.pixelColor(int(x), int(y))
        return (c.red() + c.green() + c.blue()) / 3.0 > 180

    def box_of(w, lemma):
        return next((b for b in w._vocab_boxes() if b[1] == lemma), None)

    def check_box(w, lemma, tag):
        b = box_of(w, lemma)
        chk(b is not None, "%s 상자가 화면에 있다" % tag, str([x[1] for x in w._vocab_boxes()]))
        if b is None:
            return None
        r = b[3]
        img = w._label.grab().toImage()
        ins = 3
        inside = [(r.left() + ins, r.top() + ins), (r.right() - ins, r.top() + ins),
                  (r.left() + ins, r.bottom() - ins), (r.right() - ins, r.bottom() - ins),
                  (r.center().x(), r.center().y())]
        out = 5
        outside = [(r.left() - out, r.center().y()), (r.right() + out, r.center().y()),
                   (r.center().x(), r.top() - out), (r.center().x(), r.bottom() + out)]
        chk(all(dark(img, x, y) for x, y in inside), "%s 변환한 상자 안이 실제 검은 칸" % tag, str(r))
        chk(all(light(img, x, y) for x, y in outside), "%s 상자 바로 바깥은 흰 바탕(어긋남 없음)" % tag, str(r))
        # 밑줄이 실제로 그 상자 **바로 아래**에, 그 수준의 색·반투명으로(본문과 같은 vocab_mark_line — 단어장 SOT §11.2)
        from viewer.vocab_marks import vocab_mark_line
        col, (_x0, ly, _x1, _y), lw = vocab_mark_line(r.left(), r.top(), r.right(), r.bottom(), 1.0, b[2])
        a = col.alphaF()
        want = [round(255 + (v - 255) * a) for v in (col.red(), col.green(), col.blue())]   # 흰 종이 위
        full = w.grab().toImage()
        c = full.pixelColor(int(r.center().x()), int(ly))
        chk(ly > r.bottom() and abs(c.red() - want[0]) + abs(c.green() - want[1]) + abs(c.blue() - want[2]) < 60,
            "%s 밑줄이 상자 바로 아래에 수준 색(%s)·반투명으로" % (tag, b[2]), str((c.name(), want, ly, r.bottom())))
        return r

    def hover_tip(w, r, lemma, tag):
        QTest.mouseMove(w, QPoint(int(r.center().x()), int(r.center().y())))
        spin(VOCAB_TIP_DELAY_MS / 1000.0 + 0.3)
        tip = w._vocab_tip
        chk(tip.isVisible() and lemma in tip.text(), "%s 실제 마우스 이동 → 그 단어 뜻 풍선" % tag,
            str((tip.isVisible(), tip.text())))
        g = tip.geometry()
        chk(g.top() >= r.bottom() and g.top() - r.bottom() <= 12 and abs(g.left() - r.left()) <= 1,
            "%s 풍선은 단어 바로 아래" % tag, str((g, r)))

    # A
    w = open_pres(pa)
    r = check_box(w, "alpha", "A")
    if r is not None:
        hover_tip(w, r, "alpha", "A")
        QTest.mouseMove(w, QPoint(int(r.right() + 200), int(r.center().y()))); spin(0.6)
        chk(not w._vocab_tip.isVisible(), "A 단어를 벗어나면 풍선이 숨는다")
        # D — 단어 위 클릭은 넘김(풍선이 클릭을 빼앗지 않음)
        hover_tip(w, r, "alpha", "D0")
        p0 = w._page
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.center().x()), int(r.center().y())))
        spin(0.2)
        chk(w._page == p0 + 1 and not w._vocab_tip.isVisible(), "D 단어 위 클릭 = 다음 쪽, 풍선 숨김", str(w._page))
        QTest.mouseMove(w, QPoint(int(r.center().x()), int(r.center().y()))); spin(0.7)
        chk(not w._vocab_tip.isVisible(), "D 단어 없는 쪽에선 풍선 없음")
    w.close(); spin(0.2)

    # B — 상하 2분할
    w = open_pres(pb)
    chk(w._page_is_split() and w._split_half == 0, "B 준비 세로 쪽은 상하 2분할 상부", str((w._page_is_split(), w._split_half)))
    rt = check_box(w, "top", "B1(상부)")
    chk(box_of(w, "bottom") is None, "B1 상부에선 아래 단어를 긋지 않는다")
    if rt is not None:
        hover_tip(w, rt, "top", "B1")
    w._next(); spin(0.2)
    chk(w._split_half == 1, "B 준비 하부")
    rb = check_box(w, "bottom", "B2(하부)")
    chk(box_of(w, "top") is None, "B2 하부에선 위 단어를 긋지 않는다")
    if rb is not None:
        hover_tip(w, rb, "bottom", "B2")
    # B3 — 좌우 2쪽(왼쪽 칸) + 크롭(왼쪽 10%)
    w._crop_resolver = lambda path, p: (0.0, 0.0, 10.0, 0.0)
    w._pm_cache = {}
    w.set_dual(True); w._page = 0; w._render(); spin(0.2)
    chk(w._dual_mode, "B3 준비 좌우 2쪽")
    rt2 = check_box(w, "top", "B3(2쪽·크롭)")
    chk(box_of(w, "bottom") is not None, "B3 2쪽 보기에선 한 쪽 전체 — 아래 단어도")
    if rt2 is not None:
        hover_tip(w, rt2, "top", "B3")
    w.close(); spin(0.2)

    # C — 스캔 쪽 OCR dpi
    w = open_pres(pc)
    rc = check_box(w, "gamma", "C")
    if rc is not None:
        hover_tip(w, rc, "gamma", "C")
    # C2 — 화면 채움(축마다 다른 배율)
    w.set_fill_screen(True); spin(0.2)
    rc2 = check_box(w, "gamma", "C2(화면 채움)")
    chk(rc is not None and rc2 is not None and abs(rc2.width() / rc2.height() - rc.width() / rc.height()) > 0.05,
        "C2 화면 채움이면 상자 비율도 화면과 함께 바뀐다")
    w.close(); spin(0.2)

    # E — 꺼짐
    calls.clear()
    w = open_pres(pa, vocab=False)
    QTest.mouseMove(w, QPoint(640, 360)); spin(0.6)
    chk(not calls and not w._vocab_boxes() and not w._vocab_tip.isVisible(),
        "E1 꺼져 있으면 공급자를 부르지 않고 아무것도 없다", str(calls))
    got = []
    w.vocabChanged.connect(got.append)
    w._tb_vocab.click(); spin(0.2)
    chk(got == [True] and w._vocab_on and calls and box_of(w, "alpha") is not None,
        "E2 '단어장' 단추로 켜면 vocabChanged·자료를 받아 긋는다", str((got, calls)))
    n = len(calls)
    for x in range(100, 1200, 50):
        QTest.mouseMove(w, QPoint(x, 300))
    spin(0.2)
    chk(len(calls) == n, "E3 마우스 이동 때는 공급자(DB)를 부르지 않는다", str(len(calls) - n))
    w.close(); spin(0.2)

    # F — 실제 연결 길: PresentMixin._presentation_vocab → StudyMixin.vocab_overlay_for(단어장 SOT §11.2) → 발표
    #     (DB 만 대역 — 행·상자·수준·뜻 풍선 글은 단어장 쪽 실제 코드가 만든다)
    from viewer.present_controller import PresentMixin
    from viewer.widgets.study_panel import StudyPanel
    pf = root / "real.pdf"
    d = fitz.open(); pg = d.new_page(width=842, height=595)
    RF = fitz.Rect(300, 260, 420, 290)
    pg.draw_rect(RF, color=(0, 0, 0), fill=(0, 0, 0))
    d.new_page(width=842, height=595)
    d.save(str(pf)); d.close()
    sp = StudyPanel(); sp.resize(420, 600)
    for _lv in ("초급", "중급", "고급", "전문용어"):
        sp._chk[_lv].setChecked(True)
    ROWS = [{"lemma": "pavement", "lang": "eng", "level": "중급", "count": 1, "pos": 0,
             "definitions": [{"definition": "포장도로", "source": "s"}], "examples": []}]

    class FStore:
        def vocab_count(self, fkey): return 1
        def get_page_words(self, fkey, page):
            return [{"surface": "pavement", "x0": RF.x0, "y0": RF.y0, "x1": RF.x1, "y1": RF.y1}] if page == 0 else []
        def get_page_dpi(self, fkey, page): return 0
        def get_page_study(self, fkey, page): return [dict(r) for r in ROWS] if page == 0 else []

    class Host(PresentMixin, StudyMixin):
        def __init__(self):
            self._prefs = {}
            self._study_pdf = pf
            self.study_panel = sp
            self.main_view = None
            self._spot_terms_cache = None
        def _study_get_store(self): return FStore()
        def _apply_word_filter(self, fkey, rs): return rs
        def _enrich_rows_with_dict(self, rs): return rs
        def _accumulate_and_merge_examples(self, rs): return rs
        def _spot_page_terms(self, page): return [], {}

    h = Host()
    w = PresentationWindow(str(pf), 0, None, vocab=True, vocab_resolver=h._presentation_vocab)
    w.resize(1280, 720); w.show(); spin(0.3); w._render(); spin(0.2)
    b = box_of(w, "pavement")
    chk(b is not None and b[2] == "중급", "F 실제 단어장 길 — 상자·수준(중급)이 발표로 온다", str(w._vocab_data))
    rf = check_box(w, "pavement", "F")
    if rf is not None:
        hover_tip(w, rf, "pavement", "F")
        chk("포장도로" in w._vocab_tip.text(), "F 뜻 풍선 글은 단어장 쪽 tip_html 그대로", w._vocab_tip.text()[:120])
    w.close(); spin(0.2)
    chk(h._presentation_vocab(str(root / "other.pdf"), 0) is None, "F 단어장을 보는 PDF 가 아니면 아무것도 없다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
