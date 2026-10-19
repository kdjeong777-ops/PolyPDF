# -*- coding: utf-8 -*-
"""261019-4(검색창 SOT §3.1·§3.2·§4·§8): 검색은 빈칸·줄바꿈을 무시하고, 스캔 쪽은 저장한 우리 OCR 을 색인한다.

A. 줄을 건너는 구('asphalt\\npavement')·띄어쓰기가 다른 질의('아스팔트포장' ↔ '아스팔트 포장')를 찾는다
B. 스캔 쪽(글자층 없음)은 study.db 의 저장한 OCR 글로 찾는다 — 보류(저장 전) OCR 은 색인하지 않는다
C. 옛 색인(pages_fts)은 지우지 않고 그대로 검색되며, 다시 색인되도록 표시된다(size=-1)
D. 본문 강조: 빈칸이 다른 질의도 칠하고, 스캔 쪽은 OCR 낱말로 칠한다
"""
import os, sys, tempfile, sqlite3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

root = Path(tempfile.mkdtemp(prefix="polypdf_flat_"))
txt_pdf = root / "text.pdf"
d = fitz.open()
pg = d.new_page()
pg.insert_text((72, 100), "The road uses asphalt", fontname="helv", fontsize=11)
pg.insert_text((72, 114), "pavement layers today.", fontname="helv", fontsize=11)
pg.insert_text((72, 140), "아스팔트 포장 공사", fontname="korea", fontsize=11)
d.new_page().insert_text((72, 100), "nothing here", fontname="helv")
d.save(str(txt_pdf)); d.close()

import test_fixtures as _fx
scan_src = Path(_fx.scanned_pdf())
scan_pdf = root / "scan.pdf"
import shutil
shutil.copy(scan_src, scan_pdf)

from viewer.indexer import PdfIndex, flat_text
from viewer.study import study_store as ss
db = root / "index.db"
# B 준비: 같은 폴더의 study.db 에 저장한 OCR(1쪽)과 보류만 된 OCR(2쪽, 다른 파일 db 라 main 에 없음)
st = ss.StudyStore(root / "study.db")
st.save_page(ss.file_key_for(str(scan_pdf)), 0, "스캔본 우리 OCR 글 시방서", dpi=300, engine="t", source="ocr", conf=1,
             words=[{"surface": "스캔본", "x0": 300, "y0": 300, "x1": 600, "y1": 360},
                    {"surface": "우리", "x0": 640, "y0": 300, "x1": 760, "y1": 360}], lang="kor")
st.close()

ix = PdfIndex(db)
ix.index_file(txt_pdf)
ix.index_file(scan_pdf)
r1 = ix.search("asphalt pavement")
chk(len(r1) == 1 and r1[0].page_index == 0 and "<" in r1[0].snippet, "A1 줄을 건너는 구를 찾는다", f"{[(r.page_index, r.snippet) for r in r1]}")
r2 = ix.search("아스팔트포장")
chk(len(r2) == 1 and r2[0].page_index == 0, "A2 질의에 빈칸이 없어도 '아스팔트 포장' 을 찾는다", f"{len(r2)}")
r3 = ix.search("아스팔트   포장   공사")
chk(len(r3) == 1, "A3 질의 빈칸이 많아도 같다")
chk(not ix.search("asphaltx"), "A4 없는 말은 없다")
r4 = ix.search("우리OCR")
chk(len(r4) == 1 and Path(r4[0].file_path).name == "scan.pdf" and r4[0].page_index == 0,
    "B1 스캔 쪽은 저장한 우리 OCR 글로 찾는다", f"{[(r.file_name, r.page_index) for r in r4]}")
chk(flat_text("a b\nc\td") == "abcd", "A5 flat_text 는 모든 빈칸을 뺀다")
ix.close()

# C. 옛 색인 — pages_fts 에만 있는 파일도 검색되고, 다시 색인 표시가 붙는다
old = root / "old.db"
c = sqlite3.connect(old)
c.execute("CREATE TABLE files(id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL, mtime REAL NOT NULL, page_count INTEGER NOT NULL, size INTEGER)")
c.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(text, file_id UNINDEXED, page_index UNINDEXED, tokenize='trigram')")
c.execute("INSERT INTO files(path, mtime, page_count, size) VALUES(?, ?, 1, 123)", (str(txt_pdf), txt_pdf.stat().st_mtime))
c.execute("INSERT INTO pages_fts(text, file_id, page_index) VALUES(?, 1, 0)", ("옛 색인의 글\n줄바꿈",))
c.execute("PRAGMA user_version = 4"); c.commit(); c.close()
ix2 = PdfIndex(old)
r5 = ix2.search("옛 색인")
size = ix2.conn.execute("SELECT size FROM files").fetchone()[0]
chk(len(r5) == 1 and size == -1 and ix2.needs_reindex(txt_pdf), "C1 옛 색인은 그대로 검색되고 다시 색인 표시(size=-1)", f"{len(r5)} size={size}")
ix2.index_file(txt_pdf)
chk(ix2.conn.execute("SELECT count(*) FROM pages_fts").fetchone()[0] == 0 and len(ix2.search("asphalt pavement")) == 1,
    "C2 다시 색인하면 새 표로 옮겨 간다")
ix2.close()

# D. 본문 강조
from viewer.pdf_doc import page_hits
d = fitz.open(str(txt_pdf))
h1 = page_hits(d[0], "아스팔트포장")
h2 = page_hits(d[0], "asphalt pavement")
chk(len(h1) >= 1, "D1 빈칸이 다른 질의도 칠한다", f"{h1}")
chk(len(h2) >= 1, "D2 줄을 건너는 구도 칠한다(줄마다)", f"{h2}")
d.close()
d = fitz.open(str(scan_pdf))
ocr = lambda: ([{"surface": "스캔본", "x0": 300, "y0": 300, "x1": 600, "y1": 360},
                {"surface": "우리", "x0": 640, "y0": 300, "x1": 760, "y1": 360}], 300)
h3 = page_hits(d[0], "스캔본 우리", ocr=ocr)
chk(len(h3) == 1 and abs(h3[0].x0 - 72.0) < 0.5 and abs(h3[0].x1 - 182.4) < 0.5,
    "D3 스캔 쪽은 OCR 낱말 자리로 칠한다(pt 로 바꿈)", f"{h3}")
d.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
