# -*- coding: utf-8 -*-
"""전자서명 핵심 — 디지털 ID·서명·검증·서명 판정·서명 그림 정리 (보안 SOT §3·§4·§5·§8).

화면(Qt)을 모른다 — 배경 스레드에서 그대로 부르고, 검사가 앱 없이 부른다.
무거운 라이브러리(pyHanko·cryptography·Pillow)는 **함수 안에서** 가져온다 — 앱 시작에 넣지 않는다(SOT §8·§10).

비밀번호는 인자로만 받고 어디에도 남기지 않는다 — 예외 메시지에 넣지 않는다(SOT §6.4).
"""
from __future__ import annotations

import datetime as _dt
import io
import os
from dataclasses import dataclass, field

RSA_BITS = 3072                 # SOT §3.2 — Acrobat·구형 뷰어 모두 검증
PFX_KDF_ROUNDS = 200_000        # PBES2-PBKDF2-SHA256 반복 수
ID_YEARS_DEFAULT = 5
PASSWORD_MIN = 10               # SOT §3.2 — 약하면 경고만(막지 않는다)
IMAGE_MAX_SIDE = 1200           # SOT §3.1 — 서명 그림 긴 변
IMAGE_MARGIN = 0.04             # 잉크 경계 바깥 여백(긴 변 대비)


class WrongPassword(Exception):
    """`.pfx` 비밀번호가 맞지 않다 — 메시지에 비밀번호를 넣지 않는다."""


class SignError(Exception):
    """서명할 수 없다(문서 상태·라이브러리 오류). `reason` 은 화면 분기용 짧은 코드."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# 디지털 ID
# ---------------------------------------------------------------------------

@dataclass
class IdInfo:
    fp: str                     # 인증서 SHA-256 지문(16진, 소문자)
    name: str
    email: str = ""
    org: str = ""
    not_after: str = ""         # YYYY-MM-DD

    @property
    def short(self) -> str:
        return self.fp[:16]


def password_weak(pw: str) -> bool:
    """SOT §3.2 — 10자 미만이거나 글자 종류가 하나뿐이면 약하다."""
    if len(pw or "") < PASSWORD_MIN:
        return True
    kinds = sum(bool(any(f(c) for c in pw)) for f in (str.isdigit, str.isalpha, lambda c: not c.isalnum()))
    return kinds < 2


def _cert_info(cert) -> IdInfo:
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID

    def _get(oid):
        try:
            v = cert.subject.get_attributes_for_oid(oid)
            return v[0].value if v else ""
        except Exception:
            return ""
    try:
        na = cert.not_valid_after_utc
    except AttributeError:                     # 옛 cryptography
        na = cert.not_valid_after
    return IdInfo(fp=cert.fingerprint(hashes.SHA256()).hex(),
                  name=_get(NameOID.COMMON_NAME), email=_get(NameOID.EMAIL_ADDRESS),
                  org=_get(NameOID.ORGANIZATION_NAME), not_after=na.strftime("%Y-%m-%d"))


def _pfx_bytes(key, cert, friendly: str, password: str) -> bytes:
    """PBES2 + AES-256-CBC + PBKDF2-SHA256 으로 잠근 PKCS#12 (SOT §3.2 — 3DES/RC2 금지)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    enc = (serialization.PrivateFormat.PKCS12.encryption_builder()
           .kdf_rounds(PFX_KDF_ROUNDS)
           .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
           .hmac_hash(hashes.SHA256())
           .build(password.encode("utf-8")))
    return pkcs12.serialize_key_and_certificates((friendly or "PolyPDF").encode("utf-8"), key, cert, None, enc)


