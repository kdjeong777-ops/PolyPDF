# -*- coding: utf-8 -*-
"""260908-6: 빈 공간의 '이상한 글자' 와 **줄 어긋남** (텍스트 창 SOT §3.5·§5.1.1).

사용자 보고(260908): "빈 공간인데 `픔` 같은 글자가 뜬다. 그 줄을 지우고 PDF 에 반영했더니
PDF 와 텍스트가 안 맞고, 밑에 있던 다른 글이 그 자리에 맞춰진다."

원인 두 가지를 각각 고정한다.
  A. 그 글자는 **스캔본의 보이지 않는 OCR 층**에 든 잡음이다(종이의 티를 글자로 읽은 것).
     글자 상자 높이가 1.4~3.4pt 로, 같은 쪽 진짜 글(5.3~27.9pt)과 확연히 다르다.
  B. 창이 **편집기 블록 번호**를 줄 번호로 썼다. 줄을 통째로 지우면 아래 번호가 당겨져
     그 뒤의 편집이 전부 한 칸 어긋난 줄에 기록됐고, 반영이 엉뚱한 사각형을 지웠다.

검사 대상
  ① 잡음 줄은 줄 목록에 오지 않는다 — 보이지 않는 OCR 층인 쪽에서만
  ② 일반 PDF(사람이 넣은 글자)는 **한 줄도** 빼지 않는다
  ③ 줄 수는 변하지 않는다 — Enter·줄 합치기·여러 줄 삭제·여러 줄 붙여넣기
  ④ 줄을 비우면 그 줄의 **제 인덱스**로 알린다(지우기 = 내용 비우기)
  ⑤ 비운 뒤 다른 줄을 고쳐도 **그 줄의 사각형**이 나온다(어긋나지 않는다)
  ⑥ 고침은 사각형과 함께 저장되고, 목록이 달라져도 **자리로 되맞춘다**
  ⑦ 반영은 저장된 사각형을 지운다 — 줄 번호가 밀려도 엉뚱한 줄을 지우지 않는다
  ⑧ 다시 적지 못한 줄은 조용히 넘기지 않고 알린다
"""
import os, sys, inspect, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextCursor, QKeyEvent
from PyQt6.QtCore import Qt, QEvent, QMimeData

fails = []
NL = chr(10)


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv[:1])
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")

import fitz
import test_fixtures as _fx
from viewer import text_extract2 as tx
from viewer.text_fix_store import TextFixStore
from viewer.text_apply import apply_fixes_to_pdf
from viewer.widgets.text_panel import TextPanel

root = Path(tempfile.mkdtemp(prefix="polypdf_align_"))
KRFONT = r"C:\Windows\Fonts\malgun.ttf"


def key(w, k, txt=""):
    for typ in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        app.sendEvent(w, QKeyEvent(typ, k, Qt.KeyboardModifier.NoModifier, txt))
    app.processEvents()


