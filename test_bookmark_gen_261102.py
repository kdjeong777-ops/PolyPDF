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

print()
print("ALL PASS" if not fails else f"FAILED {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
