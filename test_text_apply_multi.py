# -*- coding: utf-8 -*-
"""260913-4: 'PDF 에 반영' 이 실제로 들어가게 (텍스트 창 SOT §5.1.3·§5.2·§5.2.1).

사용자 보고·지시
  ① "텍스트창을 수정 후 'pdf에 반영'을 했는데, 반영이 실제 안되. 다른 페이지 갔다가
     다시 돌아가면 그대로야. (줄나누기를 합쳤는데, 기존 그대로임)"
  ② "편집모드가 아니면 편집모드 상태로 변경 후 저장한다고 메시지창 넣고 수정해"
  ③ "여러 페이지에 걸쳐 수정 후 'pdf에 반영'하면 모든 페이지의 수정 내용이 본문에 반영"

원인은 셋이었다 — 표 찾기 핸들이 원본을 잠가 `_edited.pdf` 로 빠졌고(A), 합친 줄이
다시 열면 되맞춤에 실패해 풀렸고(B), 반영은 지금 쪽만 했다(C). **결과를 센다** —
PDF 의 글·파일 크기·쪽 번호·편집모드 상태를 실제로 확인한다.
"""
import os, sys, gc, time, threading, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer import text_extract2 as tx
from viewer import text_fix_store as tfs
from viewer.text_apply import apply_fixes_by_page

root = Path(tempfile.mkdtemp(prefix="polypdf_apply_multi_"))
KRFONT = r"C:\Windows\Fonts\malgun.ttf"
# 사용자 설정 폴더의 text_fix.json 을 건드리지 않는다
tfs._SINGLETON = tfs.TextFixStore(root / "text_fix.json")
STORE = tfs._SINGLETON

LINES = ("alpha first line", "bravo second line", "charlie third line", "delta fourth line")


def scan_pdf(dst, pages=3):
    """그림 위에 **보이지 않는** 글자층을 얹은 쪽들 — 스캔본과 같은 모양."""
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        for i, t in enumerate(LINES):
            # 짧은 줄 — §3.7 이 잇지 않는다(오른쪽까지 차지 않음)
            page.insert_text((60, 140 + i * 60), "%s p%d" % (t, p + 1), fontsize=14,
                             render_mode=3)
    doc.save(str(dst))
    doc.close()
    return dst


