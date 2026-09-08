# -*- coding: utf-8 -*-
"""260908-5: 속도·안정성 개선 3건의 회귀 검사 (응답성 SOT §4 ⑦·§4.5).

사용자 보고(260908): "실행이나 사용 중 응답없음이나 느리게 동작하지 않는지" 검토 요청.
실측 결과 '한 번의 정지' 는 1초 밑이었으나, 첫 인덱싱 100초 동안 UI 하트비트가 기대의
**47%** 밖에 울리지 않았다 — 멈추지는 않아도 내내 굼떴다.

검사 대상
  ① 표 인식 결과가 `index.db(page_tables)` 에 남고, 다음 실행에서 그대로 쓰인다
  ② 파일이 바뀌면(크기·수정시각) 그 캐시는 무효다 — 재인덱싱 판정과 같은 기준
  ③ 캐시가 맞으면 **pdfplumber 를 아예 열지 않는다**(값을 헛되이 치르지 않는다)
  ④ DB 경로가 없어도 동작한다(캐시는 있으면 좋은 것, 없으면 그냥 계산)
  ⑤ 인덱싱이 도는 동안에는 표를 새로 파지 않는다(`cached_only`, 의무 ①)
  ⑥ `Pacer` 가 '일한 시간에 비례해' 쉰다 — 간격이 아니라 점유율(의무 ⑦)
  ⑦ `YIELD_S = 0` 이면 쉬지 않는다(검사에서 몰아 돌리던 관례 유지)
  ⑧ 반복형 워커가 모두 `pacing.pace` 를 쓴다 — `time.sleep(self.YIELD_S)` 잔존 금지
  ⑨ 태그 키는 **바이트까지 종전과 같다**(태그 SOT §6.1 불변식) — 심볼릭 링크 포함
"""
import os, sys, time, tempfile, shutil, sqlite3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


import test_fixtures as _fx
from viewer.indexer import PdfIndex
from viewer import text_extract2 as tx
from viewer import pacing

root = Path(tempfile.mkdtemp(prefix="polypdf_perf_"))
db = root / "index.db"
src = Path(_fx.text_pdf())
pdf = root / "a.pdf"
shutil.copy2(str(src), str(pdf))

