# -*- coding: utf-8 -*-
"""261014-12: 표 찾기가 예외로 끝나면 '표 없음' 을 남기지 않는다 (텍스트 창 SOT §3 규칙 6).

공유 pdfplumber 핸들은 다른 스레드의 `close_cache()` 로 언제든 닫힌다. 그때 배경 워커의 표 찾기가 예외를 냈는데,
종전에는 그것을 `[]` 로 바꿔 메모리 캐시와 index.db `page_tables` 에 **영구 저장**했다 — 파일이 바뀌기 전까지 표가 사라졌다
(형식 변환 시험에서 드러남). 실제 함수로:
A. 닫힌 핸들로 물으면 빈 목록을 주되
B. 다음에 다시 물으면 표가 나온다(메모리 캐시에 '없음' 이 남지 않았다)
C. index.db 에도 '없음' 이 저장되지 않았다
"""
import os, sys, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_tcache_"))
try:
    p = root / "T.pdf"
    d = fitz.open(); pg = d.new_page(width=595, height=842)
    x0, y0, cw, rh = 72, 160, 140, 24
    for r in range(4):
        pg.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
    for c in range(4):
        pg.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + 3 * rh))
    for r in range(3):
        for c in range(3):
            pg.insert_text((x0 + c * cw + 6, y0 + r * rh + 16), f"R{r}C{c}", fontsize=10)
    d.save(str(p)); d.close()

    from viewer import text_extract2 as tx
    from viewer.indexer import PdfIndex
    db = root / "index.db"
    PdfIndex(str(db)).close()                     # 스키마를 만든다
    tx.set_table_cache_db(str(db))
    tx.close_cache()

    import pdfplumber
    broken = pdfplumber.open(str(p)); broken.close()      # 다른 스레드가 닫은 핸들과 같은 상태
    got = tx._tables(str(p), 0, plumber=broken)
    chk(got == [], "A 닫힌 핸들로 물으면 빈 목록(예외를 앱에 올리지 않는다)", str(got))
    again = tx._tables(str(p), 0)
    chk(len(again) == 1 and again[0][1][0][0] == "R0C0", "B 다시 물으면 표가 나온다(메모리 캐시에 '없음' 이 안 남음)", str(again)[:80])
    tx.close_cache()                              # 메모리 캐시를 비우고 DB 만 본다
    st = os.stat(str(p))
    ix = PdfIndex(str(db))
    try:
        stored = ix.tables_get(str(p), 0, int(st.st_size), float(st.st_mtime))
    finally:
        ix.close()
    chk(stored is not None and len(stored) == 1, "C index.db 에는 실제 표가 저장됐다('없음' 이 아니다)", str(stored)[:80])
finally:
    try:
        from viewer import text_extract2 as _tx
        _tx.close_cache(); _tx.set_table_cache_db(None)
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
