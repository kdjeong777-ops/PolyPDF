# -*- coding: utf-8 -*-
"""261103 사용자 지시 세 가지 — 텍스트 창 SOT §3.7.15·§3.6.3·§5.1.3.

  ① 목차 두 줄(`2. 성격의 5요인 모델 158` + `요약 162`)이 한 줄로 이어졌다 — 한 단계 번호 목차는 목차로 판정되지 않았다
  ② 목차 번호 오독 `A 성격 평가기법 183` → `4. 성격 평가기법 183`(그리고 `1,`·`2 주요`)
  ③ 본문의 초록 줄 상자 끝을 마우스로 끌어 늘리면, 늘린 띠만 읽어 텍스트 창 그 줄에 넣는다

①② 의 줄은 실제 교재(성격심리 11쪽) 글자층에서 뽑은 자리·크기 그대로다. ③ 은 실제 마우스 이벤트(본문 뷰 viewport)
→ 앱 처리기 → 배경 워커(`TextStripOcrWorker`) → 텍스트 창까지 그대로 탄다 — OCR 엔진만 가짜(`ocr_image`)로 바꾼다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint, QPointF
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_toc_stretch_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer import text_extract2 as tx
from viewer.study.ocr_pages import toc_tail_lines

# 성격심리 11쪽(차례) 글자층 — 자리·크기는 실측. `158` 줄의 크기는 뒷줄과 같게(사용자 화면처럼 크기로 갈리지 않는 경우)
TOC = [
    ('4. 성격 평가기법 139', (105.6, 96.3, 199.9, 112.1), 10.87),
    ('5. 성격이론의 적용 142', (105.8, 115.9, 208.7, 126.6), 8.86),
    ('요약 143', (105.8, 134.0, 148.5, 144.3), 9.11),
    ('Review Questions 145', (106.1, 153.0, 202.0, 161.3), 7.74),
    ('성격 연습 7 기질 146', (114.5, 172.1, 221.5, 183.0), 9.56),
    ('제6장 아이젱크의 생물학적 유형론과 성격의 5요인 모델 149', (67.9, 197.4, 343.6, 225.5), 14.65),
    ('1, 아이젱크의 생물학적 유형론 151', (106.1, 224.3, 254.1, 245.2), 12.15),
    ('2. 성격 의 5요인 모델 158', (105.8, 245.7, 217.8, 260.6), 9.23),
    ('요약 162', (105.8, 265.7, 148.5, 276.3), 9.23),
    ('Review Questions 164', (106.1, 284.7, 202.2, 293.3), 7.89),
    ('성격 연습 8 자극 추구 165', (114.5, 303.8, 243.8, 315.0), 9.55),
    ('성격 연습 9 성실성 167', (114.5, 321.8, 230.1, 332.7), 9.46),
    ('제7장 프로이트의 정신분석 171', (68.2, 394.4, 204.4, 415.6), 12.36),
    ('1. 프로이 트 생애 172', (106.3, 420.7, 206.8, 431.6), 9.16),
    ('2 주요 개념 174', (106.1, 438.7, 180.7, 449.9), 9.31),
    ('3. 성격 발달 180', (106.1, 456.7, 182.6, 467.6), 9.17),
    ('A 성격 평가기법 183', (106.1, 471.2, 200.4, 487.0), 10.94),
    ('5. 성격이론의 적용 185', (106.1, 492.5, 209.2, 503.4), 8.99),
    ('요약 187', (106.1, 510.5, 148.5, 520.9), 9.08),
    ('Review Questions 188', (106.3, 529.3, 202.5, 537.9), 7.89),
    ('성격 연습 10 일상생황 속에 묻어 있는 프로이트의 원리 189', (113.0, 547.9, 377.9, 559.1), 9.11),
    ('제8장 아들러의 개인심리학 191', (68.4, 580.1, 206.1, 597.9), 11.38),
    ('1. 아들러 생애 192', (106.3, 605.3, 198.4, 615.9), 9.32),
    ('2. 주요 개념 194', (106.3, 623.1, 182.3, 633.7), 9.02),
    ('3. 성격 평가기법 207', (106.1, 635.8, 201.8, 653.3), 11.54),
]


def rows_of(lines):
    return [{'text': t, 'style': 'body', 'rect': r, 'kind': 'text', 'size': s} for t, r, s in lines]


# ── ① 목차 줄은 잇지 않는다 ─────────────────────────────────────────────
chk(toc_tail_lines([t for t, _r, _s in TOC]), "① 한 단계 번호 목차(쪽 번호로 끝나는 줄)를 목차로 본다")
quest = ["%d 나는 규칙적으로 운동을 한다. | 1 | 2 | 3 | 4 | 5" % i for i in range(16, 40)]
chk(not toc_tail_lines(quest), "① 끝 칸이 숫자인 설문 표는 목차가 아니다")
index = ["청소년기 %d 투사 %d" % (a, b) for a, b in ((138, 179), (29, 153), (89, 554), (412, 39), (220, 18),
                                                   (77, 301), (15, 480), (350, 92), (61, 270), (499, 4))]
chk(not toc_tail_lines(index), "① 쪽 번호가 뒤섞인 찾아보기는 목차가 아니다")
body = ["그는 1952년에 각종 정신장애를 분류하였다.", "이 편람에는 성격장애를 진단하는 준거가 있다.",
        "현재까지 여러 장애가 삭제 혹은 추가되면서 2013년에", "5판까지 출판되었다."] * 3
chk(not toc_tail_lines(body), "① 본문 쪽은 목차가 아니다")
joined = tx.join_sentences(rows_of(TOC))
texts = [r['text'] for r in joined]
chk(len(joined) == len(TOC), "① 목차 쪽은 한 줄도 잇지 않는다", [t for t in texts if t.count(" ") > 8])
chk(any(t.endswith("158") for t in texts) and "요약 162" in texts, "① `…모델 158` 과 `요약 162` 가 따로 있다", texts[6:9])

# ── ② 목차 번호 오독 바로잡기 ────────────────────────────────────────────
fixed = [r['text'] for r in tx.fix_toc_numbers(rows_of(TOC))]
chk("4. 성격 평가기법 183" in fixed, "② `A 성격 평가기법 183` → `4.` (위 `3.`·아래 `5.`)", fixed[16])
chk("1. 아이젱크의 생물학적 유형론 151" in fixed, "② `1,` → `1.` (아래 `2.`)", fixed[6])
chk("2. 주요 개념 174" in fixed, "② `2 주요` → `2.` (위 `1.`·아래 `3.`)", fixed[14])
chk(fixed[5].startswith("제6장") and fixed[3] == "Review Questions 145", "② 번호 줄이 아닌 줄은 그대로")
lone = rows_of([("3. 성격 발달 180", (0, 0, 9, 9), 9), ("요약 182", (0, 10, 9, 19), 9), ("A 성격 평가기법 183", (0, 20, 9, 29), 9)]
               + TOC)
chk(tx.fix_toc_numbers(lone)[2]['text'] == "A 성격 평가기법 183", "② 글자 번호는 위·아래가 둘 다 맞을 때만 고친다")
chk([r['text'] for r in tx.fix_toc_numbers(rows_of([(t, r, s) for t, r, s in TOC[:3]]))][0] == TOC[0][0],
    "② 목차 쪽이 아니면(줄이 적다) 손대지 않는다")

# ── ③ 줄 상자 끌어 늘리기 ─────────────────────────────────────────────
import fitz
from test_fixtures import KRFONT
root = tempfile.mkdtemp(prefix="polypdf_tocstretch_")
src = os.path.join(root, "p.pdf")
d = fitz.open()
pg = d.new_page(width=500, height=700)
kw = dict(fontsize=12, fontfile=KRFONT, fontname="kr") if KRFONT else dict(fontsize=12)
LINES = ["Association) in 1952 published a manual", "Diagnostic and Statistical Manual of Mental",
         "Disorders and many other disorders were", "added and removed until the fifth edition."]
for i, t in enumerate(LINES):
    pg.insert_text((60, 120 + i * 18), t, **kw)
d.save(src); d.close()

from viewer.app import MainWindow
from viewer.history import HistoryItem
from viewer.study import ocr as study_ocr
seen = {}


def fake_ocr(img, lang="eng", psm=0, dpi=300):
    seen["psm"], seen["size"] = psm, getattr(img, "size", None)
    return {"text": "(DSM-I:", "conf": 90, "words": [{"surface": "(DSM-I:", "x0": 2, "y0": 2, "x1": 60, "y1": 30, "conf": 90}]}


_real_ocr = study_ocr.ocr_image
study_ocr.ocr_image = fake_ocr
mw = MainWindow(); mw.resize(1300, 900); mw.show(); app.processEvents()
try:
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); app.processEvents(); QTest.qWait(200)
    m = mw.main_view
    tp = mw.text_panel
    # 텍스트 창에 이은 줄 하나(원래 줄 넷) — 실제 추출로
    rows = tx.page_lines(m._doc.doc, src, 0, tables="off")
    joined_row = max(rows, key=lambda r: len(r.get('rects') or []))
    chk(len(joined_row.get('line_texts') or []) == len(joined_row.get('rects') or []) >= 2,
        "③ 이은 줄은 원래 줄마다의 글(`line_texts`)을 상자 수만큼 가진다", (joined_row.get('line_texts'), joined_row.get('rects')))
    tp.set_page(src, 0, rows)
    li = rows.index(joined_row)
    blk = tp.edit.document().findBlockByNumber(li)
    from PyQt6.QtGui import QTextCursor
    tp.edit.setTextCursor(QTextCursor(blk)); tp._on_cursor(); app.processEvents()   # 같은 자리면 커서 신호가 안 난다
    chk(m._word_hl_src == "text_panel" and m._word_hl_groups, "③ 텍스트 창 줄을 고르면 본문에 초록 상자가 걸린다")
    rect0 = tuple(m._word_hl_groups[0][0][0])
    z = m._zoom
    vp = m.view.viewport()

    def vpt(x_pt, y_pt):
        p = m.view.mapFromScene(QPointF(x_pt * z, y_pt * z))
        return QPoint(p.x(), p.y())
    ymid = (rect0[1] + rect0[3]) / 2
    got = []
    m.panelRectStretched.connect(lambda p, o, n: got.append((p, o, n)))
    QTest.mouseMove(vp, vpt(rect0[2], ymid)); app.processEvents()
    chk(vp.cursor().shape() == Qt.CursorShape.SizeHorCursor, "③ 상자 오른 끝 위에서 좌우 늘리기 포인터")
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vpt(rect0[2], ymid))
    QTest.mouseMove(vp, vpt(rect0[2] + 60, ymid)); app.processEvents()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vpt(rect0[2] + 60, ymid))
    app.processEvents()
    chk(len(got) == 1 and got[0][2][2] > rect0[2] + 50 and abs(got[0][2][0] - rect0[0]) < 0.5,
        "③ 끌어 놓으면 늘린 상자를 알린다(오른쪽만 늘었다)", got)
    chk(not (m._sel_text or "").strip(), "③ 상자 끝을 끌 때는 글 고르기가 시작되지 않는다", m._sel_text)
    for _ in range(60):
        app.processEvents(); QTest.qWait(50)
        if "(DSM-I:" in (tp.rows()[li].get("text") or ""):
            break
    t_new = tp.rows()[li].get("text") or ""
    first, second = (joined_row.get('line_texts') or ["", ""])[:2]
    chk(seen.get("psm") == 7, "③ 늘린 띠만 한 줄로 읽는다(psm 7)", seen)
    chk("manual (DSM-I: Diagnostic" in t_new.replace("  ", " "),
        "③ 읽은 글은 그 상자(첫 줄) 끝 — 다음 줄 글 앞에 들어간다", t_new)
    chk(tp.edit.document().findBlockByNumber(li).text() == t_new, "③ 텍스트 창 화면에도 들어갔다")
    rr = tp.rows()[li].get("rects")[0]
    chk(rr[2] > rect0[2] + 50, "③ 그 줄의 상자 자리도 늘린 대로", rr)
    # 왼쪽으로 늘리면 그 상자 글 앞에
    tp.edit.setTextCursor(QTextCursor(tp.edit.document().findBlockByNumber(li))); tp._on_cursor(); app.processEvents()
    r2 = tuple(m._word_hl_groups[0][0][1])
    ym2 = (r2[1] + r2[3]) / 2
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vpt(r2[0], ym2))
    QTest.mouseMove(vp, vpt(r2[0] - 30, ym2)); app.processEvents()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vpt(r2[0] - 30, ym2))
    for _ in range(60):
        app.processEvents(); QTest.qWait(50)
        if (tp.rows()[li].get("text") or "").count("(DSM-I:") >= 2:
            break
    t2 = tp.rows()[li].get("text") or ""
    chk("(DSM-I: (DSM-I:Diagnostic" in t2 or "(DSM-I: (DSM-I: Diagnostic" in t2,
        "③ 왼쪽으로 늘리면 그 상자(둘째 줄) 글 앞에 들어간다", t2)
finally:
    study_ocr.ocr_image = _real_ocr
    mw._skip_save_on_close = True
    mw.close()
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
