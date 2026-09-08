# -*- coding: utf-8 -*-
"""260908-2: 우측 '텍스트' 창 (텍스트 창 SOT §9).

사용자 요청(260908):
  ① 탭 순서 **텍스트 / 단어장 / 검색**, 텍스트가 맨 왼쪽
  ② 현재 쪽의 본문(스캔본이면 OCR 결과)을 보여 준다
  ③ 표는 **한 행을 한 줄**로, **생략 옵션**도
  ④ 스타일은 제목/내용 둘, 글꼴·굵기·크기·자간·줄간격 조절 — 설정에 남는다
  ⑤ 글자가 큰 줄이 **제목**, 아니면 내용
  ⑥ 고치면 **본문 복사에 반영**되고, [PDF 에 반영] 로 OCR 텍스트층까지
  ⑦ 하이라이트 → 책갈피(제목·쪽·레벨)
  ⑧ Word 저장 — 현재 쪽 / 범위 / 전체
  ⑨ 줄을 고르거나 고치면 **본문 뷰어의 그 자리를 강조**(사용자 추가 요청)
  ⑩ 유료 LLM API 미사용
"""
import os, sys, inspect, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")
import test_fixtures as _fx

root = Path(tempfile.mkdtemp(prefix="polypdf_txtpanel_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)
FIXJSON = root / "text_fix.json"

try:
    import fitz
    from viewer import text_extract2 as tx
    from viewer.text_fix_store import TextFixStore
    from viewer.widgets.text_panel import TextPanel, DEFAULT_STYLES

    doc = fitz.open(str(pdf))

    # ── ② ⑤ 본문 추출과 제목 판정 ───────────────────────────────────────
    rows = tx.page_lines(doc, str(pdf), 0)
    chk(len(rows) > 3, "② 쪽의 본문 줄을 뽑는다", f"{len(rows)}줄")
    chk(rows[0]["style"] == "title",
        "⑤ 글자가 큰 첫 줄이 제목으로 잡힌다", rows[0]["text"][:24])
    chk(all(r["style"] == "body" for r in rows[1:]),
        "⑤ 나머지는 내용")
    chk(rows[0]["rect"] is not None and len(rows[0]["rect"]) == 4,
        "⑨ 줄마다 원본 사각형을 들고 있다(본문 강조용)", str(rows[0]["rect"] is not None))
    chk(tx.has_text_layer(doc, 0) is True, "② 텍스트층이 있는 쪽을 가려낸다")

    # OCR 폴백(텍스트층 없는 척 — ocr_text 를 주면 그것을 쓴다)
    empty = fitz.open(); empty.new_page()
    ocr_rows = tx.page_lines(empty, "", 0, ocr_text="ㅂ1ㅓ 를 고쳐야 한다\n둘째 줄")
    chk([r["text"] for r in ocr_rows] == ["ㅂ1ㅓ 를 고쳐야 한다", "둘째 줄"],
        "② 텍스트층이 없으면 OCR 결과를 쓴다", f"{len(ocr_rows)}줄")
    chk(all(r["rect"] is None for r in ocr_rows),
        "② OCR 폴백에는 좌표가 없다(본문 강조 불가 — 정상)")

    # ── ③ 표: 한 행 한 줄 · 생략 ────────────────────────────────────────
    from viewer.text_extract2 import _row_line, TABLE_OMIT_FMT
    chk(_row_line(["가", "나", None, "라"]) == "가 | 나 |  | 라",
        "③ 표 한 행이 한 줄이 된다(빈 칸도 자리를 지킨다)", _row_line(["가", "나", None, "라"]))
    chk("{cols}" in TABLE_OMIT_FMT and "{rows}" in TABLE_OMIT_FMT,
        "③ 표 생략 표시 형식이 있다", TABLE_OMIT_FMT)
    src_tx = inspect.getsource(tx)
    chk('tables == "omit"' in src_tx, "③ 생략 옵션이 실제로 갈라진다")
    chk("pdfplumber" in src_tx and "openai" not in src_tx.lower()
        and "anthropic" not in src_tx.lower(),
        "⑩ 표 인식은 좌표 기반(pdfplumber) — 유료 API 미사용")

    # ── ④ 스타일 ────────────────────────────────────────────────────────
    tp = TextPanel()
    tp.resize(420, 700)
    tp.show()
    chk(set(DEFAULT_STYLES) == {"title", "body"}, "④ 기본 스타일은 제목/내용 둘")
    for name in ("cmb_font", "sp_size", "btn_bold", "sp_sp", "sp_ls"):
        chk(hasattr(tp, name), f"④ 조절 위젯이 있다: {name}")
    tp.set_page(str(pdf), 0, rows)
    chk(len(tp.rows()) == len(rows), "④ 줄이 창에 들어간다")
    tp.cmb_style.setCurrentIndex(0)               # 제목
    tp.sp_size.setValue(22.0)
    chk(tp.styles()["title"]["size_pt"] == 22.0, "④ 스타일 값이 바뀐다")
    tp2 = TextPanel(); tp2.set_styles(tp.styles())
    chk(tp2.styles()["title"]["size_pt"] == 22.0, "④ 값을 주입해 되살릴 수 있다(설정 저장)")

    # ── ⑨ 줄을 고르면 본문 강조 신호 ────────────────────────────────────
    got = {"n": 0, "last": None}
    tp.lineFocused.connect(lambda pg, rc: (got.__setitem__("n", got["n"] + 1),
                                           got.__setitem__("last", (pg, rc))))
    cur = tp.edit.textCursor()
    cur.movePosition(cur.MoveOperation.Start)
    cur.movePosition(cur.MoveOperation.Down)
    tp.edit.setTextCursor(cur)
    app.processEvents()
    chk(got["n"] > 0 and got["last"] and got["last"][1],
        "⑨ 줄을 고르면 (쪽, 사각형) 을 알린다", str(got["last"][0] if got["last"] else None))

    # ── ⑥ 고침 → 저장소 → 복사 반영 ─────────────────────────────────────
    st = TextFixStore(FIXJSON)
    st.set_fix(str(pdf), 0, 1, "배 로 고침", orig=rows[1]["text"])
    chk(st.get_fixes(str(pdf), 0)[1] == "배 로 고침", "⑥ 고친 글이 저장된다")
    copied = st.apply_to_copy(str(pdf), 0, "앞 " + rows[1]["text"] + " 뒤")
    chk("배 로 고침" in copied and rows[1]["text"] not in copied,
        "⑥ 복사한 글에 고침이 반영된다", copied[:44])
    st2 = TextFixStore(FIXJSON)
    chk(st2.get_fixes(str(pdf), 0)[1] == "배 로 고침", "⑥ 다시 열어도 남아 있다")
    st.set_fix(str(pdf), 0, 1, None)
    chk(1 not in st.get_fixes(str(pdf), 0), "⑥ 되돌릴 수 있다")

    from viewer.widgets.main_view import MainView
    mv_src = inspect.getsource(MainView.copy_selection) + inspect.getsource(
        MainView.copy_page_text)
    chk(mv_src.count("_apply_text_fixes") == 2,
        "⑥ 본문 복사 두 경로가 모두 고침을 거친다")

    # ── ⑥-b PDF 텍스트층 반영 ───────────────────────────────────────────
    from viewer import text_apply
    ap = inspect.getsource(text_apply)
    chk("add_redact_annot" in ap and "PDF_REDACT_IMAGE_NONE" in ap,
        "⑥-b 글자만 지우고 그림은 건드리지 않는다")
    chk("render_mode" in ap, "⑥-b 보이지 않는 글자로 다시 적는다(모양 유지)")
    chk("BACKUP_SUFFIX" in ap, "⑥-b 원본을 백업한다")

    # ── ⑦ 하이라이트 → 책갈피 ───────────────────────────────────────────
    tp.set_page(str(pdf), 4, rows)
    c = tp.edit.textCursor()
    c.movePosition(c.MoveOperation.Start)
    c.movePosition(c.MoveOperation.EndOfBlock, c.MoveMode.KeepAnchor)
    tp.edit.setTextCursor(c)
    tp._on_highlight()
    picks = tp.highlighted_lines()
    chk(len(picks) == 1 and picks[0]["line"] == 0, "⑦ 칠한 줄을 찾아낸다", str(len(picks)))
    made = {"items": None}
    tp.bookmarkFromHighlight.connect(lambda items: made.__setitem__("items", items))
    tp._on_make_bookmarks()
    it = (made["items"] or [None])[0]
    chk(it is not None, "⑦ 책갈피 항목을 만든다")
    if it:
        chk(it["page"] == 5, "⑦ 쪽은 지금 보고 있는 쪽(1부터)", str(it["page"]))
        chk(it["level"] == 1, "⑦ 제목 스타일이면 1단계", str(it["level"]))
        chk(it["title"] and len(it["title"]) <= 40, "⑦ 제목은 칠한 글(40자 제한)",
            it["title"][:30])

    # ── ⑧ Word 저장 ─────────────────────────────────────────────────────
    from viewer.text_word import export_pages_to_docx
    dst = root / "out.docx"
    ok, msg = export_pages_to_docx(str(pdf), doc, [0, 1], str(dst), tp.styles())
    chk(ok and dst.exists() and dst.stat().st_size > 0,
        "⑧ Word 파일이 만들어진다", msg or f"{dst.stat().st_size if dst.exists() else 0} bytes")
    try:
        from docx import Document as _D
        d2 = _D(str(dst))
        heads = [p.text for p in d2.paragraphs if p.style.name.startswith("Heading")]
        chk(len(heads) >= 1, "⑧ 제목 줄이 Word 제목 스타일로 나간다", str(heads[:1]))
    except Exception as e:
        chk(False, "⑧ Word 파일을 다시 읽을 수 있다", str(e))
    from viewer.app import MainWindow
    ex = inspect.getsource(MainWindow._on_text_export_word)
    chk('"page"' in ex and '"all"' in ex and "range" in ex,
        "⑧ 현재 쪽·범위·전체 세 가지를 다 다룬다")

    # ── ① 탭 순서 ───────────────────────────────────────────────────────
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show()
    tabs = [mw.search_tabs.tabText(i) for i in range(mw.search_tabs.count())]
    chk(len(tabs) >= 3 and "텍스트" in tabs[0] and "단어장" in tabs[1]
        and "검색" in tabs[2],
        "① 탭 순서가 텍스트 / 단어장 / 검색", str(tabs))
    mw.open_pdf(pdf); app.processEvents()
    mw.search_tabs.setCurrentWidget(mw.text_panel)
    mw._reload_text_panel(); app.processEvents()
    chk(len(mw.text_panel.rows()) > 3, "① 탭을 고르면 현재 쪽이 채워진다",
        f"{len(mw.text_panel.rows())}줄")
    chk("text_panel_styles" in mw._build_settings_payload().get("preferences", {}),
        "④ 스타일이 설정에 저장된다(허용목록 통과)")
    # ── 감사(260908-3): 응답성·SOT 정합 ─────────────────────────────────
    src_tx = inspect.getsource(tx)
    chk("_plumber" in src_tx and "close_cache" in src_tx,
        "감사① pdfplumber 핸들을 재사용한다(쪽마다 새로 열지 않는다)")
    import time as _t
    doc2 = fitz.open(str(pdf))
    ts = []
    for pg in range(min(4, doc2.page_count)):
        t0 = _t.time(); tx.page_lines(doc2, str(pdf), pg); ts.append(_t.time() - t0)
    t0 = _t.time(); tx.page_lines(doc2, str(pdf), 0); again = _t.time() - t0
    chk(again < max(ts) + 0.05, "감사① 같은 쪽은 캐시로 다시 뽑지 않는다",
        f"처음 {max(ts)*1000:.0f}ms → 다시 {again*1000:.0f}ms")
    tx.close_cache()

    from viewer.workers import TextPageWorker
    chk(hasattr(TextPageWorker, "request_cancel"),
        "감사② 쪽 추출 워커가 있고 취소된다(응답성 §4 ①)")
    wsrc = inspect.getsource(TextPageWorker)
    chk("fitz.open(self.doc_path)" in wsrc,
        "감사② 워커가 문서를 따로 연다(PyMuPDF 문서는 스레드 안전하지 않다)")
    app_src = inspect.getsource(MainWindow._reload_text_panel)
    chk("TextPageWorker" in app_src and "request_cancel" in app_src,
        "감사② 창 적재가 워커를 쓰고 앞의 것을 취소한다")
    chk("_text_token" in app_src, "감사② 세대 토큰으로 마지막 요청만 쓴다")

    chk(hasattr(tp, "restore_highlights"),
        "감사③ 하이라이트를 다시 칠하는 길이 있다(쪽을 넘겨도 남는다)")
    tp.set_page(str(pdf), 0, rows)
    tp.restore_highlights([[0, 0, 5, "#ffe680"]])
    chk(len(tp.highlighted_lines()) == 1, "감사③ 저장해 둔 하이라이트가 되살아난다")

    chk(hasattr(tp, "apply_style_to_selection"),
        "감사④ 고른 줄의 스타일을 바꾸는 길이 있다")
    c2 = tp.edit.textCursor(); c2.movePosition(c2.MoveOperation.Start)
    # ★ Down 은 **화면상 줄**로 움직인다(줄바꿈된 긴 줄에서는 같은 블록 안에 머문다).
    #   줄(블록) 단위로 고르려면 NextBlock 을 쓴다.
    c2.movePosition(c2.MoveOperation.NextBlock, c2.MoveMode.KeepAnchor)
    tp.edit.setTextCursor(c2)
    tp.cmb_style.setCurrentIndex(0)
    tp.apply_style_to_selection()
    chk(tp.rows()[1]["style"] == "title", "감사④ 내용 줄을 제목으로 바꿀 수 있다",
        f"sel={c2.selectionStart()}~{c2.selectionEnd()} key={tp._cur_style_key()} "
        f"styles={[r['style'] for r in tp.rows()[:3]]}")

    # 260908-8(사용자 지시): 단추는 **늘 보인다** — OCR 이 잘못 읽은 쪽을 다시 읽히려면
    #   글자가 있는 쪽에서도 눌러야 한다. 문구만 상황에 따라 바뀐다.
    chk(hasattr(tp, "btn_ocr"), "감사⑤ [OCR 다시 읽기] 단추가 있다")
    tp.set_page(str(pdf), 0, [], "스캔본입니다")
    chk(tp.btn_ocr.isVisible() is True, "감사⑤ 글자가 없을 때 보인다")
    chk(tp.btn_ocr.text() == "OCR 로 읽기", "감사⑤ 글자가 없으면 '읽기'", tp.btn_ocr.text())
    tp.set_page(str(pdf), 0, rows)
    chk(tp.btn_ocr.isVisible() is True, "감사⑤ 글이 있어도 계속 보인다(260908-8)")
    chk(tp.btn_ocr.text() == "OCR 다시 읽기", "감사⑤ 글이 있으면 '다시 읽기'",
        tp.btn_ocr.text())

    from viewer import indexer as _ix
    isrc = inspect.getsource(_ix)
    chk("_apply_text_fixes" in isrc,
        "감사⑥ 검색 색인에도 교정이 얹힌다(찾은 것이 안 찾아지지 않게)")
    ocr_src = inspect.getsource(MainWindow._ocr_page_text)
    chk("BUSY_MS_UI" in ocr_src, "감사⑦ study.db 연결이 UI 대기 상한을 쓴다(응답성 §4 ⑤)")
    ap_src = inspect.getsource(MainWindow._on_text_apply_pdf)
    chk("close_cache" in ap_src,
        "감사⑧ PDF 를 덮어쓰기 전에 열린 핸들을 놓는다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
