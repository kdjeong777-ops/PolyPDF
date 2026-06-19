# -*- coding: utf-8 -*-
"""새로 만든/편집한 PDF가 검색 인덱스에 포함되는지 검증."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()
check("_index_single_file 메서드", callable(getattr(mw, "_index_single_file", None)))

# 텍스트가 든 임시 PDF 생성
import fitz
tmpdir = tempfile.mkdtemp()
pdf = os.path.join(tmpdir, "newbm_bookmarked.pdf")
TOKEN = "zqxwpolypdfunique"
doc = fitz.open()
pg = doc.new_page()
pg.insert_text((72, 72), f"{TOKEN} sample text for indexing")
doc.save(pdf)
doc.close()

# _index_single_file 이 쓰는 워커를 동기 실행(스레드 플레이크 회피)
from viewer.workers import IndexWorker
from pathlib import Path
w = IndexWorker(mw._db_path, Path(pdf).parent, single_file=Path(pdf))
w.run()

# 인덱스에서 검색 → 새 파일이 결과에 포함
from viewer.indexer import PdfIndex
idx = PdfIndex(mw._db_path)
try:
    res = idx.search(TOKEN)
finally:
    idx.close()
want = os.path.normcase(os.path.abspath(pdf))
hit = any(os.path.normcase(os.path.abspath(str(r.file_path))) == want for r in (res or []))
check("새 PDF가 검색에 포함", bool(res) and hit,
      f"n={len(res) if res else 0} files={[Path(r.file_path).name for r in (res or [])]}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