def create_id(name: str, password: str, *, email: str = "", org: str = "",
              years: int = ID_YEARS_DEFAULT) -> tuple[bytes, IdInfo]:
    """자체 서명 디지털 ID — RSA 3072·SHA-256, keyUsage = digitalSignature·nonRepudiation (SOT §3.2).

    반환: (`.pfx` 바이트, 정보). extKeyUsage 는 넣지 않는다(Acrobat 이 거부하는 경우 — SOT §11 실측 ①)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    name = (name or "").strip()
    if not name:
        raise ValueError("name")
    if not password:
        raise ValueError("password")
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, name)]
    if org.strip():
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org.strip()))
    if email.strip():
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email.strip()))
    subj = x509.Name(attrs)
    key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)
    now = _dt.datetime.now(_dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - _dt.timedelta(minutes=5))
         .not_valid_after(now + _dt.timedelta(days=365 * max(1, int(years))))
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True,
                                      key_encipherment=False, data_encipherment=False,
                                      key_agreement=False, key_cert_sign=False, crl_sign=False,
                                      encipher_only=False, decipher_only=False), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False))
    if email.strip():
        b = b.add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email.strip())]), critical=False)
    cert = b.sign(key, hashes.SHA256())
    return _pfx_bytes(key, cert, name, password), _cert_info(cert)


def load_pfx(data: bytes, password: str):
    """(개인 키, 인증서, 추가 인증서 목록). 비밀번호가 틀리면 `WrongPassword`."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(data, (password or "").encode("utf-8"))
    except ValueError:
        # 비밀번호가 틀렸거나 파일이 PKCS#12 가 아니다 — 원문 예외는 버린다(SOT §6.4)
        raise WrongPassword() from None
    return key, cert, list(extra or [])


def check_pfx(data: bytes, password: str) -> IdInfo:
    """가져올 `.pfx` 확인 — 개인 키가 있고 문서 서명 용도인지(SOT §3.2)."""
    from cryptography import x509
    key, cert, _extra = load_pfx(data, password)
    if key is None or cert is None:
        raise SignError("no_key")
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (ku.digital_signature or ku.content_commitment):
            raise SignError("bad_usage")
    except x509.ExtensionNotFound:
        pass
    return _cert_info(cert)


def normalize_pfx(data: bytes, password: str) -> tuple[bytes, IdInfo]:
    """가져온 `.pfx` 를 우리 형식(PBES2-AES256)으로 다시 잠근다 — 같은 비밀번호(SOT §3.2)."""
    info = check_pfx(data, password)
    key, cert, _extra = load_pfx(data, password)
    return _pfx_bytes(key, cert, info.name, password), info


def pfx_info(data: bytes, password: str) -> IdInfo:
    _key, cert, _ = load_pfx(data, password)
    return _cert_info(cert)


def cert_der(data: bytes, password: str) -> bytes:
    """공개 인증서(.cer, DER) — 받는 사람이 신뢰 등록하는 데 쓴다(SOT §3.2 내보내기)."""
    from cryptography.hazmat.primitives import serialization
    _key, cert, _ = load_pfx(data, password)
    return cert.public_bytes(serialization.Encoding.DER)


def cert_fingerprint(der: bytes) -> str:
    import hashlib
    return hashlib.sha256(der).hexdigest()


# ---------------------------------------------------------------------------
# 서명 판정 — SOT §4
# ---------------------------------------------------------------------------

def doc_is_signed(doc) -> bool:
    """열린 fitz 문서에 값이 있는 서명 필드가 있나. SigFlags 로 먼저 거른다(보통 문서는 바로 False)."""
    try:
        if doc.get_sigflags() < 1:
            return False
    except Exception:
        return False
    try:
        import fitz
        for page in doc:
            for w in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []:
                if getattr(w, "is_signed", False):
                    return True
    except Exception:
        return False
    return False


def probe_signed(doc) -> bool:
    """목록 조사용(보안 SOT §4 책갈피창 표시) — 열린 문서가 잠겨 있으면 SigFlags 만으로 '서명됐을 수 있다'."""
    try:
        if getattr(doc, "needs_pass", False) and getattr(doc, "is_encrypted", False):
            return doc.get_sigflags() >= 1
    except Exception:
        return False
    return doc_is_signed(doc)


_SIGNED_CACHE: dict = {}


