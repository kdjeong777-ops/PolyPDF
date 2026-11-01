# -*- coding: utf-8 -*-
"""261101-1(검색창 SOT §3.1): 검색은 하이픈도 빈칸처럼 무시한다 — 글자층의 줄 끝 분철(`labora-`/`tory`)을 찾는다.

A. 색인 검색: `laboratory` 가 `labora-\\ntory` 를, `coarse graded`·`coarsegraded`·`coarse-graded` 가 `coarse-\\ngraded` 를 찾는다
B. 본문 강조(`pdf_doc.flat_hits`)도 같은 꼴로 칠한다
C. 스키마 5 색인은 6 으로 올리며 파일마다 다시 색인 표시(size=-1)를 한다 — 옛 글은 그대로 검색된다
"""
import os, sys, tempfile, sqlite3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz

fails = []


def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra if not c else "")
    if not c:
        fails.append(m)


root = Path(tempfile.mkdtemp(prefix="polypdf_hyph_"))
pdf = root / "napa.pdf"
d = fitz.open()
pg = d.new_page()
pg.insert_text((72, 100), "BMD is used to establish whether a labora-", fontname="helv", fontsize=11)
pg.insert_text((72, 114), "tory mixture meets the requirements of coarse-", fontname="helv", fontsize=11)
pg.insert_text((72, 128), "graded asphalt in KS F-2357 tests.", fontname="helv", fontsize=11)
d.save(str(pdf)); d.close()

from viewer.indexer import PdfIndex, flat_text
from viewer import pdf_doc
ix = PdfIndex(root / "index.db")
ix.index_file(pdf)
chk(len(ix.search("laboratory")) == 1, "A1 `laboratory` 가 줄 끝 분철 `labora-`/`tory` 를 찾는다")
for q in ("coarse-graded", "coarse graded", "coarsegraded"):
    chk(len(ix.search(q)) == 1, "A2 `%s` 가 `coarse-`/`graded` 를 찾는다" % q)
chk(len(ix.search("KS F 2357")) == 1 and len(ix.search("KS F-2357")) == 1, "A3 하이픈이 든 기호도 서로 맞는다")
chk(not ix.search("laboratoryx"), "A4 없는 말은 없다")
r = ix.search("laboratory")
chk(bool(r) and "<" in r[0].snippet, "A5 미리보기에 맞은 자리가 칠해진다", r[0].snippet if r else "")
chk(flat_text("a-b\nc­d") == "abcd", "A6 flat_text 는 빈칸·하이픈을 모두 뺀다")
ix.close()

dd = fitz.open(str(pdf))
chk(len(pdf_doc.flat_hits(dd[0], "laboratory")) >= 1, "B1 본문 강조도 `labora-`/`tory` 를 칠한다")
chk(len(pdf_doc.flat_hits(dd[0], "coarse graded")) >= 1, "B2 `coarse graded` 도 칠한다")
dd.close()

old = root / "old.db"
c = sqlite3.connect(old)
c.execute("CREATE TABLE files(id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL, mtime REAL NOT NULL, page_count INTEGER NOT NULL, size INTEGER)")
c.execute("CREATE VIRTUAL TABLE pages2 USING fts5(flat, text UNINDEXED, file_id UNINDEXED, page_index UNINDEXED, tokenize='trigram')")
c.execute("INSERT INTO files(path, mtime, page_count, size) VALUES(?, ?, 1, 123)", (str(pdf), pdf.stat().st_mtime))
c.execute("INSERT INTO pages2(flat, text, file_id, page_index) VALUES(?, ?, 1, 0)", ("옛색인의글coarse-graded", "옛 색인의 글 coarse-graded"))
c.execute("PRAGMA user_version = 5"); c.commit(); c.close()
ix = PdfIndex(old)
sz = ix.conn.execute("SELECT size FROM files").fetchone()[0]
chk(sz == -1, "C1 스키마 5 → 6 에서 파일마다 다시 색인 표시", str(sz))
chk(len(ix.search("옛 색인의 글")) == 1, "C2 다시 색인 전에도 옛 글은 검색된다")
ix.close()

print()
print("FAILED:", len(fails)) if fails else print("ALL PASS")
sys.exit(1 if fails else 0)
