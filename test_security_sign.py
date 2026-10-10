# -*- coding: utf-8 -*-
"""261010-21: 전자서명 1단계 (보안 SOT `문서 보안(암호·전자서명) 작업 계획서.md` §3~§6·§11).

A. 핵심 — 디지털 ID 만들기(PBES2-AES256 .pfx)·틀린 비밀번호·가져오기(옛 3DES .pfx → 우리 형식),
   증분 서명 → 검증 '유효·신원 미확인' / 지문 신뢰 → '신뢰함' / 서명 하나 더 → 둘 다 유효 /
   서명 뒤 증분 수정 → '변경됨' / 전체 다시 쓰기·바이트 변조 → '무효' / 암호 문서 서명(암호 유지)
   / MediaBox 원점이 0 이 아닌 쪽에 끈 자리 그대로 / 서명 판정(열린 문서·파일)
B. 서명 그림 — 종이 사진에서 배경 지우기·잉크 경계 자르기, 투명 PNG 는 그대로
C. Windows Hello 보관(가짜 키) — 보관·꺼내기·지우기, 취소, ID 지우면 보관값도
D. 실제 MainWindow — 도구 메뉴 '🔏 전자서명' 구역·크롭 오른쪽 단추, 단추 → 본문 끌기 → 서명 창 → 현재 파일에 서명 → 다시 열면 검증 띠
E. 저장 가드(§4) — 서명된 파일에 `_finalize_save`: 새 파일로 / 취소 / 덮어쓰기, 서명 자체 저장은 묻지 않는다
G. 대화상자 — 디지털 ID 창·서명 그림 창·서명 패널
H. 서명 창 겉모양 미리보기 — 끈 상자 비율·배경에서·바꾸면 다시(S8)
I. 본문 우클릭 '여기에 서명…' — 실제 메뉴 처리기, 누른 자리에 기본 크기(S6)
F. 비밀번호가 설정·ID 목록·Hello 보관 파일 어디에도 평문으로 없다(§6.4)
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["POLYPDF_FAKE_HELLO"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QRectF
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_sign_%d" % os.getpid())
from viewer import sign_core as sc, sign_store as st, sign_hello as sh

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


def font_path():
    return sc.default_font()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_sign_"))
try:
    # ── A. 핵심 ─────────────────────────────────────────────
    src = tmp / "doc.pdf"
    d = fitz.open()
    p0 = d.new_page(); p0.insert_text((72, 72), "Hello signed world")
    p1 = d.new_page(); p1.set_mediabox(fitz.Rect(10, 20, 610, 820)); p1.insert_text((80, 80), "Page two")
    d.save(str(src)); d.close()

    pfx, info = sc.create_id("홍길동", PW, email="hong@example.com", org="PolyPDF")
    chk(len(info.fp) == 64 and info.name == "홍길동", "A1 디지털 ID 를 만든다(이름·지문)", str(info))
    try:
        sc.load_pfx(pfx, "wrong-password")
        chk(False, "A2 틀린 비밀번호는 WrongPassword")
    except sc.WrongPassword as e:
        chk(PW not in str(e) and "wrong-password" not in repr(e), "A2 틀린 비밀번호는 WrongPassword(메시지에 비밀번호 없음)")
    # 옛 형식(.pfx 3DES — 다른 도구가 흔히 만드는 것)을 가져오면 우리 형식으로 다시 잠근다
    from cryptography.hazmat.primitives.serialization import pkcs12, BestAvailableEncryption
    key, cert, _ = sc.load_pfx(pfx, PW)
    legacy = pkcs12.serialize_key_and_certificates(b"x", key, cert, None, BestAvailableEncryption(PW.encode()))
    norm, info2 = sc.normalize_pfx(legacy, PW)
    chk(info2.fp == info.fp and sc.pfx_info(norm, PW).fp == info.fp, "A3 .pfx 가져오기 — 같은 인증서, 다시 잠가도 같은 비밀번호")

    signed = tmp / "signed.pdf"
    doc = fitz.open(str(src))
    want = fitz.Rect(100, 100, 300, 175)
    box = sc.page_box_to_pdf(doc[1], want)
    doc.close()
    app_ = sc.Appearance(font_path=font_path(), show_reason=True)
    name = sc.sign_pdf(str(src), str(signed), pfx, PW, page_index=1, box_pdf=box, appearance=app_, reason="승인")
    chk(name == "Signature1", "A4 증분 서명 — 필드 이름 Signature1", name)
    raw_src = src.read_bytes()
    chk(signed.read_bytes().startswith(raw_src), "A4 증분 저장 — 원본 바이트 뒤에 덧붙였다")
    sd = fitz.open(str(signed))
    rects = [w.rect for w in sd[1].widgets()]
    chk(rects and abs(rects[0].x0 - want.x0) < 0.5 and abs(rects[0].y0 - want.y0) < 0.5,
        "A5 MediaBox 원점이 0 이 아닌 쪽에서도 끈 자리 그대로", str(rects))
    chk(sc.doc_is_signed(sd) and sc.is_signed_file(signed) and not sc.is_signed_file(src), "A6 서명 판정(열린 문서·파일)")
    sd.close()

    rep = sc.verify_pdf(str(signed))
    chk(rep.worst == sc.OK_UNKNOWN and rep.sigs[0].signer == "홍길동" and rep.sigs[0].reason == "승인",
        "A7 검증 — 신뢰 목록에 없으면 '유효·신원 미확인'", str(rep))
    chk(sc.verify_pdf(str(signed), [info.fp]).worst == sc.OK_TRUSTED, "A8 지문을 신뢰하면 '유효·신뢰함'")

    two = tmp / "two.pdf"
    sd = fitz.open(str(signed))
    sc.sign_pdf(str(signed), str(two), pfx, PW, page_index=0, box_pdf=sc.page_box_to_pdf(sd[0], fitz.Rect(50, 300, 200, 360)),
                appearance=sc.Appearance(font_path=font_path()))
    sd.close()
    r2 = sc.verify_pdf(str(two), [info.fp])
    chk([s.state for s in r2.sigs] == [sc.OK_TRUSTED, sc.OK_TRUSTED], "A9 서명을 하나 더 — 앞 서명도 유효(허용된 변경)",
        str([(s.field, s.state, s.modification) for s in r2.sigs]))

    inc = tmp / "incr.pdf"
    shutil.copy(signed, inc)
    di = fitz.open(str(inc)); di[0].insert_text((72, 300), "tampered"); di.saveIncr(); di.close()
    chk(sc.verify_pdf(str(inc), [info.fp]).worst == sc.MODIFIED, "A10 서명 뒤 내용을 덧붙여 고치면 '변경됨'")
    rw = tmp / "rewrite.pdf"
    dr = fitz.open(str(signed)); dr.save(str(rw), garbage=4, deflate=True); dr.close()
    chk(sc.verify_pdf(str(rw), [info.fp]).worst == sc.INVALID, "A11 PolyPDF 식 전체 저장은 서명을 깬다 → '무효'")
    b = bytearray(signed.read_bytes()); i = b.find(b"Hello"); b[i] = ord("J")
    tam = tmp / "tamper.pdf"; tam.write_bytes(bytes(b))
    chk(sc.verify_pdf(str(tam), [info.fp]).worst == sc.INVALID, "A12 바이트 변조 → '무효'")

    enc = tmp / "enc.pdf"; encs = tmp / "enc_signed.pdf"
    de = fitz.open(str(src))
    de.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="own-pw", user_pw="usr-pw", permissions=-1); de.close()
    try:
        sc.sign_pdf(str(enc), str(encs), pfx, PW, page_index=0, box_pdf=(100, 600, 300, 680),
                    appearance=sc.Appearance(font_path=font_path()), doc_password="own-pw")
        ok = True
    except Exception as e:
        ok = False; print("   ", e)
    de = fitz.open(str(encs)) if ok else None
    chk(ok and de.needs_pass and de.authenticate("usr-pw") and sc.doc_is_signed(de)
        and sc.verify_pdf(str(encs), [info.fp], "usr-pw").worst == sc.OK_TRUSTED,
        "A13 암호 문서(AES-256, PyMuPDF 로 암호화)에 서명 — 암호 유지·서명 유효")
    if de:
        de.close()
    try:
        sc.sign_pdf(str(enc), str(tmp / "x.pdf"), pfx, PW, page_index=0, box_pdf=(1, 1, 50, 50))
        chk(False, "A14 암호를 모르면 서명하지 않는다")
    except sc.SignError as e:
        chk(e.reason == "need_doc_password", "A14 암호를 모르면 서명하지 않는다", e.reason)

    # ── B. 서명 그림 ─────────────────────────────────────────
    from PIL import Image, ImageDraw
    photo = Image.new("RGB", (900, 400), (236, 231, 214))
    ImageDraw.Draw(photo).line((60, 300, 840, 90), fill=(25, 25, 70), width=16)
    out = sc.clean_signature(photo, ink="blue")
    a = out.getchannel("A")
    chk(out.mode == "RGBA" and a.getpixel((2, 2)) == 0 and sc.ink_bbox(out) is not None,
        "B1 종이 사진 → 배경 투명·잉크 남음", str(a.getextrema()))
    chk(out.width < 900 and out.height < 400, "B2 잉크 경계로 잘랐다", str(out.size))
    t = Image.new("RGBA", (200, 80), (0, 0, 0, 0)); ImageDraw.Draw(t).line((5, 70, 195, 10), fill=(0, 0, 0, 255), width=6)
    chk(sc.has_transparency(t) and sc.ink_bbox(sc.clean_signature(t)) is not None, "B3 이미 투명한 PNG 는 배경 지우기를 건너뛴다")

    # ── C. Windows Hello(가짜 키) ──────────────────────────────
    e = st.add_id(pfx, info)
    chk(st.get_id(info.fp)["file"].startswith("ids/") and info.fp in st.trusted(), "C1 ID 보관 — 상대 경로·내 ID 는 자동 신뢰")
    sh.store(info.fp, PW)
    chk(sh.has(info.fp) and sh.recall(info.fp) == PW, "C2 Hello 로 잠가 보관 → 꺼내기")
    os.environ["POLYPDF_FAKE_HELLO"] = "cancel"
    try:
        sh.recall(info.fp); chk(False, "C3 Hello 취소 → HelloCancelled")
    except sh.HelloCancelled:
        chk(True, "C3 Hello 취소 → HelloCancelled")
    os.environ["POLYPDF_FAKE_HELLO"] = "1"
    st.set_id_flag(info.fp, hello=True)

    # ── F. 평문 비밀번호가 없다 ───────────────────────────────
    blobs = b""
    for f in st.root().rglob("*"):
        if f.is_file():
            blobs += f.read_bytes()
    chk(PW.encode() not in blobs, "F1 설정 폴더 signing\\ 어디에도 평문 비밀번호 없음")

    # ── D. 실제 MainWindow ─────────────────────────────────────
    from viewer.app import MainWindow
    import viewer.widgets.sign_dialogs as sdlg
    root = tmp / "folder"; root.mkdir()
    doc_path = root / "계약서.pdf"
    shutil.copy(src, doc_path)
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(1.0)
    mv = mw.main_view
    chk(str(mv.current_file()) == str(doc_path), "D0 문서를 열었다")
    labels = []
    for act in mw.menuBar().actions():
        if act.text().startswith("도구"):
            labels = [a.text() for a in act.menu().actions()]
    chk("🔏 전자서명" in labels and "서명..." in labels and "디지털 ID..." in labels, "D1 도구 메뉴에 '🔏 전자서명' 구역", str(labels[-6:]))
    chk(not mv.sign_band.isVisible(), "D2 서명 없는 문서에는 검증 띠가 없다")

    picked = {}
    orig_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next((b for b in self.buttons() if picked.get("text") and picked["text"] in b.text()), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3] if len(a) > 2 else a))

    class _FakeSignDialog(sdlg.SignDialog):
        mode = "hello"

        def exec(self):
            if _FakeSignDialog.mode == "hello":
                self._hello()
            else:
                self.ed_pw.setText(PW)
                self._sign()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _FakeSignDialog
    tb = [mv._toolbar_widget.layout().itemAt(i).widget() for i in range(mv._toolbar_widget.layout().count())]
    chk(mv.btn_crop in tb and tb.index(mv.btn_sign) == tb.index(mv.btn_crop) + 1 and not mv.btn_sign.icon().isNull(),
        "D1b 본문 툴바 — 크롭 오른쪽에 전자서명 단추(아이콘)")
    picked["text"] = "그림 없이"
    mv.btn_sign.click()                     # 실제 단추로 — 도구 메뉴 '서명...' 과 같은 길
    chk(getattr(mv.view, "_block_purpose", "") == "sign" and mv.view._block_armed, "D3 '서명' → 본문 끌기 무장(서명 자리)")
    mv.go_to_page(0); spin(0.3)
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(100 * z, 400 * z, 300 * z, 470 * z))
    spin(1.5)
    chk(sc.is_signed_file(doc_path), "D4 서명 창(Windows Hello) → 현재 파일에 서명됐다")
    rep = sc.verify_pdf(str(doc_path), st.trusted())
    chk(rep.worst == sc.OK_TRUSTED, "D5 현재 파일 서명 유효·신뢰함(내 ID)", str(rep))
    for _ in range(100):
        spin(0.05)
        if mv.sign_band.state not in ("", "checking"):
            break
    chk(mv.sign_band.isVisible() and mv.sign_band.state == sc.OK_TRUSTED, "D6 다시 열면 검증 띠 — 신뢰함", mv.sign_band.state)
    chk(not list(root.glob("~*.polypdf-sign")), "D7 서명 임시 파일이 남지 않았다")

    # ── E. 저장 가드 ───────────────────────────────────────────
    from viewer.file_overwrite import SaveCancelled

    def produced():
        p = root / ("~prod_%d.tmp" % time.time_ns())
        dd = fitz.open(str(src)); dd.save(str(p)); dd.close()
        return p
    picked["text"] = "새 파일로"
    out1 = mw._finalize_save(str(doc_path), str(produced()))
    chk(Path(out1) != doc_path and Path(out1).exists() and sc.verify_pdf(str(doc_path), st.trusted()).worst == sc.OK_TRUSTED,
        "E1 서명된 파일에 저장 → '새 파일로' 면 원본 서명은 그대로", out1)
    picked["text"] = "취소"
    pr = produced()
    try:
        mw._finalize_save(str(doc_path), str(pr)); chk(False, "E2 취소 → SaveCancelled")
    except SaveCancelled:
        chk(sc.is_signed_file(doc_path) and not pr.exists(), "E2 취소 → SaveCancelled, 원본·임시 정리")
    picked["text"] = "덮어쓰기"
    out3 = mw._finalize_save(str(doc_path), str(produced()))
    chk(Path(out3) == doc_path and not sc.is_signed_file(doc_path), "E3 '서명을 무효로 하고 덮어쓰기' 를 고르면 덮어쓴다")
    picked["text"] = ""
    out4 = mw._finalize_save(str(doc_path), str(produced()))
    chk(Path(out4) == doc_path, "E4 서명 없는 파일은 묻지 않고 덮어쓴다")

    # 비밀번호 칸 경로(2순위·직접 입력)도 — Hello 를 못 쓰는 PC 처럼
    os.environ["POLYPDF_FAKE_HELLO"] = ""
    sh._cached_available = False
    _FakeSignDialog.mode = "password"
    mw._open_saved_file(str(doc_path)); spin(0.6)
    picked["text"] = "그림 없이"
    mw.action_sign_pdf()
    mv = mw.main_view
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(150 * z, 500 * z, 1, 1))    # 클릭만 — 기본 크기
    spin(1.5)
    dd = fitz.open(str(doc_path))
    ws = [w.rect for w in dd[0].widgets()]
    dd.close()
    chk(sc.is_signed_file(doc_path) and ws and abs(ws[0].width - sc_w) < 1 if (sc_w := 50 / 25.4 * 72) else False,
        "E5 비밀번호를 넣어 서명(Hello 없는 PC) · 클릭만 하면 폭 50mm", str(ws))

    # ── G. 대화상자가 실제로 뜨고 일한다 ───────────────────────────
    idd = sdlg.DigitalIdDialog(mw, runner=mw._sign_bg, hello_ok=True)
    chk(idd.lst.count() == 1 and "Windows Hello" in idd.lst.item(0).text() and idd.b_hello.isVisible() is not None,
        "G1 디지털 ID 창 — 목록·Hello 표시", idd.lst.item(0).text() if idd.lst.count() else "")
    idd.close()
    imd = sdlg.SignImageDialog(mw)
    imd.set_source(photo)
    chk(imd._btn_save.isEnabled(), "G2 서명 그림 창 — 사진을 넣으면 저장할 수 있다")
    imd.ed_name.setText("기본"); imd._save()
    chk(st.image_path("기본") and Path(st.image_path("기본")).exists(), "G3 서명 그림 저장(signing\\images)")
    pan = sdlg.SignPanelDialog(mw, sc.verify_pdf(str(two), [info.fp]))
    chk(pan.lst.count() == 2 and "홍길동" in pan.detail.text() and "PC" in pan.detail.text(), "G4 서명 패널 — 목록·상세(PC 시계 기준 문구)")
    pan.close()
    # 두 번째 서명 문서 — 앞서 검증 스레드가 끝난 뒤 다시 검증해도 띠가 갱신된다(지워진 스레드를 만지던 것)
    shutil.copy(two, root / "shot.pdf")
    mw._open_saved_file(str(root / "shot.pdf"))
    for _ in range(200):
        spin(0.05)
        if mw.main_view.sign_band.state not in ("", "checking"):
            break
    chk(mw.main_view.sign_band.state == sc.OK_TRUSTED, "G5 두 번째로 연 서명 문서도 검증 띠가 결과로 바뀐다",
        mw.main_view.sign_band.state)
    if os.environ.get("POLYPDF_SHOT"):
        mw.grab().save(os.environ["POLYPDF_SHOT"])

    # ── H. 서명 창 겉모양 미리보기(S8) — 실제 서명과 같은 그리기, 배경에서, 바꾸면 다시 ──
    from PIL import Image as _I
    _RealSign = sdlg.SignDialog.__mro__[1] if sdlg.SignDialog.__name__ == "_FakeSignDialog" else sdlg.SignDialog
    sd = _RealSign(mw, hello_ok=False, file_name="x.pdf", box_size=(200.0, 75.0))

    def _wait_pv(prev_key=None, sec=8.0):
        t0 = time.time()
        while time.time() - t0 < sec:
            spin(0.05)
            pm = sd.preview.pixmap()
            if pm is not None and not pm.isNull() and pm.cacheKey() != prev_key and not sd._pv_threads and not sd._pv_timer.isActive():
                return pm
        return None
    pm1 = _wait_pv()
    def _dark(pm):
        q = pm.toImage().convertToFormat(pm.toImage().Format.Format_RGB888)
        b = bytes(q.constBits().asarray(q.sizeInBytes()))
        return sum(1 for i in range(0, len(b), 3) if b[i] < 128) if b else 0
    chk(pm1 is not None and abs(pm1.width() / max(1, pm1.height()) - 200 / 75) < 0.1 and _dark(pm1) > 50,
        "H1 미리보기 — 끈 상자 비율로 그려지고 글자가 보인다(배경에서)", str(pm1.size() if pm1 else None))
    sd.chk_reason.setChecked(True); sd.ed_reason.setText("검토 완료")
    pm2 = _wait_pv(pm1.cacheKey() if pm1 else None)
    chk(pm2 is not None and _dark(pm2) > _dark(pm1 or pm2), "H2 사유를 켜고 넣으면 다시 그린다(글자가 늘어남)",
        "%s → %s" % (_dark(pm1) if pm1 else None, _dark(pm2) if pm2 else None))
    sd.stop_preview(); sd.close()

    # ── I. 본문 우클릭 '여기에 서명…'(S6) — 실제 메뉴 처리기로, 누른 자리가 가운데인 기본 크기 ──
    from PyQt6.QtWidgets import QMenu
    here = root / "우클릭.pdf"
    shutil.copy(src, here)
    mw.open_pdfs([str(here)]); spin(0.8)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.3)
    z = mv._zoom or 1.0
    want_pt = (200.0, 300.0)                          # 쪽 좌표(pt)
    gpos = mv.view.viewport().mapToGlobal(mv.view.mapFromScene(want_pt[0] * z, want_pt[1] * z))
    _orig_menu_exec = QMenu.exec
    labels_seen = []

    def _pick_sign_here(self, *a, **k):
        labels_seen.extend(x.text() for x in self.actions())
        return next((x for x in self.actions() if x.text() == "여기에 서명…"), None)
    QMenu.exec = _pick_sign_here
    picked["text"] = "그림 없이"
    try:
        mw._on_viewer_context_menu(gpos); spin(1.5)
    finally:
        QMenu.exec = _orig_menu_exec
    chk("여기에 서명…" in labels_seen, "I1 본문 우클릭 메뉴에 '여기에 서명…'", str(labels_seen[:8]))
    dh = fitz.open(str(here))
    ws = [w.rect for w in dh[0].widgets()]
    dh.close()
    cx = (ws[0].x0 + ws[0].x1) / 2 if ws else -1
    cy = (ws[0].y0 + ws[0].y1) / 2 if ws else -1
    chk(sc.is_signed_file(here) and abs(cx - want_pt[0]) < 3 and abs(cy - want_pt[1]) < 3
        and abs(ws[0].width - 50 / 25.4 * 72) < 1,
        "I2 끌기 없이 누른 자리를 가운데로 기본 크기(폭 50mm) 서명", str(ws))
    QMessageBox.exec = orig_exec
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
