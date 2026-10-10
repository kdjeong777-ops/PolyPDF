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
J. 책갈피창 서명 표식(S1) · K. 서명 문서 암호화 안내(S9) · L. 제거·업데이트가 signing 을 지우지 않음(S3) · M. 서명·저장 뒤 암호 옮기기(§7.2·S11)
N. 2단계 — 여러 쪽·인증·타임스탬프·글자 배치·서명 시점 판·손으로 그리기(§3.6)
O. 3단계 빈 서명 칸 — 만들기·찾기·채우기(인증 문서 포함)·실제 흐름·검증 띠(§3.7)
P. 3단계 공동인증서 — 같은 형식으로 만든 가짜 signCert.der/signPri.key 풀기·거부·가져와 서명(§3.8)
Q. 3단계 Windows 인증서 저장소 — 가짜 저장소로 목록·참조 보관·키 없이 서명·취소·사라짐(§3.9)
F. 비밀번호가 설정·ID 목록·Hello 보관 파일 어디에도 평문으로 없다(§6.4)
R. 검토 보완(261011-1) — 책갈피 '현재 PDF에 저장' 도 서명 가드·signing.json 잠김은 깨진 목록이 아니다·.pfx 체인 유지·읽기 전용 폴더 임시 파일
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


def make_npki(folder, password, scheme="seed_sha1", days=365, key=None, cert_key=None, prf="sha256"):
    """국내 공동인증서와 같은 꼴의 가짜 signCert.der/signPri.key (보안 SOT §3.8) — PKCS#8 randomNum 속성 포함."""
    import hashlib, datetime as _dt
    from asn1crypto import core, keys as akeys
    from cryptography import x509 as _x
    from cryptography.x509.oid import NameOID as _N
    from cryptography.hazmat.primitives import hashes as _h, serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from viewer import sign_npki as sn
    os.makedirs(folder, exist_ok=True)
    key = key or _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.now(_dt.timezone.utc)
    sub = _x.Name([_x.NameAttribute(_N.COUNTRY_NAME, "KR"), _x.NameAttribute(_N.ORGANIZATION_NAME, "yessign"),
                   _x.NameAttribute(_N.COMMON_NAME, "홍길동()0001234567890123")])
    iss = _x.Name([_x.NameAttribute(_N.COUNTRY_NAME, "KR"), _x.NameAttribute(_N.ORGANIZATION_NAME, "yessign"),
                   _x.NameAttribute(_N.COMMON_NAME, "yessignCA Class 2")])
    nb, na = (now - _dt.timedelta(days=10), now + _dt.timedelta(days=days)) if days > 0 else \
        (now - _dt.timedelta(days=400), now - _dt.timedelta(days=1))
    cert = (_x.CertificateBuilder().subject_name(sub).issuer_name(iss).public_key((cert_key or key).public_key())
            .serial_number(1234).not_valid_before(nb).not_valid_after(na)
            .add_extension(_x.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                       data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                       encipher_only=False, decipher_only=False), critical=True)
            .sign(ca, _h.SHA256()))
    open(os.path.join(folder, "signCert.der"), "wb").write(cert.public_bytes(_ser.Encoding.DER))

    def _len(n):
        if n < 128:
            return bytes([n])
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return bytes([0x80 | len(b)]) + b
    p8 = akeys.PrivateKeyInfo.load(key.private_bytes(_ser.Encoding.DER, _ser.PrivateFormat.PKCS8, _ser.NoEncryption()))
    rnd = core.Sequence(contents=core.ObjectIdentifier("1.2.410.200004.10.1.1.3").dump()
                        + core.SetOf(contents=core.BitString((0,) * 160).dump()).dump()).dump()
    body = p8["version"].dump() + p8["private_key_algorithm"].dump() + p8["private_key"].dump()
    attr = bytes([0xA0]) + _len(len(rnd)) + rnd
    plain = bytes([0x30]) + _len(len(body) + len(attr)) + body + attr
    pad = 16 - len(plain) % 16
    plain += bytes([pad]) * pad
    salt, it, pw = os.urandom(8), 2048, password.encode()
    if scheme == "seed_sha1":
        dk = sn._pbkdf1_sha1(pw, salt, it, 20)
        k, iv = dk[:16], hashlib.sha1(dk[16:20]).digest()[:16]
        alg = core.Sequence(contents=core.ObjectIdentifier(sn.OID_SEED_SHA1).dump()
                            + core.Sequence(contents=core.OctetString(salt).dump() + core.Integer(it).dump()).dump())
    else:
        iv = os.urandom(16)
        k = hashlib.pbkdf2_hmac(prf, pw, salt, it, 16)
        kp = core.OctetString(salt).dump() + core.Integer(it).dump()
        if prf != "sha1":
            kp += core.Sequence(contents=core.ObjectIdentifier("1.2.840.113549.2.9").dump() + core.Null().dump()).dump()
        kdf = core.Sequence(contents=core.ObjectIdentifier(sn.OID_PBKDF2).dump() + core.Sequence(contents=kp).dump())
        enc = core.Sequence(contents=core.ObjectIdentifier(sn.OID_SEED_CBC).dump() + core.OctetString(iv).dump())
        alg = core.Sequence(contents=core.ObjectIdentifier(sn.OID_PBES2).dump()
                            + core.Sequence(contents=kdf.dump() + enc.dump()).dump())
    ct = sn._seed(k, iv, plain, decrypt=False)
    open(os.path.join(folder, "signPri.key"), "wb").write(
        core.Sequence(contents=alg.dump() + core.OctetString(ct).dump()).dump())
    return cert, key


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

    # ── J. 책갈피창 서명 표식(S1) — probe_cache.signed, 옛 index.db 에 열 더하기, 파일 행 아이콘·툴팁 ──
    import sqlite3
    from viewer.indexer import PdfIndex
    old_db = tmp / "old_index.db"
    con = sqlite3.connect(str(old_db))
    con.execute("CREATE TABLE probe_cache(key TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL,"
                " encrypted INTEGER NOT NULL, has_toc INTEGER, auth TEXT)")
    con.commit(); con.close()
    ix = PdfIndex(old_db)
    cols = {r[1] for r in ix.conn.execute("PRAGMA table_info(probe_cache)").fetchall()}
    chk("signed" in cols, "J1 옛 index.db 의 probe_cache 에 signed 열을 더한다", str(cols))
    ix.index_file(two)
    st2 = two.stat()
    got = ix.probe_get(two, st2.st_size, st2.st_mtime)
    chk(got is not None and got[3] is True, "J2 인덱싱이 서명 표식도 함께 적는다", str(got))
    ix.close()
    bt = mw.bookmark_tree
    signed_item = plain_item = None
    for it in bt._iter_file_nodes():
        f = str(it.data(0, bt.DATA_FILE) or "")
        if f.endswith("우클릭.pdf"):
            signed_item = it
        elif f.endswith("shot.pdf") is False and f.endswith("계약서.pdf"):
            plain_item = it
    if signed_item is not None:
        bt._probe_cache = {}
        bt._ensure_probed(signed_item, force=True)
    chk(signed_item is not None and bool(signed_item.data(0, bt.DATA_SIGNED))
        and "전자서명" in (signed_item.toolTip(0) or "")
        and signed_item.icon(0).pixmap(16, 16).toImage() == bt._signed_icon().pixmap(16, 16).toImage(),
        "J3 서명된 파일 행 — 표식·`sign` 아이콘·툴팁", signed_item.toolTip(0) if signed_item else "없음")
    bt.refresh_icons()
    chk(signed_item is not None and signed_item.icon(0).pixmap(16, 16).toImage() == bt._signed_icon().pixmap(16, 16).toImage(),
        "J4 테마를 바꿔 아이콘을 다시 칠해도 서명 아이콘을 지킨다")

    # ── K. 서명된 문서 암호화(S9) — 먼저 알리고, '아니요' 면 암호화 창을 열지 않는다 ──
    import viewer.widgets.encrypt_dialog as _ed
    asked, opened = [], []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.No)[1])
    _orig_ed_exec = _ed.EncryptDialog.exec
    _ed.EncryptDialog.exec = lambda self: (opened.append(1), 0)[1]
    mw._open_saved_file(str(here)); spin(0.6)
    mw.action_encrypt_pdf()
    _ed.EncryptDialog.exec = _orig_ed_exec
    chk(any("서명" in m for m in asked) and not opened, "K1 서명된 문서를 암호화하려 하면 먼저 묻고, '아니요' 면 멈춘다", str(asked[-1:]))

    # ── L. 제거·업데이트가 signing\ 을 지우지 않는다(S3) — 정적 확인 ──
    iss = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer", "PolyPDF.iss"), encoding="utf-8").read()
    ud = iss.split("[UninstallDelete]", 1)[1].split("\n[", 1)[0]
    ud_lines = [x.strip() for x in ud.splitlines() if x.strip() and not x.strip().startswith(";")]
    chk(ud_lines == ['Type: filesandordirs; Name: "{app}"'], "L1 제거 프로그램은 설치 폴더만 지운다(설정 폴더 signing\\ 은 남는다)", str(ud_lines))
    upd = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer", "updater.py"), encoding="utf-8").read()
    chk("StartsWith('_internal\\'" in upd, "L2 앱 안 업데이트 정리는 _internal\\ 아래만(휴대용 Data\\ 는 건드리지 않는다)")
    from viewer.settings_store import settings_dir, app_base_dir
    chk(str(st.root()).startswith(str(settings_dir())) and not str(st.root()).startswith(str(app_base_dir())),
        "L3 서명 자료는 설정 폴더 아래(프로그램 폴더 밖)", str(st.root()))

    # ── M. 암호 문서 서명 뒤 암호를 서명한 파일로 옮긴다(크기가 바뀌어 기억 키가 바뀜, §7.2) ──
    from viewer import secure_store as _ss
    from viewer.sign_controller import SignMixin
    epath = root / "암호.pdf"
    shutil.copy(enc, epath)
    _ss.set_session(epath, "usr-pw")
    with open(epath, "ab") as fh:
        fh.write(b"\n%grow\n")                       # 서명처럼 크기가 는다
    before = _ss.recall_any(epath)
    SignMixin._sign_carry_password(str(epath), "usr-pw", False)
    chk(before is None and _ss.recall_any(epath) == "usr-pw", "M1 크기가 바뀐 서명 파일에도 세션 암호가 따라온다", str(before))
    # M2(S11): 서명 밖의 저장도 — 실제 `_finalize_save` 로 크기가 다른 판을 덮어써도 암호가 따라온다
    e2 = root / "암호2.pdf"
    shutil.copy(enc, e2)
    _ss.set_session(e2, "usr-pw")
    prod = root / "~prod_enc.tmp"
    shutil.copy(enc, prod)
    with open(prod, "ab") as fh:
        fh.write(b"\n%different size\n")
    picked["text"] = ""
    out_e2 = mw._finalize_save(str(e2), str(prod))
    chk(Path(out_e2) == e2 and e2.stat().st_size != enc.stat().st_size and _ss.recall_any(e2) == "usr-pw",
        "M2 `_finalize_save` 로 크기가 바뀐 암호 PDF 도 다시 열 때 암호를 묻지 않는다(세션 암호가 따라온다)")

    # ── N. 2단계(보안 SOT §3.6) ─────────────────────────────────────────
    import datetime as _dt, io as _io
    from cryptography import x509 as _x
    from cryptography.x509.oid import NameOID as _N, ExtendedKeyUsageOID as _E
    from cryptography.hazmat.primitives import hashes as _h, serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from asn1crypto import x509 as _ax, keys as _ak
    from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
    _tk = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _tn = _x.Name([_x.NameAttribute(_N.COMMON_NAME, "Test TSA")])
    _now = _dt.datetime.now(_dt.timezone.utc)
    _tc = (_x.CertificateBuilder().subject_name(_tn).issuer_name(_tn).public_key(_tk.public_key()).serial_number(7)
           .not_valid_before(_now - _dt.timedelta(days=1)).not_valid_after(_now + _dt.timedelta(days=30))
           .add_extension(_x.ExtendedKeyUsage([_E.TIME_STAMPING]), critical=True).sign(_tk, _h.SHA256()))
    tsa = DummyTimeStamper(tsa_cert=_ax.Certificate.load(_tc.public_bytes(_ser.Encoding.DER)),
                           tsa_key=_ak.PrivateKeyInfo.load(_tk.private_bytes(_ser.Encoding.DER, _ser.PrivateFormat.PKCS8,
                                                                             _ser.NoEncryption())))
    three = tmp / "three.pdf"
    _d3 = fitz.open(); [_d3.new_page() for _ in range(3)]; _d3.save(str(three)); _d3.close()
    ap2 = sc.Appearance(font_path=font_path(), image_path=st.image_path("기본"))
    tg = [(i, (50, 50, 250, 120)) for i in range(3)]
    m2 = tmp / "m2.pdf"
    names = sc.sign_pdf(str(three), str(m2), pfx, PW, targets=tg, appearance=ap2, certify=2, tsa=tsa)
    rr = sc.verify_pdf(str(m2), [info.fp])
    chk(names == ["Signature1", "Signature2", "Signature3"] and [x.state for x in rr.sigs] == [sc.OK_TRUSTED] * 3
        and rr.sigs[0].certify == 2 and rr.sigs[1].certify == 0,
        "N1 여러 쪽 + 인증(양식·서명 허용) — 칸을 먼저 만들어 세 서명 모두 유효, 첫 서명만 인증",
        str([(x.field, x.state, x.certify, x.modification) for x in rr.sigs]))
    chk(all(x.ts_time and x.ts_name == "Test TSA" for x in rr.sigs), "N2 타임스탬프 기관 시각·이름이 검증에 나온다")
    errs = {}
    for label, kw, srcf in (("one_page", dict(targets=tg, certify=1), three),
                            ("new_field", dict(page_index=0, box_pdf=(300, 300, 400, 350)), m2),
                            ("not_first", dict(page_index=0, box_pdf=(300, 300, 400, 350), certify=2), signed)):
        try:
            sc.sign_pdf(str(srcf), str(tmp / "x.pdf"), pfx, PW, appearance=ap2, **kw)
            errs[label] = "signed"
        except sc.SignError as e:
            errs[label] = e.reason
    c1 = tmp / "c1.pdf"
    sc.sign_pdf(str(three), str(c1), pfx, PW, page_index=0, box_pdf=(50, 50, 250, 120), appearance=ap2, certify=1)
    try:
        sc.sign_pdf(str(c1), str(tmp / "x.pdf"), pfx, PW, page_index=1, box_pdf=(50, 50, 250, 120), appearance=ap2)
        errs["p1"] = "signed"
    except sc.SignError as e:
        errs["p1"] = e.reason
    chk(errs == {"one_page": "certify_one_page", "new_field": "certified_new_field", "not_first": "certify_not_first",
                 "p1": "certified"},
        "N3 막는 경우 — 변경 금지는 한 쪽만·인증 문서에 새 칸 거부·인증은 첫 서명만·변경 금지 인증 뒤 서명 거부", str(errs))
    try:
        sc.sign_pdf(str(three), str(tmp / "x.pdf"), pfx, PW, page_index=0, box_pdf=(50, 50, 250, 120), appearance=ap2,
                    tsa="http://127.0.0.1:9/tsa")
        chk(False, "N4 기관에 닿지 않으면 서명하지 않는다(tsa_failed)")
    except sc.SignError as e:
        chk(e.reason == "tsa_failed",
            "N4 기관에 닿지 않으면 서명하지 않는다(tsa_failed)", e.reason)
    # 글자 배치 — 미리보기가 배치마다 다르다(같은 그리기를 서명도 쓴다)
    pv = {lay: sc.preview_png(sc.Appearance(font_path=font_path(), image_path=st.image_path("기본"), layout=lay),
                              "홍길동", "", 200, 75) for lay in sc.LAYOUTS}
    chk(len(set(pv.values())) == 3, "N5 글자 배치 셋(겹쳐·그림 왼쪽·그림 위)이 서로 다르게 그려진다")
    rev = sc.signed_revision_bytes(str(m2), "Signature1")
    rv = tmp / "rev.pdf"; rv.write_bytes(rev)
    rr2 = sc.verify_pdf(str(rv), [info.fp])
    chk(m2.read_bytes().startswith(rev) and [(x.field, x.state) for x in rr2.sigs] == [("Signature1", sc.OK_TRUSTED)],
        "N6 서명 시점 판 — 그 서명까지 자른 앞부분, 그 판에서는 그 서명 하나만·변경 없음")
    # 서명 패널 [서명 시점 판 저장…] — 실제 단추로
    opened_rev = []
    out_rev = root / "m2_서명시점.pdf"
    QFileDialog_ = __import__("PyQt6.QtWidgets", fromlist=["QFileDialog"]).QFileDialog
    _orig_gs = QFileDialog_.getSaveFileName
    QFileDialog_.getSaveFileName = staticmethod(lambda *a, **k: (str(out_rev), "PDF (*.pdf)"))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    pan2 = sdlg.SignPanelDialog(mw, sc.verify_pdf(str(m2), [info.fp]), path=str(m2), open_cb=opened_rev.append)
    pan2.lst.setCurrentRow(1)
    detail = pan2.detail.text()
    pan2.b_rev.click(); spin(0.2)
    QFileDialog_.getSaveFileName = _orig_gs
    chk(out_rev.exists() and opened_rev == [str(out_rev)] and len(sc.verify_pdf(str(out_rev), [info.fp]).sigs) == 2
        and "타임스탬프" in detail and "승인 서명" in detail,
        "N7 패널 — 종류·타임스탬프 줄, [서명 시점 판 저장…] 이 그 판을 저장하고 연다", detail[:80])
    pan2.close()
    # 손으로 그리기 — 실제 마우스 끌기로
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import QPoint, Qt as _Qt
    dd_ = sdlg._DrawDialog(mw); dd_.show(); spin(0.1)
    pad = dd_.pad
    QTest.mousePress(pad, _Qt.MouseButton.LeftButton, pos=QPoint(40, 150))
    for x in range(40, 560, 20):
        QTest.mouseMove(pad, QPoint(x, 150 - (x // 8) % 60))
    QTest.mouseRelease(pad, _Qt.MouseButton.LeftButton, pos=QPoint(560, 120))
    drawn = dd_.pil_image()
    imd2 = sdlg.SignImageDialog(mw); imd2.set_source(drawn)
    chk(pad.strokes == 1 and sc.ink_bbox(drawn) is not None and imd2._btn_save.isEnabled(),
        "N8 손으로 그리기 — 그린 획이 투명 바탕 그림이 되고 서명 그림으로 저장할 수 있다")
    dd_.close(); imd2.close()
    # 여러 쪽 — 실제 서명 흐름(서명 창 '모든 쪽' + 인증 2)
    mp = root / "여러쪽.pdf"
    shutil.copy(three, mp)
    mw.open_pdfs([str(mp)]); spin(0.8)
    mv = mw.main_view; mv.go_to_page(0); spin(0.3)

    class _MultiDlg(_RealSign):
        def exec(self):
            self.cmb_pages.setCurrentIndex(self.cmb_pages.findData("all"))
            self.cmb_kind.setCurrentIndex(self.cmb_kind.findData(2))
            self.ed_pw.setText(PW); self._sign()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _MultiDlg
    picked["text"] = "그림 없이"
    z = mv._zoom or 1.0
    mw.action_sign_pdf(); mv.signRegionSelected.emit(QRectF(80 * z, 80 * z, 200 * z, 70 * z)); spin(2.0)
    rm = sc.verify_pdf(str(mp), st.trusted())
    chk(len(rm.sigs) == 3 and rm.worst == sc.OK_TRUSTED and rm.sigs[0].certify == 2,
        "N9 서명 창 '모든 쪽'·인증 — 실제 흐름으로 세 쪽 모두 서명, 첫 서명 인증", str([(x.state, x.certify) for x in rm.sigs]))

    # ── O. 3단계 빈 서명 칸(§3.7) ────────────────────────────────
    sdlg.SignDialog = _RealSign
    blank = tmp / "blank.pdf"
    _b = fitz.open(); [_b.new_page() for _ in range(2)]; _b.save(str(blank)); _b.close()
    e1 = tmp / "e1.pdf"
    nm = sc.add_empty_field(str(blank), str(e1), page_index=1, box_pdf=(100, 100, 300, 160), name="검토자")
    _d = fitz.open(str(e1)); ef = sc.empty_fields(_d); signed_flag = sc.doc_is_signed(_d); _d.close()
    chk(nm == "검토자" and len(ef) == 1 and ef[0].page == 1 and abs(ef[0].rect[2] - ef[0].rect[0] - 200) < 0.5
        and not signed_flag and e1.read_bytes().startswith(blank.read_bytes()),
        "O1 빈 서명 칸 만들기 — 증분·찾기(쪽·크기)·서명된 문서 아님", str(ef))
    oerr = {}
    try:
        sc.add_empty_field(str(e1), str(tmp / "x.pdf"), page_index=0, box_pdf=(1, 1, 60, 30), name="검토자")
    except sc.SignError as e:
        oerr["dup"] = e.reason
    e2 = tmp / "e2.pdf"
    sc.sign_pdf(str(e1), str(e2), pfx, PW, page_index=0, box_pdf=(20, 20, 220, 80), appearance=ap2, certify=2)
    try:
        sc.add_empty_field(str(e2), str(tmp / "x.pdf"), page_index=0, box_pdf=(300, 300, 400, 350))
    except sc.SignError as e:
        oerr["cert"] = e.reason
    _d = fitz.open(str(e2)); lvl = sc.doc_certify_level(_d); _d.close()
    e3 = tmp / "e3.pdf"
    sc.sign_pdf(str(e2), str(e3), pfx, PW, field="검토자", appearance=ap2)
    try:
        sc.sign_pdf(str(e3), str(tmp / "x.pdf"), pfx, PW, field="검토자", appearance=ap2)
    except sc.SignError as e:
        oerr["filled"] = e.reason
    r3 = sc.verify_pdf(str(e3), [info.fp])
    chk(oerr == {"dup": "field_exists", "cert": "certified_new_field", "filled": "no_field"} and lvl == 2,
        "O2 막는 경우 — 이름 겹침·인증 문서에 칸 더하기·이미 채운 칸", str(oerr))
    chk([(x.field, x.state) for x in r3.sigs] == [("Signature1", sc.OK_TRUSTED), ("검토자", sc.OK_TRUSTED)],
        "O3 인증(P=2) 문서의 빈 칸 채우기 — 인증 서명·채운 서명 둘 다 유효",
        str([(x.field, x.state, x.modification) for x in r3.sigs]))
    e4 = tmp / "e4.pdf"
    sc.add_empty_field(str(signed), str(e4), page_index=0, box_pdf=(300, 300, 450, 360))
    chk(sc.verify_pdf(str(e4), [info.fp]).worst == sc.OK_TRUSTED, "O4 승인 서명 뒤 빈 칸을 더해도 앞 서명은 유효")
    # 실제 흐름 — 도구 '빈 서명 칸 만들기' → 끌기 → 이름 → 현재 파일
    from PyQt6.QtWidgets import QInputDialog
    _orig_gt, _orig_gi = QInputDialog.getText, QInputDialog.getItem
    QInputDialog.getText = staticmethod(lambda *a, **k: ("승인자", True))

    class _FieldSet(sdlg.SigFieldDialog):
        want = {"name": "승인자", "lock": False, "cert": ""}

        def exec(self):
            self.ed_name.setText(_FieldSet.want["name"])
            self.chk_lock.setChecked(_FieldSet.want["lock"])
            if _FieldSet.want["cert"]:
                self.load_cert(_FieldSet.want["cert"])
            self._ok()
            return self.result()
    _orig_sfd = sdlg.SigFieldDialog
    sdlg.SigFieldDialog = _FieldSet
    fd_path = root / "빈칸.pdf"
    shutil.copy(blank, fd_path)
    mw.open_pdfs([str(fd_path)]); spin(0.8)
    mv = mw.main_view; mv.go_to_page(0); spin(0.3)
    labels = []
    for act in mw.menuBar().actions():
        if act.text().startswith("도구"):
            labels = [a.text() for a in act.menu().actions()]
    mw.action_sign_field()
    armed = getattr(mv.view, "_block_purpose", "") == "sign" and mv.view._block_armed
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(100 * z, 100 * z, 200 * z, 60 * z)); spin(1.2)
    _d = fitz.open(str(fd_path)); ef = sc.empty_fields(_d); _d.close()
    chk("빈 서명 칸 만들기..." in labels and armed and [f.name for f in ef] == ["승인자"] and not list(root.glob("~*.polypdf-sign")),
        "O5 도구 '빈 서명 칸 만들기...' → 끌기 → 이름 → 현재 파일에 칸", str(ef))
    mv = mw.main_view
    spin(0.3)
    chk(mv.sign_band.isVisible() and mv.sign_band.state == "empty" and mv.sign_band.btn.text() == "서명",
        "O6 빈 칸만 있는 문서 — 띠 '빈 서명 칸' + [서명]", mv.sign_band.state + "/" + mv.sign_band.label.text())
    seen_buttons = []

    class _FieldDlg(_RealSign):
        got = []

        def exec(self):
            _FieldDlg.got.append((self.field_name, self.cmb_pages.isEnabled()))
            self.ed_pw.setText(PW); self._sign()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _FieldDlg
    QMessageBox.exec = lambda self: (seen_buttons.append([b.text() for b in self.buttons()]),
                                     setattr(self, "_pick", next((b for b in self.buttons() if picked.get("text") and picked["text"] in b.text()), None)), 0)[2]
    picked["text"] = "빈 칸에 서명"
    mv.sign_band.btn.click(); spin(1.5)
    _d = fitz.open(str(fd_path)); ef = sc.empty_fields(_d); _d.close()
    rf = sc.verify_pdf(str(fd_path), st.trusted())
    chk(_FieldDlg.got == [("승인자", False)] and not ef and [(x.field, x.state) for x in rf.sigs] == [("승인자", sc.OK_TRUSTED)],
        "O7 띠 [서명] → '빈 칸에 서명' → 서명 창(칸 이름·쪽 고르기 끔) → 그 칸이 채워지고 유효", str(_FieldDlg.got))
    # 칸이 둘 — '새 자리 끌기' 를 골라도 끈 자리의 가운데가 칸 안이면 그 칸을 채운다
    two_f = root / "두칸.pdf"
    _t1 = tmp / "t1.pdf"
    sc.add_empty_field(str(blank), str(_t1), page_index=0, box_pdf=(50, 600, 250, 660), name="갑")
    sc.add_empty_field(str(_t1), str(two_f), page_index=0, box_pdf=(300, 600, 500, 660), name="을")
    mw.open_pdfs([str(two_f)]); spin(0.8)
    mv = mw.main_view; mv.go_to_page(0); spin(0.3)
    _d = fitz.open(str(two_f)); f_eul = next(f for f in sc.empty_fields(_d) if f.name == "을"); _d.close()
    picked["text"] = "새 자리 끌기"
    _FieldDlg.got = []
    seen_buttons.clear()
    mw.action_sign_pdf()
    z = mv._zoom or 1.0
    cx, cy = (f_eul.rect[0] + f_eul.rect[2]) / 2, (f_eul.rect[1] + f_eul.rect[3]) / 2
    mv.signRegionSelected.emit(QRectF(cx * z, cy * z, 1, 1)); spin(1.5)
    _d = fitz.open(str(two_f)); left = [f.name for f in sc.empty_fields(_d)]; _d.close()
    chk(_FieldDlg.got == [("을", False)] and left == ["갑"] and any("새 자리 끌기" in b for b in seen_buttons[0]),
        "O8 끈 자리의 가운데가 빈 칸 안이면 그 칸('을')을 채운다", str((_FieldDlg.got, left)))
    # 인증 문서 — '새 자리 끌기' 단추가 없다
    cert_f = root / "인증빈칸.pdf"
    shutil.copy(e2, cert_f)
    mw.open_pdfs([str(cert_f)]); spin(0.8)
    seen_buttons.clear()
    picked["text"] = "취소"
    mw.action_sign_pdf(); spin(0.2)
    chk(seen_buttons and not any("새 자리 끌기" in b for b in seen_buttons[0]) and any("빈 칸에 서명" in b for b in seen_buttons[0]),
        "O9 인증 문서는 빈 칸에만 — '새 자리 끌기' 없음", str(seen_buttons[:1]))
    # 잠금·서명할 사람(261010-31, §3.7)
    pB_, iB_ = sc.create_id("Bob", PW)
    cerA, cerB = tmp / "hong.cer", tmp / "bob.cer"
    cerA.write_bytes(sc.cert_der(pfx, PW)); cerB.write_bytes(sc.cert_der(pB_, PW))
    l1, l2 = tmp / "l1.pdf", tmp / "l2.pdf"
    sc.add_empty_field(str(blank), str(l1), page_index=0, box_pdf=(100, 100, 300, 160), name="대표", lock=True,
                       signer_certs=[cerA.read_bytes()])
    sc.add_empty_field(str(l1), str(l2), page_index=0, box_pdf=(100, 300, 300, 360), name="실무")
    _d = fitz.open(str(l2)); efl = {f.name: f for f in sc.empty_fields(_d)}; _d.close()
    chk(efl["대표"].lock and efl["대표"].signer_fps == (info.fp,) and efl["대표"].signer_names == ("홍길동",)
        and not efl["실무"].lock and not efl["실무"].signer_fps,
        "O10 칸의 잠금·서명할 사람을 찾기가 읽는다", str(efl["대표"]))
    try:
        sc.sign_pdf(str(l2), str(tmp / "x.pdf"), pB_, PW, field="대표", appearance=ap2)
        lerr = "signed"
    except sc.SignError as e:
        lerr = e.reason
    l3, l4 = tmp / "l3.pdf", tmp / "l4.pdf"
    sc.sign_pdf(str(l2), str(l3), pfx, PW, field="대표", appearance=ap2)
    one = [(x.field, x.state) for x in sc.verify_pdf(str(l3), [info.fp]).sigs]
    sc.sign_pdf(str(l3), str(l4), pB_, PW, field="실무", appearance=ap2)
    two = [(x.field, x.state) for x in sc.verify_pdf(str(l4), [info.fp, iB_.fp]).sigs]
    chk(lerr == "wrong_signer" and one == [("대표", sc.OK_TRUSTED)] and two == [("대표", sc.MODIFIED), ("실무", sc.OK_TRUSTED)],
        "O11 지정한 사람만 서명(다른 ID 는 wrong_signer) · 잠금 칸 서명 뒤 다른 칸 서명은 '변경됨'", str((lerr, one, two)))
    # 실제 흐름 — 칸 설정 창(서명할 사람 Bob·잠금) → 기본 ID(홍길동)로 채우려 하면 서명 전에 막는다
    _FieldSet.want = {"name": "대표", "lock": True, "cert": str(cerB)}
    lk = root / "잠금칸.pdf"
    shutil.copy(blank, lk)
    mw.open_pdfs([str(lk)]); spin(0.8)
    mv = mw.main_view; mv.go_to_page(0); spin(0.3)
    mw.action_sign_field()
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(100 * z, 100 * z, 200 * z, 60 * z)); spin(1.2)
    _d = fitz.open(str(lk)); efk = sc.empty_fields(_d); _d.close()
    chk(len(efk) == 1 and efk[0].lock and efk[0].signer_names == ("Bob",),
        "O12 칸 설정 창 — 서명할 사람(.cer)·잠금이 칸에 들어간다", str(efk))
    infos = []
    QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))

    class _OnceDlg(_RealSign):
        n = 0

        def exec(self):
            _OnceDlg.n += 1
            if _OnceDlg.n > 1:
                return QDialog.DialogCode.Rejected
            self.ed_pw.setText(PW); self._sign()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _OnceDlg
    picked["text"] = "빈 칸에 서명"
    mw.main_view.sign_band.btn.click(); spin(1.0)
    chk(any("Bob" in t for t in infos) and not sc.is_signed_file(lk),
        "O13 지정된 사람이 아닌 ID 로 채우면 서명 전에 막는다(파일은 그대로)", str(infos[-1:]))
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    sdlg.SigFieldDialog = _orig_sfd
    sdlg.SignDialog = _RealSign
    QInputDialog.getText, QInputDialog.getItem = _orig_gt, _orig_gi

    # ── P. 3단계 공동인증서(§3.8) ─────────────────────────────────
    from viewer import sign_npki as sn
    NP = tmp / "NPKI"
    NPW = "npki!Pass99"
    make_npki(str(NP / "yessign" / "USER" / "a"), NPW, "seed_sha1")
    make_npki(str(NP / "KICA" / "USER" / "b"), NPW, "pbes2", prf="sha256")
    make_npki(str(NP / "KICA" / "USER" / "c"), NPW, "pbes2", prf="sha1")
    make_npki(str(NP / "KICA" / "USER" / "old"), NPW, "seed_sha1", days=-1)
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa2
    make_npki(str(NP / "KICA" / "USER" / "mis"), NPW, "seed_sha1",
              cert_key=_rsa2.generate_private_key(public_exponent=65537, key_size=2048))
    found = sn.find([str(NP)])
    by = {Path(c.folder).name: c for c in found}
    chk(sorted(by) == ["a", "b", "c", "mis", "old"] and not by["old"].usable and by["old"].why == "expired"
        and by["a"].usable and by["a"].issuer == "yessign",
        "P1 찾기 — <NPKI>\\<기관>\\USER\\<폴더> 짝, 만료는 못 씀", str([(k, c.usable, c.why) for k, c in by.items()]))
    perr = {}
    for k in ("a", "b", "c"):
        try:
            sn.load(by[k].cert_path, by[k].key_path, "wrong-pass")
            perr[k] = "opened"
        except sc.WrongPassword:
            perr[k] = "wrong"
    for k in ("old", "mis"):
        try:
            sn.load(by[k].cert_path, by[k].key_path, NPW)
            perr[k] = "opened"
        except sc.SignError as e:
            perr[k] = e.reason
    chk(perr == {"a": "wrong", "b": "wrong", "c": "wrong", "old": "expired", "mis": "key_mismatch"},
        "P2 틀린 비밀번호(세 방식)·만료·짝 안 맞는 키는 거부", str(perr))
    okk = []
    for k in ("a", "b", "c"):
        pfx_n, info_n = sn.to_pfx(by[k].cert_path, by[k].key_path, NPW)
        out_n = tmp / f"np_{k}.pdf"
        sc.sign_pdf(str(blank), str(out_n), pfx_n, NPW, page_index=0, box_pdf=(20, 20, 220, 80), appearance=ap2)
        rn = sc.verify_pdf(str(out_n), [info_n.fp])
        okk.append((k, rn.worst, rn.sigs[0].signer if rn.sigs else ""))
    chk(all(w == sc.OK_TRUSTED and sg.startswith("홍길동") for _k, w, sg in okk),
        "P3 seedCBCWithSHA1·PBES2(SHA-256)·PBES2(기본 SHA-1) — 풀어 우리 .pfx 로, 서명·유효", str(okk))
    # 디지털 ID 창 [공동인증서 가져오기…] — 실제 단추
    sn_default = sn.default_roots
    sn.default_roots = lambda: [str(NP)]

    class _NpkiPick(sdlg.NpkiDialog):
        def exec(self):
            it = next(i for i, c in self._items if Path(c.folder).name == "a")
            self.lst.setCurrentItem(it); self.ed_pw.setText(NPW); self._ok()
            return QDialog.DialogCode.Accepted
    _orig_npki = sdlg.NpkiDialog
    sdlg.NpkiDialog = _NpkiPick
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    idd = sdlg.DigitalIdDialog(mw, runner=mw._sign_bg, hello_ok=False)
    n_before = idd.lst.count()
    idd.b_npki.click(); spin(0.3)
    texts = [idd.lst.item(i).text() for i in range(idd.lst.count())]
    ent = next((e for e in st.load()["ids"] if e.get("source") == "npki"), {})
    chk(idd.lst.count() == n_before + 1 and any("공동인증서" in t for t in texts) and ent.get("name", "").startswith("홍길동")
        and (NP / "yessign" / "USER" / "a" / "signPri.key").exists(),
        "P4 디지털 ID 창 [공동인증서 가져오기…] → 목록에 '공동인증서', 원래 폴더는 그대로", str(texts[-1:]))
    idd.close()
    sdlg.NpkiDialog = _orig_npki
    sn.default_roots = sn_default

    # ── Q. 3단계 Windows 인증서 저장소(§3.9) — 가짜 저장소 ─────────────────
    from viewer import sign_winstore as ws
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives.serialization import pkcs12 as _p12
    from cryptography.hazmat.primitives import serialization as _ser2
    store = tmp / "store"; store.mkdir()
    (store / "rsa.pfx").write_bytes(sc.create_id("저장소 RSA", ws.FAKE_PW_DEFAULT)[0])
    (store / "zz_cancel.pfx").write_bytes(sc.create_id("취소 카드", ws.FAKE_PW_DEFAULT)[0])
    _ek = _ec.generate_private_key(_ec.SECP256R1())
    import datetime as _dt2
    from cryptography import x509 as _x2
    from cryptography.x509.oid import NameOID as _N2
    from cryptography.hazmat.primitives import hashes as _h2
    _en = _x2.Name([_x2.NameAttribute(_N2.COMMON_NAME, "EC Card")])
    _nw = _dt2.datetime.now(_dt2.timezone.utc)
    _ec_cert = (_x2.CertificateBuilder().subject_name(_en).issuer_name(_en).public_key(_ek.public_key()).serial_number(9)
                .not_valid_before(_nw - _dt2.timedelta(days=1)).not_valid_after(_nw + _dt2.timedelta(days=100)).sign(_ek, _h2.SHA256()))
    (store / "ec.pfx").write_bytes(_p12.serialize_key_and_certificates(
        b"ec", _ek, _ec_cert, None, _ser2.BestAvailableEncryption(ws.FAKE_PW_DEFAULT.encode())))
    os.environ[ws.FAKE_ENV] = str(store)
    certs = ws.list_certs()
    names_q = sorted(c.name for c in certs)
    chk(ws.available() and names_q == ["EC Card", "저장소 RSA", "취소 카드"] and all(len(c.thumb) == 40 for c in certs),
        "Q1 저장소 목록 — 개인 키가 딸린 인증서·SHA-1 지문", str(names_q))
    qres = {}
    for c in certs:
        out_q = tmp / f"q_{c.thumb[:6]}.pdf"
        try:
            sc.sign_pdf(str(blank), str(out_q), b"", "", page_index=0, box_pdf=(20, 20, 220, 80), appearance=ap2,
                        signer=ws.make_signer(c.thumb))
            qres[c.name] = sc.verify_pdf(str(out_q), [c.fp]).worst
        except ws.StoreCancelled:
            qres[c.name] = "cancelled"
    chk(qres == {"EC Card": sc.OK_TRUSTED, "저장소 RSA": sc.OK_TRUSTED, "취소 카드": "cancelled"},
        "Q2 키 없이 저장소 Signer 로 서명 — RSA·ECDSA(원시 r‖s → DER) 유효, PIN 취소는 StoreCancelled", str(qres))
    try:
        ws.make_signer("00" * 20)
        chk(False, "Q3 저장소에 없는 지문은 not_found")
    except ws.StoreError as e:
        chk(e.reason == "not_found", "Q3 저장소에 없는 지문은 not_found(카드 뺌·삭제)", e.reason)

    class _StorePick(sdlg.StoreCertDialog):
        def exec(self):
            it = next(i for i, c in self._items if c.name == "저장소 RSA")
            self.lst.setCurrentItem(it); self._ok()
            return QDialog.DialogCode.Accepted
    _orig_sd = sdlg.StoreCertDialog
    sdlg.StoreCertDialog = _StorePick
    idd = sdlg.DigitalIdDialog(mw, runner=mw._sign_bg, hello_ok=False)
    idd.b_store.click(); spin(0.2)
    went = next((e for e in st.load()["ids"] if e.get("kind") == "win"), {})
    idd.lst.setCurrentRow(next(i for i in range(idd.lst.count()) if "Windows 저장소" in idd.lst.item(i).text()))
    chk(idd.b_store.isVisible() is not None and went.get("thumb") and not went.get("file")
        and st.abspath(went["cert"]).exists() and not idd.b_bak.isEnabled() and idd.b_cer.isEnabled(),
        "Q4 [Windows 인증서 저장소에서…] → 참조만(키·.pfx 없음, .cer 만) · 백업 끔", str(went))
    idd.close()
    sdlg.StoreCertDialog = _orig_sd
    # 실제 서명 흐름 — 비밀번호 칸 없이 [서명]
    ws_doc = root / "저장소서명.pdf"
    shutil.copy(blank, ws_doc)
    mw.open_pdfs([str(ws_doc)]); spin(0.8)
    mv = mw.main_view; mv.go_to_page(0); spin(0.3)

    class _WinDlg(_RealSign):
        seen = []

        def exec(self):
            self.cmb_id.setCurrentIndex(self.cmb_id.findData(went["fp"]))
            _WinDlg.seen.append((self.ed_pw.isEnabled(), self._win_note.isVisibleTo(self)))
            if len(_WinDlg.seen) > 1:
                return QDialog.DialogCode.Rejected
            self._sign()
            return QDialog.DialogCode.Accepted if self.result() == QDialog.DialogCode.Accepted else QDialog.DialogCode.Rejected
    sdlg.SignDialog = _WinDlg
    picked["text"] = "그림 없이"
    z = mv._zoom or 1.0
    mw.action_sign_pdf(); mv.signRegionSelected.emit(QRectF(80 * z, 80 * z, 200 * z, 70 * z)); spin(1.5)
    rw = sc.verify_pdf(str(ws_doc), st.trusted())
    chk(_WinDlg.seen[:1] == [(False, True)] and rw.worst == sc.OK_TRUSTED and rw.sigs[0].signer == "저장소 RSA",
        "Q5 저장소 ID 로 서명 — 비밀번호 칸 끔·'Windows 가 PIN' 안내, 현재 파일에 유효", str((_WinDlg.seen, rw.worst)))
    sdlg.SignDialog = _RealSign
    os.environ.pop(ws.FAKE_ENV, None)

    # ── R. 검토 보완(261011-1) ─────────────────────────────────
    # R1·R2 책갈피 자동 생성 '현재 PDF에 저장' 은 워커가 원본을 바꿔 _finalize_save 를 거치지 않는다 — 같은 가드
    import viewer.widgets.bookmarker_dialog as _bmd
    import viewer.app as _vapp
    r_doc = root / "R_서명됨.pdf"
    shutil.copy(signed, r_doc)
    started = []

    class _FakeBm(QDialog):
        def __init__(self, *a, **k):
            super().__init__()

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_options(self):
            return {"input_pdf": str(r_doc), "save_pdf": True, "save_txt": False, "overwrite": True,
                    "mode": "auto", "review": False}
    _RealBm, _RealW, _RealRun = _bmd.BookmarkerDialog, _vapp.BookmarkerWorker, _vapp.run_in_thread
    _bmd.BookmarkerDialog = _FakeBm
    _vapp.BookmarkerWorker = lambda pdf, opts: started.append(dict(opts)) or _RealW(pdf, opts)
    _vapp.run_in_thread = lambda *a, **k: None
    picked["text"] = "취소"
    mw.action_open_bookmarker()
    chk(not started and sc.is_signed_file(r_doc), "R1 서명된 PDF 에 책갈피 '현재 PDF에 저장' → 묻고, 취소면 시작하지 않는다", str(started))
    picked["text"] = "새 파일로"
    mw.action_open_bookmarker()
    chk(len(started) == 1 and started[0].get("overwrite") is False and mw._prefs.get("bookmarker_overwrite") is True,
        "R2 [새 파일로] → 이 실행만 새 PDF(_bookmarked), 저장한 선택값은 그대로", str(started))
    _bmd.BookmarkerDialog, _vapp.BookmarkerWorker, _vapp.run_in_thread = _RealBm, _RealW, _RealRun
    QMessageBox.exec = orig_exec

    # R3 signing.json 을 잠깐 못 읽어도(다른 창·백신) '깨진 목록' 으로 옮기거나 빈 목록으로 덮어쓰지 않는다
    idx = st.root() / st.INDEX
    before = idx.read_bytes()
    _rt = Path.read_text

    def _locked(self, *a, **k):
        if self.name == st.INDEX:
            raise PermissionError(13, "locked")
        return _rt(self, *a, **k)
    Path.read_text = _locked
    try:
        dd_ = st.load()
        try:
            st.save(dd_); wrote = True
        except OSError:
            wrote = False
    finally:
        Path.read_text = _rt
    chk(dd_.get("_unreadable") and not wrote and idx.read_bytes() == before and not idx.with_suffix(".broken.json").exists()
        and st.load().get("ids"), "R3 signing.json 을 못 읽으면 표시만 — 옮기지도 덮어쓰지도 않는다")

    # R4 기관 .pfx 의 중간 인증서(체인)는 가져와도 남는다 — 버리면 Acrobat 이 '신원 미확인'
    import datetime as _dt
    from cryptography import x509 as _x
    from cryptography.x509.oid import NameOID as _N
    from cryptography.hazmat.primitives import hashes as _h, serialization as _ser
    from cryptography.hazmat.primitives.serialization import pkcs12 as _p12
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    _ca_k = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _ee_k = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _now = _dt.datetime.now(_dt.timezone.utc)
    _cn = lambda n: _x.Name([_x.NameAttribute(_N.COMMON_NAME, n)])
    _ca = (_x.CertificateBuilder().subject_name(_cn("Test CA")).issuer_name(_cn("Test CA")).public_key(_ca_k.public_key())
           .serial_number(1).not_valid_before(_now - _dt.timedelta(days=1)).not_valid_after(_now + _dt.timedelta(days=99))
           .add_extension(_x.BasicConstraints(ca=True, path_length=None), critical=True).sign(_ca_k, _h.SHA256()))
    _ee = (_x.CertificateBuilder().subject_name(_cn("기관 발급")).issuer_name(_cn("Test CA")).public_key(_ee_k.public_key())
           .serial_number(2).not_valid_before(_now - _dt.timedelta(days=1)).not_valid_after(_now + _dt.timedelta(days=99))
           .sign(_ca_k, _h.SHA256()))
    _raw = _p12.serialize_key_and_certificates(b"x", _ee_k, _ee, [_ca], _ser.BestAvailableEncryption(PW.encode()))
    _norm, _inf = sc.normalize_pfx(_raw, PW)
    _k2, _c2, _extra2 = sc.load_pfx(_norm, PW)
    chk(len(_extra2) == 1 and _extra2[0].subject == _ca.subject, "R4 가져온 .pfx 의 중간 인증서를 남긴다", str(len(_extra2)))

    # R5 원본 폴더에 임시 파일을 못 만들면(읽기 전용) 시스템 임시 폴더로 — 슬롯 예외로 끝나지 않는다
    _t = mw._sign_tmp(str(tmp / "없는폴더" / "a.pdf"))
    chk(Path(_t).exists() and Path(_t).parent != tmp / "없는폴더", "R5 원본 폴더에 못 쓰면 임시 파일은 시스템 임시 폴더", _t)
    os.remove(_t)
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
