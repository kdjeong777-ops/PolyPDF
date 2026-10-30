# -*- coding: utf-8 -*-
"""261012-1: 서명 자리(초안) → 일괄 확정 → 서명 편집 · 그림만 · 글자 배치 (보안 SOT §3.3·§3.4·§3.6·§3.10·§3.11, 검사 T).

T1 글쓰기 도구가 켜진 채 서명 단추 → **실제 마우스 끌기**로 서명 자리가 생긴다(종전: 글상자가 끌기를 가져갔다)
T2 기본 글자 배치 '그림 위·글자 아래' — 옛 signing.json(겹쳐)도 한 번 바뀐다
T3 겉모양 글자가 잘리지 않는다 — 긴 이메일·날짜 줄이 글자 칸 안, 맑은 고딕 `/W` 폭이 1000 단위
T4 한 쪽에 자리 여럿 — 실제 마우스로 옮기기·모서리로 크기, Delete 로 지우기
T5 일괄 확정 → `<이름>_서명.pdf`: 전자서명 둘(유효)·그림만 하나(서명 칸 아님)·원본 바이트 그대로·자리 기록은 결과 파일로
T6 서명 편집 → 원본 위에 자리 되살림 → 옮겨 다시 확정 → [바꾸기] → 서명 파일 자리 바뀜·유효
T7 기록 없는 서명 파일 편집 → `<이름>_서명전.pdf` 바탕(%%EOF)·서명 자리만 되살림
T8 다른 사람 서명이 뒤에 있으면 편집 거부
T9 회전한 쪽 그림만 — 끈 상자 안에 바로 선다
"""
import os, sys, shutil, time, hashlib, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["POLYPDF_FAKE_HELLO"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_signdraft_%d" % os.getpid())
from viewer import sign_core as sc, sign_store as st, sign_drafts as sdr

fails = []
PW = "Sign-Test-2026!"


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


tmp = Path(tempfile.mkdtemp(prefix="signdraft_"))
try:
    # ── 준비: ID·서명 그림·문서(3쪽, 2쪽은 /Rotate 90) ─────────────────────
    pfx, info = sc.create_id("홍길동", PW, email="hong.gildong.longname@example-company.co.kr")
    st.add_id(pfx, info)
    from viewer import sign_hello as sh
    sh.store(info.fp, PW)
    st.set_id_flag(info.fp, hello=True)
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (400, 160), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 399, 159], outline=(0, 0, 220, 255), width=6)
    dr.rectangle([0, 0, 70, 50], fill=(220, 0, 0, 255))        # 왼쪽 위 표식(회전 확인)
    st.add_image(im, "기본")

    # T2 — 옛 signing.json(겹쳐, rev 없음) → 한 번 '그림 위·글자 아래'
    import json
    p_idx = st.root() / st.INDEX
    raw = json.loads(p_idx.read_text(encoding="utf-8"))
    raw["appearance"] = {"show_name": True, "show_date": True, "show_reason": False, "layout": "overlay"}
    raw.pop("appearance_rev", None)
    p_idx.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    chk(st.load()["appearance"]["layout"] == "image_top" and sc.Appearance().layout == "image_top",
        "T2 기본 글자 배치 '그림 위·글자 아래' — 옛 목록(겹쳐)도 한 번 바뀐다", str(st.load()["appearance"]))
    st.save(st.load())
    d_ = st.load(); d_["appearance"]["layout"] = "overlay"; st.save(d_)
    chk(st.load()["appearance"]["layout"] == "overlay", "T2b 바꾼 뒤 사용자가 고른 배치는 지킨다")
    d_["appearance"]["layout"] = "image_top"; st.save(d_)

    # T3 — 글자가 잘리지 않는다
    app_ = sc.Appearance(image_path=st.image_path("기본"), font_path=sc.default_font())
    label = sc.signer_label(info.name, info.email)
    tl = sc.text_layout(app_, label, "", 142.0)
    m = sc._Measure(app_.font_path)
    widest = max(m.width(sc._TS_SAMPLE if ln == "%(ts)s" else ln, tl.size) for ln in tl.lines)
    chk(widest <= 142.0 - 2 * sc.TEXT_PAD_PT + 0.5 and tl.size >= sc.TEXT_PT_MIN - 0.01 and len(tl.lines) >= 3,
        "T3 긴 이메일 줄은 6pt 아래로 줄이지 않고 나눠, 모든 줄이 글자 칸 폭 안", "%s %s %.1f" % (tl.size, tl.lines, widest))
    tw, th = sc.stamp_size(app_, label, "", 142.0, 57.0)
    chk(tw == 142.0 and abs(th - (57.0 + tl.height)) < 0.01, "T3b 그림 위·글자 아래 — 글자 줄은 상자 아래에 덧붙는다", str((tw, th)))

    # ── 실제 MainWindow ───────────────────────────────────────
    src = tmp / "folder"; src.mkdir()
    doc_path = src / "계약서.pdf"
    d = fitz.open()
    for i in range(3):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 100), "Page %d contract text" % (i + 1), fontsize=18)
        if i == 1:
            pg.set_rotation(90)
    d.save(str(doc_path)); d.close()
    orig_sha = sha(doc_path)

    from viewer.app import MainWindow
    import viewer.widgets.sign_dialogs as sdlg
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); spin(0.3)
    mw.open_folder(str(src)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.3)

    picked = {}
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next((b for b in self.buttons() if picked.get("text") and picked["text"] in b.text()), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    infos = []
    QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3] if len(a) > 2 else a))

    class _HelloDlg(sdlg.SignDialog):
        def exec(self):
            self._hello()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _HelloDlg

    # T1 — 편집 모드 + 글쓰기 도구가 켜진 채 서명 단추 → 실제 마우스로 끌기
    mw._on_edit_mode_toggled(True)
    mv._toggle_text()
    chk(mv._draw_kind == "text" and mv._draw_tool is not None, "T1a 글쓰기 도구가 켜져 있다")
    mv.btn_sign.click(); spin(0.2)
    chk(mv._draw_tool is None and mv.view._block_armed and mv.view._block_purpose == "sign",
        "T1b 서명 단추 → 그리기 도구를 끄고 서명 자리 끌기를 무장", str((mv._draw_kind, mv.view._block_armed)))
    vp = mv.view.viewport()
    pr = mv._page_view_rect()
    z = pr.width() / 595.0
    p0 = QPoint(int(pr.left() + 100 * z), int(pr.top() + 300 * z))
    p1 = QPoint(int(pr.left() + 250 * z), int(pr.top() + 360 * z))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for k in range(1, 6):
        QTest.mouseMove(vp, p0 + (p1 - p0) * (k / 5.0))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    spin(0.5)
    ds = sdr.drafts(doc_path)
    chk(len(ds) == 1 and ds[0]["kind"] == "sign" and abs(ds[0]["rect"][0] - 100) < 3 and abs(ds[0]["rect"][2] - 250) < 3,
        "T1 글쓰기 도구가 켜져 있어도 끈 자리에 서명 자리가 생긴다(서명하지 않고 초안)", str(ds))
    chk(sha(doc_path) == orig_sha and not list(src.glob("*_서명.pdf")), "T1c 자리만 놓았다 — 원본·새 파일 그대로")
    mw._on_edit_mode_toggled(False)
    spin(0.3)
    chk(mv.sign_draft_band.isVisible() and "1" in mv.sign_draft_band.label.text(), "T1d 서명 자리 띠가 보인다",
        mv.sign_draft_band.label.text())
    # 261031-1(error.log): 도구 메뉴 '전자서명 ▸ 서명...' 은 triggered(checked=False) 를 at_scene 으로 넘겨 QRectF(False, False) 오류 —
    #   메뉴로는 서명을 시작할 수 없었다. 실제 메뉴 항목을 눌러 끌기가 무장되는지 본다(sys.excepthook 으로 예외를 잡는다)
    _exc = []
    _hook = sys.excepthook
    sys.excepthook = lambda *a: _exc.append(a[1])
    try:
        mv.view.arm_block_select(False)
        _sub = mw._cmds["tools.sign"].menu()
        _a_sign = next(a for a in _sub.actions() if a.text().startswith("서명"))
        _a_sign.trigger(); spin(0.2)
    finally:
        sys.excepthook = _hook
    chk(not _exc and mv.view._block_armed and mv.view._block_purpose == "sign",
        "T1m 도구 메뉴 '서명...' 을 누르면 오류 없이 자리 끌기를 무장한다(261031-1)", repr(_exc[:1]))
    mv.view.arm_block_select(False)
    mw._sign_pending = None

    # T4 — 자리 둘 더(전자서명·그림만), 실제 마우스로 옮기기·크기, Delete
    from PyQt6.QtCore import QRectF
    mw._sign_pending = str(doc_path); mw._sign_pending_mode = "sign"
    mw._on_sign_region(QRectF(300 * mv._zoom, 500 * mv._zoom, 450 * mv._zoom, 560 * mv._zoom), view=mv)
    mw._sign_pending = str(doc_path); mw._sign_pending_mode = "image"
    mw._on_sign_region(QRectF(100 * mv._zoom, 600 * mv._zoom, 200 * mv._zoom, 640 * mv._zoom), view=mv)
    # 미리보기(배경) — 고정 시간이 아니라 그림이 들어올 때까지(최대 10초). 처음 그릴 때 pyHanko 를 불러와
    #   기계가 바쁘면 1.5초를 넘긴다(261012 묶음 검사에서 두 번 실패 — 마스터 §14.7.2 의 17)
    for _ in range(200):
        spin(0.05)
        _l = mv.sign_draft_layer
        _ds = sdr.drafts(doc_path)
        if _l is not None and len(_l.boxes) == 3 and all(
                (_b := _l.box_for(d["id"])) is not None and _b.d.get("pix") is not None and not _b.d["pix"].isNull()
                for d in _ds if d["kind"] == "sign"):
            break
    lay = mv.sign_draft_layer
    ds = sdr.drafts(doc_path)
    chk(len(ds) == 3 and len(lay.boxes) == 3 and sum(1 for x in ds if x["kind"] == "image") == 1,
        "T4a 한 쪽에 자리 셋(전자서명 둘·그림만 하나)", str(len(lay.boxes)))
    b0 = lay.box_for(ds[0]["id"])
    chk(b0 is not None and b0.d.get("pix") is not None and not b0.d["pix"].isNull(), "T4b 전자서명 자리 미리보기(배경에서 그림)")
    chk(b0 is not None and b0.height() > (ds[0]["rect"][3] - ds[0]["rect"][1]) * lay.scale() + 5,
        "T4c 전자서명 자리는 그림 상자 + 아래 글자 줄", str(b0.geometry() if b0 else None))
    # 옮기기 — 위젯 안을 눌러 40pt 오른쪽·20pt 아래로
    s_ = lay.scale()
    c = QPoint(b0.width() // 2, 6)
    g0 = b0.mapToGlobal(c)                               # 끄는 동안 위젯이 움직인다 — 화면 좌표로 옮긴다
    QTest.mousePress(b0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
    for k in (0.5, 1.0):
        QTest.mouseMove(b0, b0.mapFromGlobal(g0 + QPoint(int(40 * s_ * k), int(20 * s_ * k))))
    QTest.mouseRelease(b0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       b0.mapFromGlobal(g0 + QPoint(int(40 * s_), int(20 * s_))))
    spin(0.3)
    r1 = next(x for x in sdr.drafts(doc_path) if x["id"] == ds[0]["id"])["rect"]
    chk(abs(r1[0] - (ds[0]["rect"][0] + 40)) < 3 and abs(r1[1] - (ds[0]["rect"][1] + 20)) < 3
        and abs((r1[2] - r1[0]) - (ds[0]["rect"][2] - ds[0]["rect"][0])) < 1.5,
        "T4d 끌어 옮기기 — 크기 그대로 자리만", "%s → %s" % (ds[0]["rect"], r1))
    # 크기 — 오른쪽 아래 손잡이(그림 비율 유지)
    b0 = lay.box_for(ds[0]["id"])
    h0 = QPoint(b0.width() - 3, b0.height() - 3)
    QTest.mousePress(b0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, h0)
    QTest.mouseMove(b0, h0 + QPoint(int(30 * s_), 0))
    QTest.mouseMove(b0, h0 + QPoint(int(60 * s_), 0))
    QTest.mouseRelease(b0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, h0 + QPoint(int(60 * s_), 0))
    spin(0.3)
    r2 = next(x for x in sdr.drafts(doc_path) if x["id"] == ds[0]["id"])["rect"]
    ar1 = (r1[3] - r1[1]) / (r1[2] - r1[0])
    ar2 = (r2[3] - r2[1]) / (r2[2] - r2[0])
    chk(abs((r2[2] - r2[0]) - (r1[2] - r1[0] + 60)) < 3 and abs(ar1 - ar2) < 0.03,
        "T4e 모서리로 크기 — 그림 비율 유지", "%s → %s" % (r1, r2))
    # Delete — 넷째 자리를 놓고 지운다
    mw._sign_pending = str(doc_path); mw._sign_pending_mode = "sign"
    mw._on_sign_region(QRectF(300 * mv._zoom, 700 * mv._zoom, 400 * mv._zoom, 740 * mv._zoom), view=mv)
    spin(0.3)
    d4 = sdr.drafts(doc_path)[-1]
    b4 = lay.box_for(d4["id"])
    QTest.mouseClick(b4, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))
    QTest.keyClick(b4, Qt.Key.Key_Delete)
    spin(0.3)
    chk(len(sdr.drafts(doc_path)) == 3 and not any(x["id"] == d4["id"] for x in sdr.drafts(doc_path)),
        "T4f Delete 로 자리 지우기")

    # T5 — 일괄 확정
    out = src / "계약서_서명.pdf"
    before = sdr.drafts(doc_path)
    mv.sign_draft_band.btn_confirm.click()
    spin(2.0)
    chk(out.exists() and sha(doc_path) == orig_sha, "T5a [서명 확정] → '계약서_서명.pdf', 원본 바이트 그대로", str(list(src.iterdir())))
    rep = sc.verify_pdf(str(out), st.trusted())
    chk(len(rep.sigs) == 2 and rep.worst == sc.OK_TRUSTED, "T5b 전자서명 둘 — 모두 유효·신뢰함", str([(s.field, s.state) for s in rep.sigs]))
    od = fitz.open(str(out))
    n_img = len(od[0].get_images(full=True))
    ws = [w for w in od[0].widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE]
    od.close()
    chk(n_img >= 1 and len(ws) == 2, "T5c 그림만 자리는 쪽 내용 그림(서명 칸 아님)", "img=%d sig=%d" % (n_img, len(ws)))
    # 서명 영역 = 그림 상자 + 아래 글자 줄(옮긴 자리·키운 크기)
    w0 = min(ws, key=lambda w: abs(w.rect.x0 - r2[0]))
    chk(abs(w0.rect.x0 - r2[0]) < 1.5 and abs(w0.rect.y0 - r2[1]) < 1.5 and w0.rect.y1 > r2[3] + 5,
        "T5d 서명 자리 그대로 · 글자 줄은 그림 상자 아래", "%s vs %s" % (w0.rect, r2))
    chk(not sdr.drafts(doc_path) and (sdr.signed(out) or {}).get("base_len") == doc_path.stat().st_size,
        "T5e 확정한 자리는 원본에서 지우고 결과 파일 기록으로")
    chk(str(mw.main_view.current_file()) == str(out), "T5f 결과 파일을 연다", str(mw.main_view.current_file()))
    for _ in range(100):
        spin(0.05)
        if mw.main_view.sign_band.state not in ("", "checking"):
            break
    chk(mw.main_view.sign_band.btn_edit.isVisible(), "T5g 검증 띠에 [서명 편집](내 서명)")
    # 글꼴 폭 — /W 가 1000 단위(맑은 고딕 숫자 ≈ 551)
    import re
    raw_out = out.read_bytes()
    od = fitz.open(str(out))
    wv = []
    for x in range(1, od.xref_length()):
        try:
            t = od.xref_object(x)
        except Exception:
            continue
        if "/CIDFontType2" in t:
            wv += [int(v) for v in re.findall(r"\b(\d{3,4})\b", t.split("/W", 1)[1])[:20]] if "/W" in t else []
    od.close()
    chk(wv and max(wv) <= 1100, "T3c 겉모양 글꼴 /W 폭이 1000 단위(종전 2048 단위로 약 2배 넓게 찍혀 잘렸다)", str(wv[:10]))

    # T6 — 서명 편집 → 원본에 자리 되살림 → 옮겨 다시 확정 → [바꾸기]
    mw.action_sign_edit(); spin(1.0)
    chk(str(mw.main_view.current_file()) == str(doc_path) and len(sdr.drafts(doc_path)) == 3
        and sdr.out_of(doc_path) == str(out), "T6a 서명 편집 → 기록의 원본을 열고 자리 셋을 되살림",
        str((mw.main_view.current_file(), len(sdr.drafts(doc_path)))))
    mv = mw.main_view
    ds = sdr.drafts(doc_path)
    tgt = next(x for x in ds if x["kind"] == "sign")
    r = tgt["rect"]
    mw._sign_draft_moved(mv, tgt["id"], (r[0], r[1] + 100, r[2], r[3] + 100))
    picked["text"] = "바꾸기"
    mv.sign_draft_band.btn_confirm.click()
    spin(2.0)
    rep2 = sc.verify_pdf(str(out), st.trusted())
    od = fitz.open(str(out))
    ys = sorted(round(w.rect.y0) for w in od[0].widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE)
    od.close()
    chk(len(rep2.sigs) == 2 and rep2.worst == sc.OK_TRUSTED and any(abs(y - (r[1] + 100)) < 2 for y in ys)
        and sha(doc_path) == orig_sha and not list(src.glob("*서명전*")),
        "T6b 옮겨 다시 확정 → [바꾸기] 로 서명 파일이 바뀌고 유효·원본 그대로", str((ys, r[1] + 100)))

    # T7 — 기록 없는 서명 파일 편집 → `<이름>_서명전.pdf`
    cp = src / "사본.pdf"
    shutil.copy(out, cp)
    mw.open_pdfs([str(cp)]); spin(1.0)
    mw.action_sign_edit(); spin(1.0)
    base = src / "사본_서명전.pdf"
    chk(base.exists() and str(mw.main_view.current_file()) == str(base) and len(sdr.drafts(base)) == 2
        and sdr.out_of(base) == str(cp), "T7a 기록 없음 → 바탕 '사본_서명전.pdf'(앞 판까지 자름)·전자서명 자리 둘",
        str((base.exists(), len(sdr.drafts(base)) if base.exists() else None)))
    if base.exists():
        bd = fitz.open(str(base))
        chk(not sc.doc_is_signed(bd) and len(bd[0].get_images(full=True)) >= 1, "T7b 바탕은 서명 없음 · 확정 때 넣은 그림은 남음")
        bd.close()

    # T8 — 다른 사람 서명이 뒤에 있으면 거부
    pfx2, info2 = sc.create_id("김철수", PW)
    two = src / "둘.pdf"
    sc.sign_pdf(str(out), str(two), pfx2, PW, page_index=2, box_pdf=(50, 50, 200, 100), appearance=sc.Appearance(font_path=sc.default_font()))
    mw.open_pdfs([str(two)]); spin(1.0)
    infos.clear()
    mw.action_sign_edit(); spin(0.5)
    chk(any("다른 사람" in str(t) for t in infos) and str(mw.main_view.current_file()) == str(two),
        "T8 다른 사람 서명이 뒤에 있으면 서명 편집을 거부", str(infos))

    # T9 — 회전한 쪽 그림만: 끈 상자 안에 바로 선다(왼쪽 위 표식이 왼쪽 위)
    rot_out = tmp / "rot.pdf"
    sc.insert_images(str(doc_path), str(rot_out), [(1, (100, 300, 300, 380), st.image_path("기본"))])
    rd = fitz.open(str(rot_out))
    pix = rd[1].get_pixmap(dpi=72)
    s_, n_ = pix.samples, pix.n
    red = [(x, y) for y in range(pix.height) for x in range(pix.width)
           if s_[(y * pix.width + x) * n_] > 150 and s_[(y * pix.width + x) * n_ + 1] < 90 and s_[(y * pix.width + x) * n_ + 2] < 90]
    rd.close()
    cx = sum(p[0] for p in red) / max(1, len(red)); cy = sum(p[1] for p in red) / max(1, len(red))
    chk(red and 100 <= cx <= 150 and 300 <= cy <= 330 and rot_out.read_bytes()[:doc_path.stat().st_size] == doc_path.read_bytes(),
        "T9 회전 90° 쪽 그림만 — 끈 상자 왼쪽 위에 표식·앞 바이트 그대로(증분)", str((cx, cy)))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAIL %d ===\n  " % len(fails) + "\n  ".join(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