def scan_with_noise(dst):
    """그림 위에 **보이지 않는** 글자를 얹은 쪽 — 진짜 글 + 잡음(아주 작은 글자)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    for i, t in enumerate(("첫째 줄입니다", "둘째 줄입니다", "셋째 줄입니다")):
        page.insert_text((60, 120 + i * 40), t, fontsize=14, render_mode=3,
                         fontfile=KRFONT, fontname="kr")
    # 잡음 — 사람이 읽을 수 없는 크기(빈 공간의 티를 OCR 이 글자로 읽은 것)
    page.insert_text((400, 60), "픔", fontsize=2.0, render_mode=3,
                     fontfile=KRFONT, fontname="kr")
    page.insert_text((430, 300), "똬", fontsize=2.5, render_mode=3,
                     fontfile=KRFONT, fontname="kr")
    doc.save(str(dst))
    doc.close()
    return dst


try:
    # ── ①② 잡음 거르기 ───────────────────────────────────────────
    scan = scan_with_noise(root / "scan.pdf")
    tx.set_table_cache_db(None)
    tx.close_cache()
    d = fitz.open(str(scan))
    chk(tx._is_ocr_layer(d.load_page(0)) is True, "① 보이지 않는 OCR 층으로 알아본다")
    rows = tx.page_lines(d, str(scan), 0, tables="off", join_lines=False)
    texts = [r["text"] for r in rows]
    chk(all("픔" not in t and "똬" not in t for t in texts),
        "① 빈 공간의 잡음 글자는 줄 목록에 오지 않는다", str(texts))
    chk(len(texts) == 3, "① 진짜 글 3줄은 그대로", str(len(texts)) + "줄")
    chk(tx.last_noise_count() == 2, "① 뺀 줄 수를 셀 수 있다(창 안내용)",
        str(tx.last_noise_count()) + "줄")
    d.close()

    plain = Path(_fx.text_pdf())
    d2 = fitz.open(str(plain))
    chk(tx._is_ocr_layer(d2.load_page(0)) is False, "② 일반 PDF 는 OCR 층이 아니다")
    n_raw = len([1 for b in d2.load_page(0).get_text("dict")["blocks"]
                 if b.get("type") == 0
                 for ln in b.get("lines", [])
                 if "".join(s.get("text", "") for s in ln.get("spans", [])).strip()])
    chk(len(tx.page_lines(d2, str(plain), 0, tables="off", join_lines=False)) == n_raw,
        "② 일반 PDF 는 한 줄도 빼지 않는다", str(n_raw) + "줄")
    d2.close()

    # ── ③④⑤ 줄 수 고정 ─────────────────────────────────────────
    tp = TextPanel()
    prows = [{"text": "줄" + str(i), "style": "body",
              "rect": (0.0, i * 10.0, 100.0, i * 10.0 + 9.0), "kind": "text"}
             for i in range(5)]
    tp.set_page("x.pdf", 0, [dict(r) for r in prows])
    seen = []
    tp.lineEdited.connect(lambda pg, i, t, o: seen.append((i, t)))
    chk(tp.edit.document().blockCount() == 5, "③ 줄 하나에 블록 하나",
        str(tp.edit.document().blockCount()) + "블록")

    # 260910-11(사용자 요청, SOT §5.1.2): **합치기는 이제 허용한다.** 종전에는 줄
    #   번호가 당겨지는 것을 막으려 입력 자체를 막았는데, 이제 줄과 **자리(사각형)를
    #   함께** 합쳐 번호를 맞춰 두므로 어긋나지 않는다. 늘리는 것은 여전히 막는다.
    c = QTextCursor(tp.edit.document().findBlockByNumber(1))
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    tp.edit.setTextCursor(c)
    key(tp.edit, Qt.Key.Key_Delete)
    chk(tp.edit.document().blockCount() == 4, "③ 줄 끝 Delete 로 아랫줄과 합쳐진다",
        str(tp.edit.document().blockCount()) + "블록")
    chk(len(tp.rows()) == 4, "③ 줄 목록도 함께 줄어 번호가 어긋나지 않는다",
        str(len(tp.rows())) + "행")
    _m = tp.rows()[1]
    chk(_m.get("text") == "줄1 줄2", "③ 두 줄의 글이 이어 붙는다", repr(_m.get("text")))
    chk(len(_m.get("rects") or []) == 2, "③ 원래 자리 둘을 기억한다",
        str(len(_m.get("rects") or [])))
    chk(_m.get("rect") == (0.0, 10.0, 100.0, 29.0),
        "③ 합친 자리는 첫 줄 좌상 ~ 둘째 줄 우하", str(_m.get("rect")))

    tp.edit.setTextCursor(QTextCursor(tp.edit.document().findBlockByNumber(2)))
    key(tp.edit, Qt.Key.Key_Backspace)
    chk(tp.edit.document().blockCount() == 3, "③ 줄 처음 Backspace 로 윗줄과 합쳐진다",
        str(tp.edit.document().blockCount()) + "블록")
    chk(len(tp.rows()) == 3, "③ 이때도 줄 목록이 같이 줄어든다")
    key(tp.edit, Qt.Key.Key_Return, NL)
    chk(tp.edit.document().blockCount() == 3, "③ Enter 로 줄이 늘지는 않는다",
        str(tp.edit.document().blockCount()) + "블록")

    md = QMimeData()
    md.setText("가" + NL + "나" + NL + "다")
    tp.edit.insertFromMimeData(md)
    app.processEvents()
    chk(tp.edit.document().blockCount() == 3, "③ 여러 줄 붙여넣기도 줄을 늘리지 않는다",
        str(tp.edit.document().blockCount()) + "블록")

    tp.set_page("x.pdf", 0, [dict(r) for r in prows])
    seen.clear()
    blk = tp.edit.document().findBlockByNumber(1)
    c = QTextCursor(blk)
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
    tp.edit.setTextCursor(c)
    key(tp.edit, Qt.Key.Key_Delete)
    chk(tp.edit.document().blockCount() == 5, "④ 줄을 비워도 줄 수는 그대로")
    chk(bool(seen) and seen[-1] == (1, ""), "④ 비운 줄을 제 인덱스로 알린다", str(seen))

    seen.clear()
    c = QTextCursor(tp.edit.document().findBlockByNumber(3))
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    tp.edit.setTextCursor(c)
    key(tp.edit, Qt.Key.Key_X, "X")
    got = seen[-1][0] if seen else -1
    chk(got == 3, "⑤ 비운 뒤에도 고친 줄의 인덱스가 맞는다", "i=" + str(got))
    chk(got >= 0 and tp.rows()[got]["rect"] == (0.0, 30.0, 100.0, 39.0),
        "⑤ 그 인덱스의 사각형이 그 줄의 것",
        str(tp.rows()[got]["rect"]) if got >= 0 else "")

    tp.set_page("x.pdf", 0, [dict(r) for r in prows])
    c = QTextCursor(tp.edit.document())
    c.setPosition(tp.edit.document().findBlockByNumber(1).position())
    c.setPosition(tp.edit.document().findBlockByNumber(3).position() + 2,
                  QTextCursor.MoveMode.KeepAnchor)
    tp.edit.setTextCursor(c)
    key(tp.edit, Qt.Key.Key_Delete)
    chk(tp.edit.document().blockCount() == 5, "③ 여러 줄 선택 삭제도 줄을 합치지 않는다",
        str(tp.edit.document().blockCount()) + "블록")

    # ── ⑥ 저장은 사각형과 함께, 되맞춤은 자리로 ────────────────────
    st = TextFixStore(root / "fix.json")
    st.set_fix(str(scan), 0, 1, "고친 둘째", "둘째 줄입니다", (0.0, 10.0, 100.0, 19.0))
    items = st.get_items(str(scan), 0)
    chk(bool(items) and items[0]["rect"] == (0.0, 10.0, 100.0, 19.0),
        "⑥ 고침에 사각형이 함께 저장된다", str(items))
    shifted = [{"text": "새 줄", "rect": (0.0, 0.0, 100.0, 9.0)},
               {"text": "또 새 줄", "rect": (0.0, 5.0, 100.0, 8.0)},
               {"text": "둘째 줄입니다", "rect": (0.0, 10.0, 100.0, 19.0)}]
    m = st.remap(str(scan), 0, shifted)
    chk(m == {2: "고친 둘째"}, "⑥ 목록이 밀려도 **자리로** 제 줄을 찾는다", str(m))
    m2 = st.remap(str(scan), 0, [{"text": "둘째 줄입니다", "rect": None}])
    chk(m2 == {0: "고친 둘째"}, "⑥ 자리가 안 맞으면 원래 글로 찾는다", str(m2))
    st.set_fix(str(scan), 0, 0, "옛 형식", None, None)
    chk(st.remap(str(scan), 0, shifted).get(0) == "옛 형식",
        "⑥ 자리도 원문도 없는 옛 기록은 줄 번호로")

    # ── ⑦ 반영은 저장된 사각형을 지운다 ────────────────────────────
    work = root / "w.pdf"
    shutil.copy2(str(scan), str(work))
    tx.close_cache()
    dw = fitz.open(str(work))
    wrows = tx.page_lines(dw, str(work), 0, tables="off", join_lines=False)
    target = dict(wrows[1])                       # '둘째 줄입니다'
    dw.close()
    # 줄 번호는 일부러 **틀리게** 준다 — 사각형이 이겨야 한다
    out, err = apply_fixes_to_pdf(str(work), 0,
                                  [{"rect": None} for _ in wrows],
                                  [{"line": 99, "text": "", "rect": target["rect"]}])
    chk(bool(out) and not err, "⑦ 줄 번호가 틀려도 사각형으로 반영된다", err or "")
    tx.close_cache()
    do = fitz.open(out)
    after = [r["text"] for r in tx.page_lines(do, out, 0, tables="off", join_lines=False)]
    do.close()
    chk("둘째 줄입니다" not in after, "⑦ 지정한 줄이 지워졌다", str(after))
    chk("첫째 줄입니다" in after and "셋째 줄입니다" in after,
        "⑦ 다른 줄은 그대로다 — 밑의 글이 당겨지지 않는다", str(after))

    # ── ⑧ 못 적은 줄을 알린다 ─────────────────────────────────────
    src2 = root / "w2.pdf"
    shutil.copy2(str(scan), str(src2))
    tx.close_cache()
    d3 = fitz.open(str(src2))
    r3 = tx.page_lines(d3, str(src2), 0, tables="off", join_lines=False)
    d3.close()
    tiny = (10.0, 10.0, 11.0, 11.0)          # 1pt 사각형 — 긴 글이 들어갈 수 없다
    out2, err2 = apply_fixes_to_pdf(str(src2), 0, r3,
                                    [{"line": 0, "text": "아" * 400, "rect": tiny}])
    chk(bool(out2), "⑧ 반영 자체는 끝난다")
    ap = inspect.getsource(apply_fixes_to_pdf.__globals__["_write_invisible"])
    chk(">= 0" in ap, "⑧ insert_textbox 의 반환값(음수=못 적음)을 본다")
    from viewer.app import MainWindow
    asrc = inspect.getsource(MainWindow._on_text_apply_pdf)
    chk("if err and not out" in asrc,
        "⑧ 알림을 '실패' 로 오해하지 않는다(경로가 있으면 반영은 된 것)")
    chk("get_items" in asrc, "⑦ 앱이 사각형이 든 형태로 넘긴다")
    rsrc = inspect.getsource(MainWindow._on_text_rows)
    chk("remap" in rsrc, "⑥ 앱이 다시 열 때 되맞춘다")

finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (" + str(len(fails)) + ")") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