def is_signed_file(path) -> bool:
    """파일 경로로 판정 — 같은 크기·수정 시각이면 다시 열지 않는다. 암호 문서는 xref 만 보고 False 일 수 있어
    열기 암호 없이 판정할 수 없을 때는 False(가드는 열린 문서 판정을 함께 쓴다 — sign_controller)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (os.path.normcase(os.path.abspath(str(path))), st.st_size, st.st_mtime_ns)
    hit = _SIGNED_CACHE.get(key)
    if hit is not None:
        return hit
    res = False
    try:
        import fitz
        d = fitz.open(str(path))
        try:
            if not d.needs_pass:
                res = doc_is_signed(d)
            else:
                # 암호 문서도 SigFlags 는 보통 읽힌다 — 있으면 '서명됐을 수 있다' 로 본다(덮어쓰기 전에 묻는 편이 안전)
                try:
                    res = d.get_sigflags() >= 1
                except Exception:
                    res = False
        finally:
            d.close()
    except Exception:
        res = False
    if len(_SIGNED_CACHE) > 256:
        _SIGNED_CACHE.clear()
    _SIGNED_CACHE[key] = res
    return res


# ---------------------------------------------------------------------------
# 서명 그림 — SOT §3.1
# ---------------------------------------------------------------------------

def _otsu(hist) -> int:
    total = sum(hist)
    if not total:
        return 128
    s_all = sum(i * h for i, h in enumerate(hist))
    w_b = s_b = 0
    best, thr = -1.0, 128
    for t in range(256):
        w_b += hist[t]
        if not w_b:
            continue
        w_f = total - w_b
        if not w_f:
            break
        s_b += t * hist[t]
        m_b = s_b / w_b
        m_f = (s_all - s_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            # 두 무리 평균의 가운데 — 잉크 값 자체를 문턱으로 삼으면 잉크가 문턱에 걸려 투명해진다(실측)
            best, thr = var, int(round((m_b + m_f) / 2))
    return thr


def auto_threshold(img) -> int:
    """밝기 임계값 자동(오츠). 종이 사진에서 잉크/종이를 가른다."""
    g = img.convert("L")
    return _otsu(g.histogram())


def has_transparency(img) -> bool:
    if img.mode not in ("RGBA", "LA", "PA"):
        return "transparency" in img.info
    a = img.getchannel("A")
    lo, _hi = a.getextrema()
    return lo < 250


def clean_signature(img, threshold: int | None = None, ink: str = "original"):
    """종이 → 투명, 잉크 색 정리, 잉크 경계로 자르기, 긴 변 줄이기 (SOT §3.1). Pillow Image → RGBA Image.

    - 이미 투명한 PNG 는 배경 지우기를 건너뛴다(잉크 색·자르기만).
    - `ink`: "original" | "black" | "blue"
    - 잉크가 없으면(전부 종이) 빈 그림 대신 원본 크기 투명 그림을 돌려준다 — 호출측이 막는다(`ink_bbox` None)."""
    from PIL import Image
    img = img.convert("RGBA")
    if not has_transparency(img):
        thr = auto_threshold(img) if threshold is None else int(threshold)
        g = img.convert("L")
        # 임계값보다 어두우면 잉크. 경계를 부드럽게: 임계값 근처 20 단계로 알파를 비례
        soft = 20

        def _alpha(v, t=thr, s=soft):
            if v <= t - s:
                return 255
            if v >= t:
                return 0
            return int(255 * (t - v) / s)
        a = g.point(_alpha)
        img.putalpha(a)
    if ink in ("black", "blue"):
        col = (0, 0, 0) if ink == "black" else (16, 48, 160)
        solid = Image.new("RGBA", img.size, col + (0,))
        solid.putalpha(img.getchannel("A"))
        img = solid
    box = ink_bbox(img)
    if box:
        x0, y0, x1, y1 = box
        m = int(max(img.size) * IMAGE_MARGIN)
        img = img.crop((max(0, x0 - m), max(0, y0 - m), min(img.width, x1 + m), min(img.height, y1 + m)))
    if max(img.size) > IMAGE_MAX_SIDE:
        r = IMAGE_MAX_SIDE / max(img.size)
        img = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
    return img


def ink_bbox(img):
    """알파가 있는(잉크) 영역의 경계. 없으면 None."""
    try:
        a = img.getchannel("A")
    except Exception:
        return None
    return a.point(lambda v: 255 if v > 24 else 0).getbbox()


# ---------------------------------------------------------------------------
# 서명 — SOT §3.3·§3.4·§8
# ---------------------------------------------------------------------------

@dataclass
class Appearance:
    image_path: str = ""            # 서명 그림(투명 PNG) — 없으면 글자만
    show_name: bool = True
    show_date: bool = True
    show_reason: bool = False
    font_path: str = ""             # 겉모양 글자 글꼴(맑은 고딕 — pdf_font.text_font_file)
    layout: str = "overlay"         # 2단계(SOT §3.6): overlay(그림 위에 겹쳐) | image_left | image_top


LAYOUTS = ("overlay", "image_left", "image_top")
CERTIFY_LEVELS = (0, 1, 2, 3)        # 0 = 승인 서명, 1·2·3 = DocMDP P (SOT §3.6)


_FALLBACK_FONTS = ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                   "/Library/Fonts/AppleGothic.ttf", "/System/Library/Fonts/Supplemental/AppleGothic.ttf")


def default_font() -> str:
    """겉모양 글자 글꼴 — 맑은 고딕(마스터 §4.5.11 `pdf_font.text_font_file`), 없으면 한글이 되는 .ttf 하나.
    pyHanko 의 글꼴 넣기는 .ttc 를 받지 않는다(.ttf/.otf 만)."""
    try:
        from viewer import pdf_font
        p = pdf_font.text_font_file()
        if p and p.lower().endswith((".ttf", ".otf")):
            return p
    except Exception:
        pass
    for p in _FALLBACK_FONTS:
        if os.path.exists(p):
            return p
    return ""


def page_box_to_pdf(page, rect) -> tuple[float, float, float, float]:
    """fitz 쪽 좌표(왼쪽 위 원점, 회전 전) 사각형 → PDF 사용자 공간(왼쪽 아래 원점) 상자.

    MediaBox 원점이 0 이 아닌 쪽도 맞도록 `transformation_matrix` 의 역행렬을 쓴다(마스터 §4.7.15 와 같은 함정)."""
    import fitz
    r = fitz.Rect(rect)
    m = ~page.transformation_matrix
    q = r * m
    q.normalize()
    return (q.x0, q.y0, q.x1, q.y1)


def _stamp_style(app: Appearance, signer_name: str, reason: str, box_w: float = 0.0, box_h: float = 0.0):
    """서명 겉모양 스타일. `box_w`·`box_h`(pt)는 글자 배치(SOT §3.6)가 상자를 나눌 때 쓴다."""
    from pyhanko import stamp
    from pyhanko.pdf_utils.images import PdfImage
    bg = None
    if app.image_path and os.path.exists(app.image_path):
        from PIL import Image
        bg = PdfImage(Image.open(app.image_path).convert("RGBA"))
    lines = []
    if app.show_name:
        lines.append("%(signer)s")
    if app.show_date:
        lines.append("%(ts)s")
    if app.show_reason and reason:
        lines.append(reason.replace("%", "%%"))
    if not lines:
        if bg is None:
            return stamp.TextStampStyle(stamp_text="%(signer)s", border_width=0)
        return stamp.StaticStampStyle(background=bg, background_opacity=1, border_width=0)
    text_style = None
    if app.font_path and os.path.exists(app.font_path) and app.font_path.lower().endswith((".ttf", ".otf")):
        from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
        from pyhanko.pdf_utils.text import TextBoxStyle
        text_style = TextBoxStyle(font=GlyphAccumulatorFactory(app.font_path), font_size=9)
    elif any(ord(c) > 127 for c in (signer_name + reason)):
        # 한글을 쓸 글꼴이 없다 — 깨진 글자를 넣지 않는다(그림만, 그림도 없으면 이름 대신 빈 글)
        if bg is not None:
            return stamp.StaticStampStyle(background=bg, background_opacity=1, border_width=0)
        raise SignError("no_font")
    kw = dict(stamp_text="\n".join(lines), border_width=0, timestamp_format="%Y-%m-%d %H:%M")
    if text_style is not None:
        kw["text_box_style"] = text_style
    if bg is not None:
        kw.update(background=bg, background_opacity=1)
        kw.update(_layout_kw(app.layout, box_w, box_h))
    return stamp.TextStampStyle(**kw)


def _layout_kw(layout: str, box_w: float, box_h: float) -> dict:
    """글자 배치(SOT §3.6) — 그림 왼쪽·글자 오른쪽(반반) / 그림 위 60%·글자 아래 40%. 겹쳐는 pyHanko 기본."""
    if layout not in ("image_left", "image_top") or box_w <= 0 or box_h <= 0:
        return {}
    from pyhanko.pdf_utils.layout import AxisAlignment, InnerScaling, Margins, SimpleBoxLayoutRule
    if layout == "image_left":
        half = box_w / 2.0
        bg = SimpleBoxLayoutRule(x_align=AxisAlignment.ALIGN_MIN, y_align=AxisAlignment.ALIGN_MID,
                                 margins=Margins(0, half, 0, 0), inner_content_scaling=InnerScaling.SHRINK_TO_FIT)
        tx = SimpleBoxLayoutRule(x_align=AxisAlignment.ALIGN_MIN, y_align=AxisAlignment.ALIGN_MID,
                                 margins=Margins(half + 2, 2, 0, 0))
    else:
        bg = SimpleBoxLayoutRule(x_align=AxisAlignment.ALIGN_MID, y_align=AxisAlignment.ALIGN_MAX,
                                 margins=Margins(0, 0, 0, box_h * 0.4), inner_content_scaling=InnerScaling.SHRINK_TO_FIT)
        tx = SimpleBoxLayoutRule(x_align=AxisAlignment.ALIGN_MID, y_align=AxisAlignment.ALIGN_MID,
                                 margins=Margins(0, 0, box_h * 0.6, 0))
    return {"background_layout": bg, "inner_content_layout": tx}


def preview_png(app: "Appearance", signer_text: str, reason: str, width_pt: float, height_pt: float,
                dpi: int = 110) -> bytes:
    """서명 겉모양 미리보기 PNG — **서명과 같은 그리기**(`_stamp_style` → pyHanko `create_stamp`)를 흰 쪽에 찍는다
    (보안 SOT §3.3). 0.2~0.4초(글꼴 부분집합) — 배경 스레드에서 부른다. 그릴 수 없으면 SignError(no_font)."""
    import fitz
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.layout import BoxConstraints
    w = max(8.0, float(width_pt))
    h = max(8.0, float(height_pt))
    d = fitz.open()
    pg = d.new_page(width=w, height=h)
    pg.draw_rect(pg.rect, color=None, fill=(1, 1, 1))     # 내용이 있어야 pyHanko 가 찍는다(/Contents 없으면 실패, 실측)
    data = d.tobytes()
    d.close()
    style = _stamp_style(app, signer_text, reason, w, h)
    wr = IncrementalPdfFileWriter(io.BytesIO(data))
    stamp = style.create_stamp(wr, BoxConstraints(width=w, height=h), {"signer": signer_text})
    stamp.apply(0, 0, 0)
    out = io.BytesIO()
    wr.write(out)
    pd = fitz.open("pdf", out.getvalue())
    try:
        return pd[0].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        pd.close()


def signer_label(name: str, email: str = "") -> str:
    """겉모양의 이름 칸 — pyHanko 가 인증서에서 쓰는 꼴과 같게 `이름 <이메일>`."""
    return f"{name} <{email}>" if email else name


def sign_pdf(src, dst, pfx: bytes, password: str, *, page_index: int = 0, box_pdf=None,
             appearance: Appearance | None = None, reason: str = "", location: str = "",
             doc_password: str = "", targets=None, certify: int = 0, tsa=None):
    """`src` 를 **증분 저장**으로 서명해 `dst` 에 쓴다(원본 바이트 + 덧붙인 서명, SOT §1·§3.3).

    - `box_pdf` 는 PDF 사용자 공간 (x0, y0, x1, y1) — `page_box_to_pdf` 로 만든다.
    - `targets=[(쪽, 상자), …]` 면 여러 쪽(SOT §3.6) — **모든 서명 칸을 첫 서명 전에 한 판에 만들고** 차례로 채운다
      (서명마다 칸을 더하면 인증 뒤 '허용 안 된 변경' 이 된다, 실측). 쪽마다 별도 승인 서명, 인증은 첫 쪽만.
    - `certify` 0 = 승인, 1·2·3 = DocMDP P. 문서의 첫 서명일 때만. P=1 은 한 쪽만.
    - `tsa` 는 타임스탬프 기관 주소(str) 또는 pyHanko TimeStamper(검사용). 받지 못하면 SignError(tsa_failed).
    - 암호 문서는 `doc_password` 로 연다(같은 암호화를 유지한 채 덧붙인다, SOT §3.5).
    반환: `targets` 를 주면 칸 이름 목록, 아니면 칸 이름 하나."""
    from pyhanko.sign import signers, fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    single = targets is None
    if single:
        targets = [(int(page_index), box_pdf)]
    targets = [(int(p), tuple(float(v) for v in b)) for p, b in targets]
    certify = int(certify or 0)
    if certify not in CERTIFY_LEVELS:
        raise ValueError("certify")
    if certify == 1 and len(targets) > 1:
        raise SignError("certify_one_page")
    key, cert, extra = load_pfx(pfx, password)
    signer = _simple_signer(key, cert, extra)
    app = appearance or Appearance()
    info = _cert_info(cert)
    stamper = None
    if tsa:
        if isinstance(tsa, str):
            from pyhanko.sign import timestamps
            stamper = timestamps.HTTPTimeStamper(tsa.strip(), timeout=20)
        else:
            stamper = tsa
    # 메모리로 읽고 곧 닫는다 — 배경 스레드가 원본 핸들을 오래 쥐면 Windows 에서 저장 바꿔치기가 거부된다(마스터 §4.7.5)
    with open(src, "rb") as f:
        data = f.read()

    def _writer(buf):
        try:
            w_ = IncrementalPdfFileWriter(io.BytesIO(buf), strict=False)
        except Exception as e:                   # noqa: BLE001 — 손상된 xref 등
            raise SignError("unreadable", type(e).__name__) from None
        if w_.prev.encrypted:
            if not doc_password:
                raise SignError("need_doc_password")
            try:
                w_.encrypt(doc_password)
            except Exception:
                raise SignError("need_doc_password") from None
            _fix_direct_encrypt(w_)
        return w_

    w = _writer(data)
    level = _certification_level(w.prev)
    if level == 1:
        raise SignError("certified")
    if level in (2, 3):
        raise SignError("certified_new_field")      # 새 서명 칸을 더하는 것은 허용 변경이 아니다(SOT §3.6)
    if certify and _has_signatures(w.prev):
        raise SignError("certify_not_first")
    names = _next_field_names(w.prev, len(targets))
    for nm, (pg, bx) in zip(names, targets):
        fields.append_signature_field(w, fields.SigFieldSpec(sig_field_name=nm, on_page=pg, box=bx))
    out = b""
    try:
        for i, (nm, (pg, bx)) in enumerate(zip(names, targets)):
            if i:
                w = _writer(out)
            cert_now = certify if i == 0 else 0
            meta = signers.PdfSignatureMetadata(
                field_name=nm, reason=reason or None, location=location or None,
                subfilter=fields.SigSeedSubFilter.PADES, md_algorithm="sha256",
                certify=bool(cert_now),
                docmdp_permissions=_mdp(cert_now) if cert_now else fields.MDPPerm.FILL_FORMS)
            style = _stamp_style(app, info.name, reason, bx[2] - bx[0], bx[3] - bx[1])
            ps = signers.PdfSigner(meta, signer=signer, stamp_style=style, timestamper=stamper)
            buf = io.BytesIO()
            ps.sign_pdf(w, output=buf)
            out = buf.getvalue()
    except SignError:
        raise
    except Exception as e:                       # noqa: BLE001
        nm_ = type(e).__name__
        if stamper is not None and ("Timestamp" in nm_ or "timestamp" in str(e).lower()
                                    or nm_ in ("ClientConnectorError", "TimeoutError", "ClientError")):
            raise SignError("tsa_failed", nm_ + ": " + str(e)[:200]) from None
        raise SignError("sign_failed", nm_ + ": " + str(e)[:200]) from None
    with open(str(dst), "wb") as f:
        f.write(out)
    return names[0] if single else names


def _mdp(level: int):
    from pyhanko.sign.fields import MDPPerm
    return {1: MDPPerm.NO_CHANGES, 2: MDPPerm.FILL_FORMS, 3: MDPPerm.ANNOTATE}[int(level)]


def _has_signatures(reader) -> bool:
    try:
        return bool(list(reader.embedded_signatures))
    except Exception:
        return False


def _next_field_names(reader, n: int) -> list:
    used = set()
    try:
        from pyhanko.sign.fields import enumerate_sig_fields
        for name, _v, _ref in enumerate_sig_fields(reader, filled_status=None):
            used.add(str(name))
    except Exception:
        pass
    out, k = [], 1
    while len(out) < n:
        nm = f"Signature{k}"
        if nm not in used:
            out.append(nm)
        k += 1
    return out


def signed_revision_bytes(path, field: str) -> bytes:
    """그 서명이 덮는 판 — `/ByteRange` 끝까지 자른 **서명할 때의 파일 그대로**(SOT §3.6 서명 시점 판)."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    with open(path, "rb") as fh:
        data = fh.read()
    r = PdfFileReader(io.BytesIO(data), strict=False)
    for es in r.embedded_signatures:
        if str(es.field_name) == str(field):
            br = list(es.sig_object["/ByteRange"])
            return data[: int(br[2]) + int(br[3])]
    raise KeyError(field)