try:
    # ── A. 표 찾기 핸들이 원본을 잠그지 않는다 ───────────────────────────
    src = scan_pdf(root / "lock.pdf", pages=1)
    import pdfplumber
    opened = []
    real_open = pdfplumber.open

    def slow_open(path, *a, **k):
        time.sleep(0.2)                  # 두 스레드가 확실히 겹치게
        h = real_open(path, *a, **k)
        opened.append(h)
        return h

    tx.close_cache()
    pdfplumber.open = slow_open
    try:
        ths = [threading.Thread(target=tx._plumber, args=(str(src),)) for _ in range(2)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
    finally:
        pdfplumber.open = real_open
    chk(len(opened) == 1, "A 두 스레드가 동시에 열어도 **한 번만** 연다", "%d번" % len(opened))
    gc.disable()                         # 가비지 수집이 대신 풀어 주지 못하게
    try:
        tx.close_cache()
        chk(all(h.stream.closed for h in opened), "A close_cache 가 연 핸들을 **모두** 닫는다")
        probe = root / "lock_probe.pdf"
        shutil.copy2(str(src), str(probe))
        try:
            os.replace(str(probe), str(src))
            ok = True
        except Exception as e:           # noqa: BLE001
            ok = False
        chk(ok, "A 닫은 뒤 원본을 덮어쓸 수 있다(가비지 수집 없이)")
    finally:
        gc.enable()

    # ── B. 고침은 자리로 얹는다 — 합친 줄이 다시 열어도 합쳐져 있다 ─────────
    s1 = scan_pdf(root / "merge.pdf", pages=1)
    d = fitz.open(str(s1))
    rows = tx.page_lines(d, str(s1), 0, tables="off", join_lines=False)
    d.close()
    chk(len(rows) == 4, "B 준비 — 4줄", str([r["text"] for r in rows]))
    ra, rb = rows[0]["rect"], rows[1]["rect"]
    union = (min(ra[0], rb[0]), ra[1], max(ra[2], rb[2]), rb[3])
    merged = rows[0]["text"] + " " + rows[1]["text"]
    STORE.set_fix(str(s1), 0, 0, merged, merged, union, [ra, rb])
    got = STORE.apply_to_rows(str(s1), 0, rows)
    chk(len(got) == 3 and got[0]["text"] == merged,
        "B **합친 줄은 다시 합친다** — 두 줄이 한 줄로(종전 remap 은 못 찾았다)",
        str([r["text"] for r in got]))
    chk(len(got[0].get("rects") or []) == 2, "B 합친 줄은 원래 자리 둘을 기억한다")
    chk(STORE.remap(str(s1), 0, rows) == {}, "B (종전 방식은 합친 고침을 못 찾았다 — 원인 재현)")
    chk(len(rows) == 4, "B 받은 줄 목록은 건드리지 않는다(사본을 돌려준다)")
    # 한 줄 고침은 자리로 — 줄 번호가 틀려도
    STORE.set_fix(str(s1), 0, 99, "delta FIXED", rows[3]["text"], rows[3]["rect"])
    got = STORE.apply_to_rows(str(s1), 0, rows)
    chk(any(r["text"] == "delta FIXED" for r in got) and len(got) == 3,
        "B 한 줄 고침은 줄 번호가 틀려도 **자리로** 붙는다")
    # 네 곳이 같은 함수를 쓴다
    tx.close_cache()
    disp = tx.display_rows(str(s1), 0)
    chk(any(r["text"] == merged for r in disp) and not any(r["text"] == rows[1]["text"] for r in disp),
        "B 본문 읽기(display_rows)에도 합친 줄이 그대로", str([r["text"] for r in disp]))
    clean = dict(tx.clean_page_texts(str(s1), [0]))
    chk(merged in clean.get(0, "") and "delta FIXED" in clean.get(0, ""),
        "B 단어장(clean_page_texts)에도 고침이 자리로 얹힌다")
    import inspect
    from viewer import text_word
    wsrc = inspect.getsource(text_word.export_pages_to_docx)
    chk("fix_rows" in wsrc and "fix_lookup" not in wsrc, "B Word 저장도 같은 함수(fix_rows)를 쓴다")
    chk(not hasattr(tfs.TextFixStore, "apply_to_text"),
        "B 줄 번호로 얹는 함수는 없앴다(다시 쓰이지 않게)")
    from viewer.app import MainWindow
    chk("apply_to_rows" in inspect.getsource(MainWindow._on_text_rows),
        "B 텍스트 창도 같은 함수를 쓴다")

    # ── C. 여러 쪽을 한 번에 · 글꼴은 쓴 글자만 · 다시 반영해도 글이 남는다 ─
    s3 = scan_pdf(root / "multi.pdf", pages=3)
    size0 = os.path.getsize(str(s3))
    d = fitz.open(str(s3))
    r0 = tx.page_lines(d, str(s3), 0, tables="off", join_lines=False)
    r2 = tx.page_lines(d, str(s3), 2, tables="off", join_lines=False)
    d.close()
    tx.close_cache()
    out, err = apply_fixes_by_page(str(s3), {
        0: [{"line": 0, "text": "첫 쪽 고침 가나다", "rect": r0[0]["rect"]}],
        2: [{"line": 1, "text": "셋째 쪽 고침 라마바", "rect": r2[1]["rect"]}]})
    chk(bool(out) and not err, "C 여러 쪽 반영이 끝난다", err)
    d = fitz.open(str(s3))
    t0, t1, t2 = d[0].get_text(), d[1].get_text(), d[2].get_text()
    d.close()
    chk("첫 쪽 고침 가나다" in t0 and "셋째 쪽 고침 라마바" in t2,
        "C **두 쪽 모두** 들어간다(종전: 지금 쪽만)")
    chk("alpha first line p1" not in t0 and "bravo second line p3" not in t2,
        "C 고친 줄의 옛 글은 지워진다")
    chk("alpha first line p2" in t1, "C 고침이 없는 쪽은 그대로")
    grow = os.path.getsize(str(s3)) - size0
    chk(grow < 1_000_000, "C 글꼴 **전체**가 들어가지 않는다(맑은 고딕 ≈ 7MB)", "%d bytes" % grow)
    chk(Path(str(s3) + ".textfix.bak.pdf").exists(), "C 백업은 한 번 남긴다")
    # 한 번 반영한 쪽에 **새 글자**로 다시 반영 — 부분집합 글꼴을 재사용하면 빠진다(§4.5.10 ②)
    out2, err2 = apply_fixes_by_page(str(s3), {
        0: [{"line": 2, "text": "다시 반영 흙쫓뷁", "rect": r0[2]["rect"]}]})
    d = fitz.open(str(s3))
    t0b = d[0].get_text()
    hits = len(d[0].search_for("흙쫓뷁"))
    d.close()
    chk("다시 반영 흙쫓뷁" in t0b and "첫 쪽 고침 가나다" in t0b,
        "C 같은 쪽에 새 글자로 **다시** 반영해도 앞의 글·새 글이 모두 남는다", t0b[:120])
    chk(hits == 1, "C 다시 반영한 글도 검색된다")
    # 합친 줄 — 글자 크기는 **원래 줄 높이**로(합친 사각형은 여러 줄 높이다)
    s5 = scan_pdf(root / "size.pdf", pages=1)
    d = fitz.open(str(s5))
    r5 = tx.page_lines(d, str(s5), 0, tables="off", join_lines=False)
    d.close()
    tx.close_cache()
    ra5, rb5 = r5[0]["rect"], r5[1]["rect"]
    un5 = (min(ra5[0], rb5[0]), ra5[1], max(ra5[2], rb5[2]), rb5[3])
    long_txt = r5[0]["text"] + " " + r5[1]["text"]
    apply_fixes_by_page(str(s5), {0: [{"line": 0, "text": long_txt, "rect": un5,
                                       "rects": [ra5, rb5]}]})
    d = fitz.open(str(s5))
    spans = [(ln["bbox"][1], sp["size"]) for b in d[0].get_text("dict")["blocks"]
             if b.get("type") == 0 for ln in b["lines"] for sp in ln["spans"]
             if any(w in sp["text"] for w in ("alpha", "bravo", "first", "second"))]
    whole = " ".join(d[0].get_text().split())
    d.close()
    lh5 = ra5[3] - ra5[1]
    sizes = [z for _y, z in spans]
    chk(sizes and max(sizes) <= lh5 + 0.5 and min(sizes) >= lh5 * 0.6,
        "C 합친 줄의 글자 크기는 **원래 줄 높이**를 따른다", "%s / 줄 높이 %.1f" % (sizes, lh5))
    chk(len({round(y) for y, _z in spans}) >= 2,
        "C 합친 줄은 원래처럼 **여러 줄로** 들어간다(한 줄로 몰리지 않는다)", str(spans))
    chk(long_txt in whole, "C 합친 줄이 **잘리지 않고** 들어간다", whole[:120])

    # ── D. 앱 — 편집모드 안내·자동 전환·보던 쪽·모든 쪽·막기 ──────────────
    s4 = scan_pdf(root / "app.pdf", pages=3)
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    tp = mw.text_panel

    def goto(pg):
        mw.main_view.go_to_page(pg); app.processEvents()
        mw._reload_text_panel()
        for _ in range(100):
            app.processEvents(); QTest.qWait(40)
            if tp._page == pg and tp.rows():
                break
        return tp.rows()

    mw._load_main(HistoryItem(str(s4), 0, "", "bookmark")); app.processEvents()
    mw._vm_text(); app.processEvents()
    if mw._in_edit():
        mw.bookmark_tree.btn_edit.setChecked(False); app.processEvents()
    chk(not mw._in_edit(), "D 준비 — 편집모드가 아니다")

    rows = goto(1)
    n_before = len(rows)
    tp._merge_line_with_next(0); app.processEvents()
    rows = goto(2)
    tp.lineEdited.emit(2, 3, "EDITED P3", rows[3]["text"]); app.processEvents()
    goto(0)
    rows = goto(1)
    chk(len(rows) == n_before - 1 and "bravo second line p2" in rows[0]["text"],
        "D **쪽을 오간 뒤에도 합친 줄이 합쳐져 있다**(사용자 보고 재현)",
        "%d → %d %s" % (n_before, len(rows), rows[0]["text"] if rows else ""))

    msgs = []
    asked = []

    def fake_scope(msg, has_fixed, _ans=["fixed"]):
        # 260913-6(SOT §5.4): 범위 고르기 창 — 검사에서는 물음을 받아 적고 답을 정한다
        asked.append((msg, has_fixed))
        msgs.append(("q", msg))
        return _ans[0]

    mw._ask_layer_scope = fake_scope

    def wait_layer():
        for _ in range(300):
            app.processEvents(); QTest.qWait(30)
            if getattr(mw, "_text_layer_worker", None) is None:
                break
        app.processEvents(); QTest.qWait(150)

    real_q, real_i, real_w = QMessageBox.question, QMessageBox.information, QMessageBox.warning
    QMessageBox.question = staticmethod(
        lambda *a, **k: (msgs.append(("q", a[2])), QMessageBox.StandardButton.Yes)[1])
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("i", a[2])))
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("w", a[2])))
    try:
        # 막기 — 저장 안 한 쪽 편집이 있으면 반영하지 않는다
        mw.bookmark_tree.btn_edit.setChecked(True); app.processEvents()
        real_dirty = mw._page_edits_dirty
        mw._page_edits_dirty = lambda: True
        mw._on_text_apply_pdf(); app.processEvents()
        mw._page_edits_dirty = real_dirty
        chk(msgs and msgs[-1][0] == "i" and "저장하지 않은 쪽 편집" in msgs[-1][1],
            "D 저장 안 한 쪽 편집이 있으면 **먼저 저장하라고** 알리고 멈춘다")
        chk(STORE.pages_with_fixes(str(s4)) == [1, 2], "D 막았을 때는 아무것도 반영하지 않는다")
        mw.bookmark_tree.btn_edit.setChecked(False); app.processEvents()

        msgs.clear()
        goto(1)
        # 트리에서 다른 곳이 골라져 있던 상태 — 반영 뒤 파일 노드를 다시 고르면 트리가
        #   '첫 쪽으로 가기' 를 예약한다(보던 쪽을 덮는 원인)
        mw.bookmark_tree.tree.setCurrentItem(None); app.processEvents()
        mw._on_text_apply_pdf(); wait_layer()
        q = [m for t, m in msgs if t == "q"]
        chk(q and "편집모드로 바꾼 뒤 저장합니다" in q[0],
            "D 편집모드가 아니면 **편집모드로 바꾼 뒤 저장한다고** 알린다", str(msgs)[:200])
        chk(q and "2, 3쪽" in q[0], "D 확인 창에 반영할 쪽을 모두 적는다", q[0][:120] if q else "")
        chk(mw._in_edit(), "D [예] 뒤 편집모드로 바뀌어 있다")
        chk(not [m for t, m in msgs if t == "w"], "D 경고(덮어쓰기 실패 등)가 없다", str(msgs))
        chk(os.path.basename(mw.main_view.current_file() or "") == "app.pdf",
            "D 원본에 들어간다 — `_edited.pdf` 로 빠지지 않는다")
        chk(mw.main_view.current_page() == 1, "D **보던 쪽으로** 돌아온다",
            str(mw.main_view.current_page()))
        # 260913-6(SOT §5.1.4): 다시 쓰기는 '원천 + 고침' 이라 고침을 **남기고 반영 표시만** 한다
        chk(STORE.pages_with_fixes(str(s4)) == [1, 2] and STORE.pages_to_apply(str(s4)) == [],
            "D 반영한 쪽의 고침은 남기고 **반영 표시**만 한다", str(STORE.pages_to_apply(str(s4))))
        d = fitz.open(str(s4))
        p2 = d[1].get_text().replace("\n", " ")
        p3 = d[2].get_text()
        d.close()
        chk("alpha first line p2 bravo second line p2" in " ".join(p2.split()),
            "D PDF 2쪽에 합친 줄이 들어갔다", repr(p2))
        chk("EDITED P3" in p3, "D PDF 3쪽 고침도 **함께** 들어갔다")
        rows = goto(2)
        chk(any("EDITED P3" in r["text"] for r in rows), "D 다시 연 3쪽에 고친 글이 보인다")

        msgs.clear(); asked.clear()
        fake_scope.__defaults__[0][0] = ""          # 이번에는 취소
        mw._on_text_apply_pdf(); app.processEvents()
        chk(asked and asked[-1][1] is False and "아직 반영하지 않은 고침은 없습니다" in asked[-1][0],
            "D 반영할 고침이 없으면 그렇게 적고 [고친 쪽만] 은 내지 않는다", str(asked)[:160])
    finally:
        QMessageBox.question, QMessageBox.information, QMessageBox.warning = real_q, real_i, real_w

    csrc = inspect.getsource(MainWindow._close_main_view_doc)
    chk("close_cache" in csrc, "D 핸들 해제 한 곳(_close_main_view_doc)이 표 찾기 핸들도 놓는다")
finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
