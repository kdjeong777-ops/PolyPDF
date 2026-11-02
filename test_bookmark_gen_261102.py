# -*- coding: utf-8 -*-
"""261102-3(사용자 지시) 책갈피 자동 생성 — 목차 쪽은 '목차' 하나, 목차가 있으면 목차 항목만 (마스터 §4.4.3 T1·T2).

A. 목차 쪽 줄은 책갈피가 되지 않고 목차 첫 쪽에 '목차'(화면 언어) 하나 — 검토 표 길·검토 없는 길
B. 목차가 있으면 목차에 없는 본문 번호 제목(`8 Measurement`)은 넣지 않는다 — `bookmark_gen.generate`(동시 생성·병합이 쓰는 길)
C. 헤딩 길에서도 목차 쪽 위 헤딩은 버린다(drop_toc_pages)
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_bm261102_"))
from viewer.study import study_store as ss
ss.enable_pending(True, root / "pend.db")
from viewer.i18n import tr

# 1쪽 표지, 2쪽 목차, 3쪽부터 본문(인쇄 쪽 1, 2, …). 5쪽 본문에 목차에 없는 번호 줄 '8 Measurement'
pdf = root / "report.pdf"
d = fitz.open()
d.new_page().insert_text((72, 300), "Test Report", fontsize=24)
pg = d.new_page()
pg.insert_text((72, 72), "Contents", fontsize=18)
for i, (t, p) in enumerate([("1. Introduction", 1), ("2. Methods", 3), ("3. Results", 5), ("4. Summary", 7)]):
    pg.insert_text((72, 120 + 24 * i), f"{t} ........................ {p}", fontsize=11)
for b in range(1, 11):
    pg = d.new_page()
    pg.insert_text((520, 30), str(b), fontsize=9)                 # 머리말 쪽 번호
    heads = {1: "1. Introduction", 3: "2. Methods", 5: "3. Results", 7: "4. Summary"}
    if b in heads:
        pg.insert_text((72, 100), heads[b], fontsize=18)
    if b == 3:
        pg.insert_text((72, 400), "8 Measurement", fontsize=18)   # 목차에 없는 본문 번호 제목
    pg.insert_text((72, 200), f"Body text on printed page {b}.", fontsize=11)
d.save(pdf); d.close()
EXPECT = [(tr("목차"), 2, 0), ("1. Introduction", 3, 1), ("2. Methods", 5, 1), ("3. Results", 7, 1), ("4. Summary", 9, 1)]

# ── A. 검토 없는 길·검토 표 길 ─────────────────────────────────────────
from viewer.workers import BookmarkerWorker
def run_worker(opts):
    w = BookmarkerWorker(pdf, opts)
    out = {}
    w.finished.connect(lambda r: out.update(r=r)); w.error.connect(lambda e: out.update(err=e))
    w.run()
    return out
res = run_worker({"mode": "auto", "review": False})
bms = [(t, p) for t, p, _l in (res.get("r") or {}).get("bookmarks") or []]
chk(bms[:1] == [(tr("목차"), 2)], "A1 목차 첫 쪽에 '목차' 하나(검토 없는 길)", f"{bms} {res.get('err')}")
chk(not [b for b in bms[1:] if b[1] == 2], "A2 목차 쪽 줄은 책갈피가 아니다", str(bms))
chk(bms == [(t, p) for t, p, _l in EXPECT], "A3 목차 항목을 실제 쪽에", str(bms))
res = run_worker({"mode": "auto", "review": True})
rows = (res.get("r") or {}).get("rows") or []
chk(rows and rows[0]["title"] == tr("목차") and rows[0]["page"] == 2 and rows[0].get("manual"),
    "A4 검토 표 첫 행 = '목차'(수동, 오프셋을 다시 적용해도 그대로)", str(rows[:2]))

# ── B. 동시 생성·병합이 쓰는 길 ────────────────────────────────────────
try:
    from viewer import bookmark_gen
    got = [(t, p) for t, p, _l in bookmark_gen.generate(pdf)]
except Exception as e:
    got = [f"error {e!r}"]
chk(got == [(t, p) for t, p, _l in EXPECT], "B1 목차가 있으면 목차 항목만(본문 '8 Measurement' 없음) + '목차'", str(got))
chk(not any("Measurement" in str(t) for t, *_ in got), "B2 목차에 없는 본문 제목은 넣지 않는다")

# ── C. 헤딩 길의 목차 쪽 ───────────────────────────────────────────────
try:
    kept = bookmark_gen.drop_toc_pages([("1.1 A", 4, 1), ("1.1 A", 12, 1), ("8 B", 37, 0)], [4, 5, 6])
except Exception as e:
    kept = [f"error {e!r}"]
chk(kept == [("1.1 A", 12, 1), ("8 B", 37, 0)], "C1 목차 쪽(4~6)을 가리키는 헤딩은 버린다", str(kept))

# ── D. 번호 모양대로 하위 책갈피(사용자 추가 지시) — 헤딩 길 ─────────────
from viewer.study.ocr_headings import _bookmarks_from_page_lines
def line(text, y, h=20.0):
    ws, x = [], 50.0
    for t in text.split():
        ws.append({"surface": t, "x0": x, "y0": y, "x1": x + 12 * len(t), "y1": y + h}); x += 12 * len(t) + 8
    return {"text": text, "h": h, "x0": 50.0, "y0": y, "words": ws}
body = [line(f"본문 줄 {k} 글자가 이어진다 여기에", 300 + 22 * k, 14.0) for k in range(8)]
seq = [(1, "1. 서론"), (2, "1.1 연구 배경"), (3, "2. 포장 일반"), (4, "2.1 포장설계"), (5, "2.1.1 개요"),
       (6, "8 계측"), (7, "2.1.2 도로시험"), (9, "45.2 배합설계"), (10, "4.5.3 시험시공"), (11, "5. 사후관측")]
page_lines = {p - 1: [line(t, 100)] + body for p, t in seq}
got = [(b.title, b.page, b.level) for b in _bookmarks_from_page_lines(page_lines, use_font_auto=False)]
lv = {t.split()[0]: l for t, _p, l in got}
chk(lv.get("1.") == 0 and lv.get("1.1") == 1 and lv.get("2.1.1") == 2 and lv.get("5.") == 0,
    "D1 1 / 1.1 / 1.1.1 → 단계 0 / 1 / 2", str(got))
chk(("4.5.2 배합설계", 9, 2) in got, "D2 '45.2' 는 뒤 번호 4.5.3 을 보고 4.5.2(단계 2)로", str(got))
chk(not any("계측" in t for t, _p, _l in got) and ("2.1.2 도로시험", 7, 2) in got,
    "D3 번호 순서에 끼어든 줄('8 계측' — 2.1.1 과 2.1.2 사이)은 버린다", str(got))

from viewer.study.ocr_headings import numbered_level
nl = lambda t: numbered_level(t, 20, 14)
chk(nl("2.1.1개요") == 2 and nl("1.서론") == 0 and nl("1.1 연구 배경") == 1,
    "D4 번호 뒤 빈칸을 OCR 이 먹어도 제목(2.1.1개요·1.서론)", str([nl("2.1.1개요"), nl("1.서론")]))
chk(nl("3개월 후 측정") is None and nl("2019년 조사") is None
    and nl("4.5.2 배합설계 및 시험 결과를 정리하면 다음과 같다.") is None,
    "D5 숫자로 시작해도 번호 제목이 아니거나 뒤 문장이 길면 아니다")

print()
print("ALL PASS" if not fails else f"FAILED {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