def _fix_direct_encrypt(w) -> None:
    """PyMuPDF 가 암호화한 PDF 는 트레일러의 `/Encrypt` 가 **직접 사전**이다. pyHanko 쓰기는 그것이 간접
    객체라고 보고 `.idnum` 을 읽다 멈춘다(실측: AttributeError). 직접 사전은 따로 쓰이는 객체가 아니므로
    '어느 객체 번호와도 같지 않은' 표시만 붙이면 같은 암호화로 덧붙여 쓴다."""
    enc = getattr(w, "_encrypt", None)
    if enc is None or hasattr(enc, "idnum"):
        return
    try:
        enc.idnum = -1
    except Exception:
        from pyhanko.pdf_utils import generic

        class _DirectEncrypt(generic.DictionaryObject):
            idnum = -1
        w._encrypt = _DirectEncrypt(enc)


def _simple_signer(key, cert, extra):
    """cryptography 객체 → pyHanko SimpleSigner (비밀번호는 이미 풀렸다 — 다시 넘기지 않는다)."""
    from asn1crypto import keys as akeys, x509 as ax
    from cryptography.hazmat.primitives import serialization
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    der_key = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    acert = ax.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
    store = SimpleCertificateStore.from_certs(
        [ax.Certificate.load(c.public_bytes(serialization.Encoding.DER)) for c in extra])
    return signers.SimpleSigner(signing_cert=acert, signing_key=akeys.PrivateKeyInfo.load(der_key),
                                cert_registry=store)


