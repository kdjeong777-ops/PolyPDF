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


def _pfx_bytes(key, cert, friendly: str, password: str, cas=None) -> bytes:
    """PBES2 + AES-256-CBC + PBKDF2-SHA256 으로 잠근 PKCS#12 (SOT §3.2 — 3DES/RC2 금지)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    enc = (serialization.PrivateFormat.PKCS12.encryption_builder()
           .kdf_rounds(PFX_KDF_ROUNDS)
           .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
           .hmac_hash(hashes.SHA256())
           .build(password.encode("utf-8")))
    return pkcs12.serialize_key_and_certificates((friendly or "PolyPDF").encode("utf-8"), key, cert, list(cas) if cas else None, enc)


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
    key, cert, extra = load_pfx(data, password)
    # 기관이 준 중간 인증서는 남긴다 — 버리면 서명에 체인이 빠져 Acrobat 이 '신원 미확인' 으로 본다(261011-1)
    return _pfx_bytes(key, cert, info.name, password, cas=extra), info


def pfx_info(data: bytes, password: str) -> IdInfo:
    _key, cert, _ = load_pfx(data, password)
    return _cert_info(cert)


def pfx_self_signed(data: bytes, password: str) -> bool:
    """자체 서명 인증서(발급자 = 주체)인가 — '내용 고치기'(새로 발급)는 이것만(보안 SOT §3.2, 261031-6).
    기관이 발급한 인증서는 PolyPDF 가 다시 발급할 수 없다."""
    _key, cert, _ = load_pfx(data, password)
    return cert is not None and cert.issuer == cert.subject


MM_PER_PT = 25.4 / 72.0


def real_box_pt(width_mm: float, img_w: float = 0.0, img_h: float = 0.0) -> tuple:
    """서명 그림 실제 크기 → 쪽 단위(pt) (폭, 높이) — 높이는 그림 비율, 그림이 없으면 폭 ÷ 2.5(보안 SOT §3.3, 261031-6)."""
    w = float(width_mm) / MM_PER_PT
    h = w * float(img_h) / float(img_w) if img_w > 0 and img_h > 0 else w / 2.5
    return (w, h)


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
    layout: str = "image_top"       # SOT §3.6: image_top(그림 위·글자 아래 — 기본, 261012-1) | overlay | image_left


LAYOUTS = ("image_top", "overlay", "image_left")
LAYOUT_DEFAULT = "image_top"
TEXT_PT_MAX = 9.0                    # 겉모양 글자 — 9pt 에서 줄 전체가 들어가게 줄인다(SOT §3.6, 261012-1)
TEXT_PT_MIN = 6.0                    # 이보다 작아져야 하면 줄을 바꾼다
TEXT_LEAD_PT = 11                    # 줄 간격(pyHanko TL 은 정수)
TEXT_PAD_PT = 1.5                    # 글자 줄 위아래 여백
_TS_FORMAT = "%Y-%m-%d %H:%M"
_TS_SAMPLE = "2026-12-31 23:59"      # 날짜 줄 너비를 잴 때(%(ts)s 는 서명할 때 채워진다)
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
    """보이는 쪽 좌표(fitz, 왼쪽 위 원점 — 회전 적용 뒤) 사각형 → PDF 사용자 공간(왼쪽 아래 원점) 상자.

    회전한 쪽은 `derotation_matrix` 로 회전 전 좌표로 돌린 뒤(261011-2, SOT §3.3) — 회전 0 이면 그대로.
    MediaBox 원점이 0 이 아닌 쪽도 맞도록 `transformation_matrix` 의 역행렬을 쓴다(마스터 §4.7.15 와 같은 함정)."""
    import fitz
    r = fitz.Rect(rect)
    if int(page.rotation) % 360:
        r = r * page.derotation_matrix
        r.normalize()
    m = ~page.transformation_matrix
    q = r * m
    q.normalize()
    return (q.x0, q.y0, q.x1, q.y1)


class _Measure:
    """겉모양 글자 너비 재기 — 서명에 넣는 글꼴 그대로(`fitz.Font`). 글꼴이 없으면 pyHanko 기본(Courier, 0.6em)."""

    def __init__(self, font_path: str = ""):
        self._f = None
        if font_path and os.path.exists(font_path):
            try:
                import fitz
                self._f = fitz.Font(fontfile=font_path)
            except Exception:
                self._f = None

    def width(self, text: str, size: float) -> float:
        if self._f is not None:
            return float(self._f.text_length(text, fontsize=size))
        return 0.6 * size * len(text)


def _wrap_line(m: "_Measure", line: str, size: float, width: float) -> list:
    """한 줄을 폭에 맞게 나눈다 — `이름 <이메일>` 은 ' <' 앞에서, 그다음 빈칸·'@'·'.' 앞, 그래도 길면 글자 단위."""
    if m.width(line, size) <= width:
        return [line]
    for sep in (" <", " ", "@", "."):           # 이메일은 @·. 앞에서
        k = line.rfind(sep)
        while k > 0:
            head = line[:k].rstrip()
            if head and m.width(head, size) <= width:
                return [head] + _wrap_line(m, line[k:].strip(), size, width)
            k = line.rfind(sep, 0, k)
    out, cur = [], ""
    for ch in line:
        if cur and m.width(cur + ch, size) > width:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


@dataclass
class TextLayout:
    size: float = 9.0                # 실제로 찍히는 크기(pt) = TEXT_PT_MAX × scale
    lines: tuple = ()                # 넣을 글(날짜 줄은 `%(ts)s` 그대로)
    height: float = 0.0              # 글자 줄 전체 높이(여백 포함)
    scale: float = 1.0               # 9pt 로 쓴 글자 상자를 줄이는 비율(pyHanko SHRINK_TO_FIT 가 그대로 한다)


def _text_lines(app: Appearance, signer_text: str, reason: str) -> list:
    lines = []
    if app.show_name and signer_text:
        lines.append(signer_text)
    if app.show_date:
        lines.append("%(ts)s")
    if app.show_reason and reason:
        lines.append(reason)
    return lines


def text_layout(app: Appearance, signer_text: str, reason: str, width_pt: float, height_pt: float = 0.0) -> TextLayout:
    """겉모양 글자 줄 — **줄 전체가 보이게**(SOT §3.6, 261012-1 사용자 보고: 이메일·일시 끝이 잘렸다).

    글자는 늘 9pt·줄 간격 11pt 로 쓰고(pyHanko 는 `Tf`·`TL` 을 정수로만 적는다 — `%d`, 실측) 상자 맞춤 축소
    (SHRINK_TO_FIT)로 줄인다. 가장 긴 줄이 `width_pt` 에 들어가는 비율을 구하고, 6pt 아래가 되면 그 대신 줄을 바꾼다.
    `height_pt` 를 주면(겹쳐·왼쪽 배치·빈 칸 — 칸이 정해져 있다) 줄 수가 그 높이에 들어가게 더 줄인다."""
    raw = _text_lines(app, signer_text, reason)
    if not raw:
        return TextLayout(TEXT_PT_MAX, (), 0.0, 1.0)
    m = _Measure(app.font_path)
    avail = max(4.0, float(width_pt) - 2 * TEXT_PAD_PT)
    base, lead = TEXT_PT_MAX, TEXT_LEAD_PT

    def _w(line):
        return m.width(_TS_SAMPLE if line == "%(ts)s" else line, base)
    lines = list(raw)
    scale = min(1.0, avail / (max(_w(ln) for ln in lines) or 1.0))
    if base * scale < TEXT_PT_MIN:
        lines = []
        for ln in raw:
            lines.extend([ln] if ln == "%(ts)s" else _wrap_line(m, ln, base, avail * base / TEXT_PT_MIN))
        scale = min(1.0, avail / (max(_w(ln) for ln in lines) or 1.0))   # 끊을 수 없는 날짜 줄 등은 더 줄인다
    if height_pt and height_pt > 0:
        room = max(1.0, float(height_pt) - 2 * TEXT_PAD_PT)
        scale = min(scale, room / (len(lines) * lead))
    return TextLayout(round(base * scale, 2), tuple(lines), len(lines) * lead * scale + 2 * TEXT_PAD_PT, scale)


def _has_image(app: Appearance) -> bool:
    return bool(app.image_path and os.path.exists(app.image_path))


def has_content(app: Appearance, signer_text: str = "", reason: str = "") -> bool:
    """겉모양에 그릴 것이 있나 — 그림이나 글자 줄 하나. 둘 다 없으면 서명하지 않는다(261031-1, SOT §3.3 —
    종전에는 pyHanko 기본 글자 `%(signer)s` 를 찍어 미리보기에 엉뚱한 글자가 나왔다)."""
    return _has_image(app) or bool(_text_lines(app, signer_text, reason))


def fit_left(box, img_w: float, img_h: float) -> tuple:
    """상자 안에 그림을 **비율 그대로** 가장 크게 — 왼쪽 위에 붙이고 남는 오른쪽·아래는 비운다(261031-1, SOT §3.11).
    `box` = (x0, y0, x1, y1) 왼쪽 위 원점(fitz·화면 좌표)."""
    x0, y0, x1, y1 = (float(v) for v in box)
    w, h = max(0.0, x1 - x0), max(0.0, y1 - y0)
    if img_w <= 0 or img_h <= 0 or w <= 0 or h <= 0:
        return (x0, y0, x1, y1)
    k = min(w / img_w, h / img_h)
    return (x0, y0, x0 + img_w * k, y0 + img_h * k)


def stamp_size(app: Appearance, signer_text: str, reason: str, width_pt: float, height_pt: float) -> tuple:
    """끈 상자(= 그림 자리) → 실제 서명 영역 (폭, 높이). '그림 위·글자 아래' 에서 그림과 글자가 둘 다 있으면
    글자 줄을 상자 **아래에 덧붙인다**(SOT §3.6). 그 밖은 상자 그대로."""
    w, h = float(width_pt), float(height_pt)
    if (app.layout or LAYOUT_DEFAULT) == "image_top" and _has_image(app):
        tl = text_layout(app, signer_text, reason, w)
        if tl.lines:
            return (w, h + tl.height)
    return (w, h)


def _font_factory(font_path: str, size):
    """pyHanko 글꼴 넣기 — **글꼴 단위가 1000 이 아닌 글꼴**(맑은 고딕 = 2048)도 바른 폭으로.

    pyHanko 0.37 은 `/W` 글자 폭을 글꼴 단위 그대로 적는다 — PDF 는 1000 단위로 읽으므로 맑은 고딕 글자가
    약 2배 넓게 찍혀 줄 끝이 상자 밖으로 잘렸다(261012-1 사용자 보고, 실측 `/W [3 [720] … 19 [1128 …]]`).
    HarfBuzz 배율을 1000 으로 두고 폭도 1000 단위로 바꿔, 위치 계산과 `/W` 를 같은 단위로 맞춘다."""
    from pyhanko.pdf_utils.font.opentype import GlyphAccumulator, GlyphAccumulatorFactory

    class _Acc(GlyphAccumulator):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._upem0 = int(self.units_per_em or 1000)
            if self._upem0 != 1000:
                self.hb_font.scale = (1000, 1000)
                self.units_per_em = 1000

        def _get_cid_and_width(self, glyph_id):
            cid, w = super()._get_cid_and_width(glyph_id)
            return cid, (int(round(w * 1000 / self._upem0)) if self._upem0 != 1000 else w)

        def prepare_write(self):
            if self._upem0 != 1000 and not self._write_prepared:
                self._glyphs = {g: (cid, int(round(w * 1000 / self._upem0))) for g, (cid, w) in self._glyphs.items()}
                self._upem0 = 1000
            return super().prepare_write()

    class _Factory(GlyphAccumulatorFactory):
        def create_font_engine(self, writer, obj_stream=None):
            fh = open(self.font_file, "rb")  # noqa: SIM115 — pyHanko 와 같이 엔진이 쥔다
            if obj_stream is None and writer.stream_xrefs and self.create_objstream_if_needed:
                obj_stream = writer.prepare_object_stream()
            return _Acc(writer=writer, font_handle=fh, font_size=self.font_size, obj_stream=obj_stream)

    return _Factory(font_path, font_size=size)


def _stamp_style(app: Appearance, signer_text: str, reason: str, box_w: float = 0.0, box_h: float = 0.0):
    """서명 겉모양 스타일. `box_w`·`box_h`(pt)는 **서명 영역 전체**(`stamp_size` 결과 · 빈 칸이면 칸 크기).
    `signer_text` 는 겉모양 이름 줄(`signer_label` — 이름 <이메일>)."""
    from pyhanko import stamp
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.pdf_utils.layout import AxisAlignment, InnerScaling, Margins, SimpleBoxLayoutRule
    bg = None
    if _has_image(app):
        from PIL import Image
        bg = PdfImage(Image.open(app.image_path).convert("RGBA"))
    from pyhanko.pdf_utils.layout import AxisAlignment as _AA, SimpleBoxLayoutRule as _SB, InnerScaling as _IS
    # 261031-1(사용자 지시): 그림·글자는 상자 **왼쪽**에 붙인다(종전 가운데)
    _img_left = _SB(x_align=_AA.ALIGN_MIN, y_align=_AA.ALIGN_MID, inner_content_scaling=_IS.STRETCH_TO_FIT)
    raw = _text_lines(app, signer_text, reason)
    if not raw:
        if bg is None:
            raise SignError("empty_appearance")       # 261031-1: 그릴 것이 없다 — 종전 '%(signer)s' 기본 글자를 찍지 않는다
        return stamp.StaticStampStyle(background=bg, background_opacity=1, border_width=0, background_layout=_img_left)
    font_ok = bool(app.font_path and os.path.exists(app.font_path) and app.font_path.lower().endswith((".ttf", ".otf")))
    if not font_ok and any(ord(c) > 127 for c in (signer_text + reason)):
        # 한글을 쓸 글꼴이 없다 — 깨진 글자를 넣지 않는다(그림만, 그림도 없으면 거부)
        if bg is not None:
            return stamp.StaticStampStyle(background=bg, background_opacity=1, border_width=0, background_layout=_img_left)
        raise SignError("no_font")
    layout = app.layout or LAYOUT_DEFAULT
    w, h = max(1.0, float(box_w or 0)), max(1.0, float(box_h or 0))
    mid, lo = AxisAlignment.ALIGN_MID, AxisAlignment.ALIGN_MIN
    fit, shrink = InnerScaling.STRETCH_TO_FIT, InnerScaling.SHRINK_TO_FIT
    # 261031-1(사용자 지시): 가로는 모두 왼쪽 정렬(`lo`) — 그림·글자 줄이 상자 왼쪽에 붙고 남는 오른쪽은 빈다
    if bg is None:                               # 글자만 — 상자 가득
        tl = text_layout(app, signer_text, reason, w, h)
        kw = {"inner_content_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid, margins=Margins.uniform(TEXT_PAD_PT),
                                                          inner_content_scaling=shrink)}
    elif layout == "image_left":
        half = w / 2.0
        tl = text_layout(app, signer_text, reason, half, h)
        kw = {"background_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid, margins=Margins(0, half, 0, 0),
                                                       inner_content_scaling=fit),
              "inner_content_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid,
                                                          margins=Margins(half + TEXT_PAD_PT, TEXT_PAD_PT, TEXT_PAD_PT, TEXT_PAD_PT),
                                                          inner_content_scaling=shrink)}
    elif layout == "overlay":
        tl = text_layout(app, signer_text, reason, w, h)
        kw = {"background_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid, inner_content_scaling=fit),
              "inner_content_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid, margins=Margins.uniform(TEXT_PAD_PT),
                                                          inner_content_scaling=shrink)}
    else:                                        # image_top — 위 그림(비율 유지, 꽉 차게) · 아래 글자 줄
        tl = text_layout(app, signer_text, reason, w)
        strip = min(tl.height, h * 0.9)
        kw = {"background_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid, margins=Margins(0, 0, 0, strip),
                                                       inner_content_scaling=fit),
              "inner_content_layout": SimpleBoxLayoutRule(x_align=lo, y_align=mid,
                                                          margins=Margins(TEXT_PAD_PT, TEXT_PAD_PT,
                                                                          max(0.0, h - strip) + TEXT_PAD_PT, TEXT_PAD_PT),
                                                          inner_content_scaling=shrink)}
    text = "\n".join(ln if ln == "%(ts)s" else ln.replace("%", "%%") for ln in tl.lines)
    st = dict(stamp_text=text, border_width=0, timestamp_format=_TS_FORMAT, **kw)
    if font_ok:
        from pyhanko.pdf_utils.text import TextBoxStyle
        # 여백 0 — pyHanko 기본 글자 상자 여백(사방 10pt)이 글자를 크게 줄였다(실측). 크기는 정수(9pt), 줄이기는 배치 규칙이
        st["text_box_style"] = TextBoxStyle(font=_font_factory(app.font_path, int(TEXT_PT_MAX)), font_size=int(TEXT_PT_MAX),
                                            leading=int(TEXT_LEAD_PT),
                                            box_layout_rule=SimpleBoxLayoutRule(x_align=lo, y_align=mid,
                                                                                margins=Margins(0, 0, 0, 0)))
    if bg is not None:
        st.update(background=bg, background_opacity=1)
    return stamp.TextStampStyle(**st)


def preview_png(app: "Appearance", signer_text: str, reason: str, width_pt: float, height_pt: float,
                dpi: int = 110) -> bytes:
    """서명 겉모양 미리보기 PNG — **서명과 같은 그리기**(`_stamp_style` → pyHanko `create_stamp`)를 **투명 바탕**에 찍는다
    (보안 SOT §3.3 — 261031-1: 서명 자리 아래의 본문이 보이게. 종전 흰 바탕은 자리 밑 글을 가렸다).
    0.2~0.4초(글꼴 부분집합) — 배경 스레드에서 부른다. 그릴 수 없으면 SignError(no_font·empty_appearance)."""
    import fitz
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.layout import BoxConstraints
    w = max(8.0, float(width_pt))
    h = max(8.0, float(height_pt))
    d = fitz.open()
    pg = d.new_page(width=w, height=h)
    # 내용이 있어야 pyHanko 가 찍는다(/Contents 없으면 실패, 실측) — 보이지 않는 사각형 하나
    pg.draw_rect(pg.rect, color=None, fill=(1, 1, 1), fill_opacity=0)
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
        return pd[0].get_pixmap(dpi=dpi, alpha=True).tobytes("png")
    finally:
        pd.close()


def signer_label(name: str, email: str = "") -> str:
    """겉모양의 이름 칸 — pyHanko 가 인증서에서 쓰는 꼴과 같게 `이름 <이메일>`."""
    return f"{name} <{email}>" if email else name


def sign_pdf(src, dst, pfx: bytes, password: str, *, page_index: int = 0, box_pdf=None,
             appearance: Appearance | None = None, reason: str = "", location: str = "",
             doc_password: str = "", targets=None, certify: int = 0, tsa=None, field: str = "", signer=None):
    """`src` 를 **증분 저장**으로 서명해 `dst` 에 쓴다(원본 바이트 + 덧붙인 서명, SOT §1·§3.3).

    - `box_pdf` 는 PDF 사용자 공간 (x0, y0, x1, y1) — `page_box_to_pdf` 로 만든다.
    - `targets=[(쪽, 상자), …]` 면 여러 쪽(SOT §3.6) — **모든 서명 칸을 첫 서명 전에 한 판에 만들고** 차례로 채운다
      (서명마다 칸을 더하면 인증 뒤 '허용 안 된 변경' 이 된다, 실측). 쪽마다 별도 승인 서명, 인증은 첫 쪽만.
    - `certify` 0 = 승인, 1·2·3 = DocMDP P. 문서의 첫 서명일 때만. P=1 은 한 쪽만.
    - `tsa` 는 타임스탬프 기관 주소(str) 또는 pyHanko TimeStamper(검사용). 받지 못하면 SignError(tsa_failed).
    - 암호 문서는 `doc_password` 로 연다(같은 암호화를 유지한 채 덧붙인다, SOT §3.5).
    - `field` 면 **이미 있는 빈 서명 칸**을 채운다(SOT §3.7) — 칸을 만들지 않으므로 인증(P=2·3) 문서에도 된다.
    - `signer` 면 `pfx`·`password` 대신 그 pyHanko Signer(Windows 저장소 키, SOT §3.9).
    반환: `targets` 를 주면 칸 이름 목록, 아니면 칸 이름 하나."""
    from pyhanko.sign import signers, fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    single = targets is None
    field = str(field or "")
    certify = int(certify or 0)
    if certify not in CERTIFY_LEVELS:
        raise ValueError("certify")
    if field:
        targets = []
    else:
        if single:
            targets = [(int(page_index), box_pdf)]
        targets = [(int(p), tuple(float(v) for v in b)) for p, b in targets]
        if certify == 1 and len(targets) > 1:
            raise SignError("certify_one_page")
    if signer is None:
        key, cert, extra = load_pfx(pfx, password)
        signer = _simple_signer(key, cert, extra)
        info = _cert_info(cert)
    else:
        info = _cert_info(_asn1_to_crypto(signer.signing_cert))
    app = appearance or Appearance()
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
    rots = _page_rotations(data, doc_password)     # 회전한 쪽은 겉모양을 반대로 돌려 넣는다(SOT §3.3, 261011-2)
    level = _certification_level(w.prev)
    if level == 1:
        raise SignError("certified")
    if level in (2, 3) and not field:
        raise SignError("certified_new_field")      # 새 서명 칸을 더하는 것은 허용 변경이 아니다(SOT §3.6)
    if certify and _has_signatures(w.prev):
        raise SignError("certify_not_first")
    if field:
        # 빈 칸 채우기(SOT §3.7) — 칸이 있고 비어 있어야 한다. 겉모양 크기는 그 칸의 /Rect
        size = _empty_field_size(w.prev, field)
        if size is None:
            raise SignError("no_field", field)
        names = [field]
        targets = [(_field_page(data, doc_password, field), (0.0, 0.0) + size)]
    else:
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
            rot = rots[pg] if 0 <= pg < len(rots) else 0
            bw, bh = bx[2] - bx[0], bx[3] - bx[1]
            if rot in (90, 270):
                bw, bh = bh, bw                    # 글자 배치는 보이는 방향의 폭·높이로
            style = _rotate_style(_stamp_style(app, signer_label(info.name, info.email), reason, bw, bh), rot)
            ps = signers.PdfSigner(meta, signer=signer, stamp_style=style, timestamper=stamper)
            buf = io.BytesIO()
            ps.sign_pdf(w, output=buf)
            out = buf.getvalue()
    except SignError:
        raise
    except Exception as e:                       # noqa: BLE001
        from viewer.sign_winstore import StoreError
        if isinstance(e, StoreError):
            raise                                # 저장소 취소·사라짐은 화면이 따로 다룬다(SOT §3.9)
        nm_ = type(e).__name__
        if nm_ == "UnacceptableSignerError":
            raise SignError("wrong_signer", str(e)[:200]) from None     # 칸의 '서명할 사람' 이 아니다(SOT §3.7)
        if stamper is not None and ("Timestamp" in nm_ or "timestamp" in str(e).lower()
                                    or nm_ in ("ClientConnectorError", "TimeoutError", "ClientError")):
            raise SignError("tsa_failed", nm_ + ": " + str(e)[:200]) from None
        raise SignError("sign_failed", nm_ + ": " + str(e)[:200]) from None
    with open(str(dst), "wb") as f:
        f.write(out)
    return names[0] if single else names


def _page_rotations(data: bytes, doc_password: str = "") -> list:
    """쪽마다 `/Rotate`(0·90·180·270). 읽지 못하면 빈 목록(= 회전 없음)."""
    try:
        import fitz
        d = fitz.open("pdf", data)
        if d.needs_pass:
            d.authenticate(doc_password or "")
        out = [int(p.rotation) % 360 for p in d]
        d.close()
        return out
    except Exception:
        return []


def _field_page(data: bytes, doc_password: str, name: str) -> int:
    """서명 칸 `name` 이 있는 쪽(0부터), 모르면 -1."""
    try:
        import fitz
        d = fitz.open("pdf", data)
        if d.needs_pass:
            d.authenticate(doc_password or "")
        for page in d:
            for w in page.widgets() or []:
                if w.field_name == name:
                    n = page.number
                    d.close()
                    return n
        d.close()
    except Exception:
        pass
    return -1


_ROT_MATRIX = {90: (0, 1, -1, 0), 180: (-1, 0, 0, -1), 270: (0, -1, 1, 0)}


def _rotate_style(style, rot: int):
    """회전한 쪽(`/Rotate`)용 스탬프 스타일 — 겉모양 그림(form XObject)에 쪽 회전만큼 **반대로 돌리는 `/Matrix`** 를 넣고,
    90·270 이면 상자의 폭·높이를 바꿔 글자를 배치한다(SOT §3.3, 261011-2). 실측: 90·180·270 × MuPDF·pdfium 모두
    끈 상자 안에 바로 선다. pyHanko `NoRotate` 깃발은 자리가 벗어나 쓰지 않는다."""
    rot = int(rot or 0) % 360
    if rot not in _ROT_MATRIX:
        return style
    import dataclasses
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.layout import BoxConstraints
    m = _ROT_MATRIX[rot]
    base = type(style)

    class _Rotated(base):
        def create_stamp(self, writer, box, text_params):
            if rot in (90, 270) and box is not None:
                box = BoxConstraints(width=box.height, height=box.width)
            st = super().create_stamp(writer, box, text_params)
            fx = st.as_form_xobject

            def _as_fx():
                o = fx()
                o["/Matrix"] = generic.ArrayObject([generic.FloatObject(v) for v in m]
                                                   + [generic.FloatObject(0), generic.FloatObject(0)])
                return o
            st.as_form_xobject = _as_fx
            return st
    _Rotated.__name__ = base.__name__
    return _Rotated(**{f.name: getattr(style, f.name) for f in dataclasses.fields(style)})


def _asn1_to_crypto(acert):
    from cryptography import x509
    return x509.load_der_x509_certificate(acert.dump())


def _empty_field_size(reader, name: str):
    """빈 서명 칸 `name` 의 겉모양 크기 (폭, 높이) — 없거나 이미 서명됐으면 None."""
    from pyhanko.sign.fields import enumerate_sig_fields
    for nm, val, ref in enumerate_sig_fields(reader, filled_status=None):
        if str(nm) != name:
            continue
        if val is not None:
            return None
        fld = ref.get_object()
        widget = fld
        if "/Rect" not in fld and "/Kids" in fld:
            widget = fld["/Kids"][0].get_object()
        try:
            r = [float(x) for x in widget["/Rect"]]
            return (abs(r[2] - r[0]), abs(r[3] - r[1]))
        except Exception:
            return (0.0, 0.0)
    return None


@dataclass
class EmptyField:
    name: str
    page: int                   # 0부터
    rect: tuple                 # 쪽 좌표(fitz, 왼쪽 위 원점) x0, y0, x1, y1
    lock: bool = False          # 서명하면 칸을 잠근다(FieldMDP /Lock, SOT §3.7)
    signer_fps: tuple = ()      # 서명할 사람 인증서 SHA-256 지문(시드 값 /SV /Cert /Subject) — 비면 누구나
    signer_names: tuple = ()


def _field_extras(doc, xref):
    """빈 칸 위젯의 잠금·서명할 사람 — fitz xref 로 읽는다(합친 칸/위젯, 아니면 부모)."""
    import re
    lock, fps, names = False, [], []
    for base in (xref, None):
        if base is None:
            t, v = doc.xref_get_key(xref, "Parent")
            if t != "xref":
                break
            base = int(v.split()[0])
        try:
            if doc.xref_get_key(base, "Lock")[0] != "null":
                lock = True
            t, v = doc.xref_get_key(base, "SV/Cert/Subject")
            if t == "array" and not fps:
                ders = [bytes.fromhex(h) for h in re.findall(r"<([0-9A-Fa-f\s]+)>", v)]
                ders += [doc.xref_stream(int(m)) for m in re.findall(r"(\d+) 0 R", v)]
                for der in ders:
                    try:
                        from cryptography import x509
                        c = x509.load_der_x509_certificate(der)
                        fps.append(cert_fingerprint(der))
                        names.append(_cert_info(c).name)
                    except Exception:
                        pass
        except Exception:
            pass
    return lock, tuple(fps), tuple(names)


def empty_fields(doc) -> list:
    """열린 fitz 문서의 **빈 서명 칸**(SOT §3.7). 양식 문서일 때만 쪽을 돈다 — 보통 문서는 바로 빈 목록(§10)."""
    try:
        if not doc.is_form_pdf:
            return []
        import fitz
        out = []
        for page in doc:
            for w in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []:
                if not getattr(w, "is_signed", False):
                    r = w.rect
                    lock, fps, names = _field_extras(doc, w.xref)
                    out.append(EmptyField(str(w.field_name or ""), page.number, (r.x0, r.y0, r.x1, r.y1),
                                          lock, fps, names))
        return out
    except Exception:
        return []


def doc_certify_level(doc) -> int:
    """열린 fitz 문서의 인증 서명 DocMDP P(1·2·3), 없으면 0 — 화면 판정용(서명 자체는 `_certification_level` 이 다시 본다)."""
    import re
    try:
        cat = doc.pdf_catalog()
        t, v = doc.xref_get_key(cat, "Perms/DocMDP")
        if t != "xref":
            return 0
        sx = int(v.split()[0])
        t, v = doc.xref_get_key(sx, "Reference")
        if t == "null":
            return 2
        text = v
        for m in re.finditer(r"(\d+) 0 R", v):
            text += doc.xref_object(int(m.group(1)), compressed=True)
        m = re.search(r"/TransformParams.*?/P\s*(\d)", text, re.S)
        return int(m.group(1)) if m else 2
    except Exception:
        return 0


def field_at(fields_, page: int, x: float, y: float):
    """쪽 좌표 (x, y) 를 품은 빈 칸 — 없으면 None(SOT §3.7 '끌기·우클릭의 가운데가 빈 칸 안이면')."""
    for f in fields_:
        x0, y0, x1, y1 = f.rect
        if f.page == page and x0 <= x <= x1 and y0 <= y <= y1:
            return f
    return None


def add_empty_field(src, dst, *, page_index: int, box_pdf, name: str = "", doc_password: str = "",
                    lock: bool = False, signer_certs=()) -> str:
    """빈 서명 칸 하나를 **증분으로** 덧붙여 `dst` 에 쓴다(SOT §3.7). 반환: 칸 이름.
    인증 문서(P 무엇이든)는 거부 — 칸을 더하는 것이 허용 변경이 아니다(§3.6). 이름이 겹치면 `field_exists`.
    `lock` 이면 서명하면 **모든 칸**을 잠근다(FieldMDP All — Include/Exclude 는 쓰지 않는다, SOT §3.7 실측).
    `signer_certs`(DER 목록)면 그 인증서로만 서명하게 한다(시드 값 /SV /Cert /Subject, 필수)."""
    from pyhanko.sign import fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    with open(src, "rb") as f:
        data = f.read()
    try:
        w = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    except Exception as e:                       # noqa: BLE001
        raise SignError("unreadable", type(e).__name__) from None
    if w.prev.encrypted:
        if not doc_password:
            raise SignError("need_doc_password")
        try:
            w.encrypt(doc_password)
        except Exception:
            raise SignError("need_doc_password") from None
        _fix_direct_encrypt(w)
    level = _certification_level(w.prev)
    if level == 1:
        raise SignError("certified")
    if level:
        raise SignError("certified_new_field")
    name = (name or "").strip()
    if name:
        from pyhanko.sign.fields import enumerate_sig_fields
        if any(str(n) == name for n, _v, _r in enumerate_sig_fields(w.prev, filled_status=None)):
            raise SignError("field_exists", name)
    else:
        name = _next_field_names(w.prev, 1)[0]
    kw = {}
    if lock:
        kw["field_mdp_spec"] = fields.FieldMDPSpec(fields.FieldMDPAction.ALL)
    if signer_certs:
        from asn1crypto import x509 as ax
        try:
            subs = [ax.Certificate.load(bytes(d)) for d in signer_certs]
            for c in subs:
                c.native                                   # 깨진 인증서는 여기서 걸린다
        except Exception:
            raise SignError("bad_cert") from None
        kw["seed_value_dict"] = fields.SigSeedValueSpec(cert=fields.SigCertConstraints(
            subjects=subs, flags=fields.SigCertConstraintFlags.SUBJECT))
    try:
        fields.append_signature_field(w, fields.SigFieldSpec(sig_field_name=name, on_page=int(page_index),
                                                             box=tuple(float(v) for v in box_pdf), **kw))
        buf = io.BytesIO()
        w.write(buf)
    except SignError:
        raise
    except Exception as e:                       # noqa: BLE001
        raise SignError("sign_failed", type(e).__name__ + ": " + str(e)[:200]) from None
    with open(str(dst), "wb") as f:
        f.write(buf.getvalue())
    return name


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


def insert_images(src, dst, items, doc_password: str = "") -> None:
    """그림만 자리(SOT §3.11) — `src` 사본 `dst` 에 서명 그림을 쪽 내용으로 넣고 **증분 저장**한다.

    `items=[(쪽, (x0, y0, x1, y1) 보이는 쪽 좌표, 그림 경로), …]`. 회전한 쪽은 상자를 회전 전 좌표로 돌리고
    그림을 쪽 `/Rotate` 만큼 돌려 넣는다(실측: 0·90·180·270 모두 끈 상자 안에 바로 선다). 앞 바이트는 그대로다."""
    import shutil
    import fitz
    shutil.copyfile(str(src), str(dst))
    d = fitz.open(str(dst))
    try:
        if d.needs_pass and not d.authenticate(doc_password or ""):
            raise SignError("need_doc_password")
        for pg_i, box, img in items:
            if not (img and os.path.exists(img)) or not (0 <= int(pg_i) < d.page_count):
                continue
            page = d[int(pg_i)]
            # 261031-1(사용자 지시): 비율 그대로 상자 **왼쪽 위**에 — 남는 오른쪽·아래는 빈다(종전 keep_proportion 은 가운데)
            try:
                from PIL import Image
                with Image.open(str(img)) as _im:
                    iw, ih = _im.size
            except Exception:
                iw = ih = 0
            r = fitz.Rect(fit_left(box, iw, ih))
            rot = int(page.rotation) % 360
            if rot:
                r = r * page.derotation_matrix
                r.normalize()
            page.insert_image(r, filename=str(img), keep_proportion=True, rotate=rot)
        d.save(str(dst), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP, deflate=True)
    finally:
        d.close()


@dataclass
class SignedField:
    name: str
    fp: str                     # 서명자 인증서 SHA-256 지문
    page: int
    rect: tuple                 # 보이는 쪽 좌표(fitz)
    start: int                  # 그 서명 판이 시작하는 바이트(= 앞 판의 끝)
    end: int                    # 그 서명 판 끝(`/ByteRange` 끝)


def _revision_ends(data: bytes) -> list:
    """판 끝 바이트 위치들 — 증분 저장마다 `%%EOF`(+ 줄바꿈)로 끝난다(실측, SOT §3.10)."""
    import re
    return [m.end() for m in re.finditer(rb"%%EOF[\r\n]{0,2}", data)]


def signed_fields(path, doc_password: str = "") -> list:
    """서명된 칸들 — 서명 차례대로 (칸 이름·서명자 지문·쪽·자리·판 범위). 서명 편집(SOT §3.10)의 바탕을 정할 때 쓴다."""
    import fitz
    from pyhanko.pdf_utils.reader import PdfFileReader
    with open(path, "rb") as fh:
        data = fh.read()
    r = PdfFileReader(io.BytesIO(data), strict=False)
    if r.encrypted:
        r.decrypt(doc_password or "")
    ends = _revision_ends(data)
    out = []
    d = fitz.open("pdf", data)
    try:
        if d.needs_pass:
            d.authenticate(doc_password or "")
        places = {}
        for pi in range(d.page_count):
            page = d[pi]
            for w in page.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    rr = fitz.Rect(w.rect)
                    if int(page.rotation) % 360:
                        rr = rr * page.rotation_matrix
                        rr.normalize()
                    places[str(w.field_name)] = (pi, (rr.x0, rr.y0, rr.x1, rr.y1))
        for es in r.embedded_signatures:
            br = list(es.sig_object["/ByteRange"])
            end = int(br[2]) + int(br[3])
            prev = [e for e in ends if e < end - 8]
            start = prev[-1] if prev else 0
            try:
                fp = cert_fingerprint(es.signer_cert.dump())
            except Exception:
                fp = ""
            pg, rc = places.get(str(es.field_name), (0, (0.0, 0.0, 0.0, 0.0)))
            out.append(SignedField(str(es.field_name), fp, pg, rc, start, end))
    finally:
        d.close()
    out.sort(key=lambda f: f.end)
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