try:
    import fitz
    doc = fitz.open(str(pdf))

    # ── ① 표 인식 결과가 DB 에 남는다 ─────────────────────────────────
    tx.close_cache()
    tx.set_table_cache_db(str(db))
    first = tx._tables(str(pdf), 0)
    tx.close_cache()                      # 메모리 캐시를 비워 'DB 만 남은' 상태로
    again = tx._tables(str(pdf), 0)
    chk(again == first, "① 다시 부르면 DB 에 남은 것과 같은 결과")
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM page_tables").fetchone()[0]
    finally:
        con.close()
    chk(n >= 1, "① page_tables 에 행이 남는다", f"{n}행")

    # ── ② 파일이 바뀌면 무효 ─────────────────────────────────────────
    st = pdf.stat()
    ix = PdfIndex(str(db))
    try:
        chk(ix.tables_get(str(pdf), 0, st.st_size, st.st_mtime) is not None,
            "② 크기·수정시각이 같으면 유효")
        chk(ix.tables_get(str(pdf), 0, st.st_size + 1, st.st_mtime) is None,
            "② 크기가 다르면 무효")
        chk(ix.tables_get(str(pdf), 0, st.st_size, st.st_mtime + 5) is None,
            "② 수정시각이 다르면 무효")
    finally:
        ix.close()

    # ── ③ 캐시가 맞으면 pdfplumber 를 열지 않는다 ─────────────────────
    tx.close_cache()
    tx.set_table_cache_db(str(db))
    opened = {"n": 0}
    _orig_plumber = tx._plumber

    def _spy(p):
        opened["n"] += 1
        return _orig_plumber(p)

    tx._plumber = _spy
    try:
        tx._tables(str(pdf), 0)
        chk(opened["n"] == 0, "③ DB 적중이면 pdfplumber 를 열지 않는다", f"{opened['n']}회")
        tx.close_cache()
        tx._tables(str(pdf), 1)                       # 캐시에 없는 쪽
        chk(opened["n"] == 1, "③ 캐시에 없으면 그때 연다", f"{opened['n']}회")

        # ── ⑤ 인덱싱 중에는 새로 파지 않는다 ──────────────────────────
        tx.close_cache()
        before = opened["n"]
        got = tx._tables(str(pdf), 2, cached_only=True)
        chk(opened["n"] == before, "⑤ cached_only 면 pdfplumber 를 열지 않는다")
        chk(got == [], "⑤ cached_only 로 못 얻으면 빈 목록")
        got2 = tx._tables(str(pdf), 2)                # 미룬 것은 다음에 제대로 판다
        chk(opened["n"] == before + 1, "⑤ 미룬 것은 다음 호출에서 제대로 판다")
    finally:
        tx._plumber = _orig_plumber

    # ── ④ DB 경로가 없어도 동작한다 ──────────────────────────────────
    tx.close_cache()
    tx.set_table_cache_db(None)
    chk(isinstance(tx._tables(str(pdf), 0), list), "④ db 경로가 없어도 표 인식은 동작")
    chk(isinstance(tx.page_lines(doc, str(pdf), 0), list), "④ page_lines 도 동작")
    tx.set_table_cache_db(str(root / "없는폴더" / "index.db"))
    chk(isinstance(tx._tables(str(pdf), 0), list), "④ db 를 못 열어도 오류로 번지지 않는다")
    tx.close_cache()
    tx.set_table_cache_db(None)
    doc.close()

    # ── ⑥⑦ Pacer — 간격이 아니라 점유율 ─────────────────────────────
    p = pacing.Pacer(duty=0.5, min_s=0.0, max_s=1.0)
    time.sleep(0.10)                                  # '일한' 시간
    rest = p.tick()
    chk(0.06 <= rest <= 0.16, "⑥ 0.1초 일했으면 duty=0.5 에서 0.1초쯤 쉰다", f"{rest*1000:.0f}ms")
    p2 = pacing.Pacer(duty=0.8, min_s=0.0, max_s=1.0)
    time.sleep(0.10)
    rest2 = p2.tick()
    chk(rest2 < rest, "⑥ duty 가 높을수록 덜 쉰다", f"{rest2*1000:.0f}ms < {rest*1000:.0f}ms")
    p3 = pacing.Pacer(duty=0.1, min_s=0.0, max_s=0.05)
    time.sleep(0.10)
    chk(p3.tick() <= 0.06, "⑥ max_s 를 넘겨 쉬지 않는다")

    class _Fast:
        YIELD_S = 0

    class _Slow:
        YIELD_S = 0.005

    t0 = time.monotonic()
    for _ in range(20):
        pacing.pace(_Fast())
    chk(time.monotonic() - t0 < 0.05, "⑦ YIELD_S=0 이면 쉬지 않는다")
    o = _Slow()
    pacing.pace(o)
    chk(getattr(o, "_pacer", None) is not None, "⑦ 인스턴스마다 박자를 하나 붙인다")

    # ── ⑧ 반복형 워커가 모두 pacing 을 쓴다 ──────────────────────────
    for name in ("viewer/workers.py", "viewer/indexer.py"):
        txt = Path(name).read_text(encoding="utf-8")
        chk("time.sleep(self.YIELD_S)" not in txt,
            f"⑧ {os.path.basename(name)} 에 직접 sleep 이 남아 있지 않다")
    wk = Path("viewer/workers.py").read_text(encoding="utf-8")
    chk(wk.count("_pacing.pace(self)") >= 4, "⑧ 반복형 워커 4곳이 pace 를 쓴다",
        f"{wk.count('_pacing.pace(self)')}곳")
    ixs = Path("viewer/indexer.py").read_text(encoding="utf-8")
    chk(ixs.count("self._pace()") >= 3, "⑧ 인덱서는 파일·쪽묶음·쓰기 뒤에 pace",
        f"{ixs.count('self._pace()')}곳")

    # ── ⑨ 태그 키 불변식 ────────────────────────────────────────────
    from viewer import tag_store
    sub = root / "태그" / "하위"
    sub.mkdir(parents=True, exist_ok=True)
    f1 = sub / "문서 A.pdf"
    f1.write_bytes(b"%PDF-1.4\n")
    want = str(Path(str(f1)).resolve()).lower()
    chk(tag_store._tag_key(str(f1)) == want, "⑨ 키가 종전(전체 resolve)과 바이트까지 같다")
    chk(tag_store._tag_key(str(f1).upper()) == want, "⑨ 대소문자가 달라도 같은 키")
    chk(tag_store._tag_key(str(sub) + os.sep + "." + os.sep + f1.name) == want,
        "⑨ '.' 이 낀 경로도 같은 키")
    t0 = time.monotonic()
    for i in range(300):
        tag_store._tag_key(str(sub / f"문서{i}.pdf"))
    el = (time.monotonic() - t0) * 1000
    chk(el < 60, "⑨ 300건이 60ms 안에 (부모 디렉터리 조회를 나눠 쓴다)", f"{el:.1f}ms")

finally:
    try:
        tx.close_cache()
        tx.set_table_cache_db(None)
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