def _certification_level(reader) -> int:
    """인증 서명의 DocMDP P(1·2·3), 없으면 0 — SOT §3.5·§3.6."""
    # pyHanko 사전의 .get() 은 간접 객체를 풀지 않는다(실측 — /DocMDP 가 IndirectObject 로 나와 늘 0 이었다) — [] 로 읽는다
    try:
        root = reader.root
        if "/Perms" not in root:
            return 0
        perms = root["/Perms"]
        if "/DocMDP" not in perms:
            return 0
        dmdp = perms["/DocMDP"]
        refs = dmdp["/Reference"] if "/Reference" in dmdp else []
        for ref in refs:
            if "/TransformParams" in ref:
                tp = ref["/TransformParams"]
                return int(tp["/P"]) if "/P" in tp else 2
        return 2
    except Exception:
        return 0


def _certified_no_changes(reader) -> bool:
    """이미 '변경 금지'(DocMDP P=1) 인증 서명이 있나 — SOT §3.5."""
    return _certification_level(reader) == 1


# ---------------------------------------------------------------------------
# 검증 — SOT §5
# ---------------------------------------------------------------------------

OK_TRUSTED, OK_UNKNOWN, MODIFIED, INVALID = "trusted", "unknown", "modified", "invalid"
_RANK = {OK_TRUSTED: 0, OK_UNKNOWN: 1, MODIFIED: 2, INVALID: 3}


@dataclass
class SigResult:
    field: str
    state: str                       # OK_TRUSTED | OK_UNKNOWN | MODIFIED | INVALID
    signer: str = ""
    email: str = ""
    org: str = ""
    time: str = ""                   # 서명한 PC 시계(타임스탬프 없음 — SOT §2)
    reason: str = ""
    location: str = ""
    fp: str = ""
    not_after: str = ""
    covers_whole: bool = False
    modification: str = ""           # none | form | annot | other
    detail: str = ""
    certify: int = 0                 # 0 = 승인 서명, 1·2·3 = 인증(DocMDP P) — SOT §3.6
    ts_time: str = ""                # 타임스탬프 기관 시각(있으면)
    ts_name: str = ""                # 타임스탬프 기관 이름(인증서 CN)


@dataclass
class VerifyReport:
    sigs: list = field(default_factory=list)
    error: str = ""

    @property
    def worst(self) -> str:
        if not self.sigs:
            return INVALID if self.error else ""
        return max((s.state for s in self.sigs), key=lambda s: _RANK[s])


def _quiet_pyhanko_logs() -> None:
    """자체 서명 ID 는 경로 검증이 늘 실패해 pyHanko 가 그때마다 스택을 찍는다 — 판정은 지문으로 하므로 소음이다."""
    import logging
    for n in ("pyhanko", "pyhanko_certvalidator"):
        logging.getLogger(n).setLevel(logging.CRITICAL)


def verify_pdf(path, trusted_fps=(), doc_password: str = "") -> VerifyReport:
    """모든 서명을 검증한다. 신뢰는 **지문 목록**으로 판정한다(자체 서명 ID 는 인증서 경로 검증에서
    신뢰 근거가 될 수 없다 — pyHanko 는 자체 서명 잎 인증서를 신뢰 루트로 받지 않는다, 실측)."""
    rep = VerifyReport()
    _quiet_pyhanko_logs()
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko.sign.validation.status import SignatureCoverageLevel
        from pyhanko_certvalidator import ValidationContext
    except Exception as e:                       # noqa: BLE001
        rep.error = "lib:" + type(e).__name__
        return rep
    trusted = {str(f).lower() for f in (trusted_fps or ())}
    try:
        # 메모리로 읽고 곧 닫는다 — 검증 중 사용자가 저장해도 원본 핸들을 쥐고 있지 않게(마스터 §4.7.5)
        with open(path, "rb") as fh:
            data = fh.read()
        r = PdfFileReader(io.BytesIO(data), strict=False)
        if r.encrypted:
            if not doc_password:
                rep.error = "need_doc_password"
                return rep
            r.decrypt(doc_password)
        for es in r.embedded_signatures:
            res = SigResult(field=str(es.field_name or ""), state=INVALID)
            try:
                st = validate_pdf_signature(es, ValidationContext(trust_roots=[], allow_fetching=False))
                cert = st.signing_cert
                res.fp = cert.sha256.hex() if hasattr(cert, "sha256") else cert_fingerprint(cert.dump())
                try:
                    na = cert.not_valid_after
                    res.not_after = na.strftime("%Y-%m-%d")
                except Exception:
                    pass
                subj = cert.subject.native
                res.signer = str(subj.get("common_name", "") or "")
                res.email = str(subj.get("email_address", "") or "")
                res.org = str(subj.get("organization_name", "") or "")
                t = getattr(st, "signer_reported_dt", None)
                if t is not None:
                    res.time = t.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                sd = es.sig_object
                res.reason = str(sd.get("/Reason", "") or "")
                res.location = str(sd.get("/Location", "") or "")
                res.covers_whole = st.coverage == SignatureCoverageLevel.ENTIRE_FILE
                ml = getattr(st, "modification_level", None)
                ml_name = getattr(ml, "name", "") if ml is not None else ""
                res.modification = {"NONE": "none", "LTA_UPDATES": "none", "FORM_FILLING": "form",
                                    "ANNOTATIONS": "annot", "OTHER": "other"}.get(ml_name, "other")
                try:
                    lvl = getattr(es, "docmdp_level", None)
                    res.certify = int(getattr(lvl, "value", 0) or 0) if lvl is not None else 0
                except Exception:
                    res.certify = 0
                tsv = getattr(st, "timestamp_validity", None)
                if tsv is not None:
                    try:
                        res.ts_time = tsv.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                        res.ts_name = str(tsv.signing_cert.subject.native.get("common_name", "") or "")
                    except Exception:
                        pass
                docmdp_ok = getattr(st, "docmdp_ok", None)
                if not (st.intact and st.valid):
                    res.state = INVALID
                elif docmdp_ok is False:
                    # 인증 서명이 허용하지 않은 변경(또는 그 뒤 새 서명 칸) — pyHanko 판정(SOT §5)
                    res.state = MODIFIED
                elif not res.covers_whole and res.modification not in ("none", "form"):
                    # 뒤에 덧붙은 것이 서명·양식 채우기뿐이면 허용된 변경이다(Acrobat 과 같다) — 그 밖은 '변경됨'
                    res.state = MODIFIED
                else:
                    res.state = OK_TRUSTED if res.fp.lower() in trusted else OK_UNKNOWN
            except Exception as e:               # noqa: BLE001
                res.state = INVALID
                res.detail = type(e).__name__
            rep.sigs.append(res)
    except Exception as e:                       # noqa: BLE001
        rep.error = type(e).__name__
    return rep
