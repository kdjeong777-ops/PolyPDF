# -*- coding: utf-8 -*-
"""Windows 인증서 저장소·스마트카드로 서명 (보안 SOT §3.9).

키를 **복사하지 않는다** — 현재 사용자 '개인'(MY) 저장소의 인증서를 찾아 `CryptAcquireCertificatePrivateKey`
(CNG 키만) → `NCryptSignHash` 로 서명하고, 그것을 pyHanko `Signer` 로 감싼다. PIN·확인 창은 Windows(키 저장소
공급자)가 띄운다. ctypes 만 쓴다(새 의존성 없음). 화면(Qt)을 모른다 — 배경 스레드에서 부른다(SOT §10).

검사용 가짜 저장소: 환경 변수 `POLYPDF_FAKE_CERTSTORE` = `.pfx` 들이 든 폴더(비밀번호 `POLYPDF_FAKE_CERTSTORE_PW`,
기본 `fake-store-pw`). 파일 이름에 `cancel` 이 들어 있으면 서명 때 사용자가 PIN 창을 취소한 것처럼 군다.
실제 저장소·스마트카드는 Windows 실측(SOT §11 ⑨).
"""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass

FAKE_ENV = "POLYPDF_FAKE_CERTSTORE"
FAKE_PW_ENV = "POLYPDF_FAKE_CERTSTORE_PW"
FAKE_PW_DEFAULT = "fake-store-pw"

# Windows 상수
_X509_PKCS7 = 0x00010001                    # X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
_CERT_FIND_SHA1_HASH = 0x00010000
_CERT_KEY_PROV_INFO_PROP_ID = 2
_ACQUIRE_ONLY_NCRYPT = 0x00040000
_ACQUIRE_WINDOW_HANDLE = 0x00000080
_BCRYPT_PAD_PKCS1 = 0x00000002
_CANCEL_CODES = {0x80090036, 0x8010006E, 0x800704C7}   # NTE_USER_CANCELLED · SCARD_W_CANCELLED_BY_USER · ERROR_CANCELLED
_HASH_NAMES = {"sha256": "SHA256", "sha384": "SHA384", "sha512": "SHA512", "sha1": "SHA1"}


class StoreError(Exception):
    """저장소로 서명할 수 없다. `reason`: not_found · no_key · bad_key · failed · unavailable."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


class StoreCancelled(StoreError):
    """사용자가 Windows 의 PIN·확인 창을 취소했다."""

    def __init__(self, detail: str = ""):
        super().__init__("cancelled", detail)


@dataclass
class StoreCert:
    thumb: str                  # SHA-1 지문(16진) — 저장소에서 찾는 키
    fp: str                     # SHA-256 지문 — 우리 ID·신뢰 목록 키
    name: str
    email: str
    org: str
    issuer: str
    not_after: str
    der: bytes
    usable: bool                # 문서 서명 용도이고 유효기간 안
    why: str = ""               # 못 쓰는 까닭: bad_usage · expired · not_yet
    hardware: bool = False      # 스마트카드·토큰(공급자 이름으로 추정)


def available() -> bool:
    return bool(os.environ.get(FAKE_ENV)) or sys.platform == "win32"


def _fake_dir() -> str:
    return os.environ.get(FAKE_ENV, "")


# ---------------------------------------------------------------------------
# 공통 — 인증서 정보
# ---------------------------------------------------------------------------

def _meta(der: bytes, hardware: bool = False) -> StoreCert:
    import datetime as _dt
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from viewer import sign_core
    cert = x509.load_der_x509_certificate(der)
    info = sign_core._cert_info(cert)
    try:
        iss = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        issuer = iss[0].value if iss else cert.issuer.rfc4514_string()
    except Exception:
        issuer = ""
    why = ""
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (ku.digital_signature or ku.content_commitment):
            why = "bad_usage"
    except x509.ExtensionNotFound:
        pass
    now = _dt.datetime.now(_dt.timezone.utc)
    if not why:
        if cert.not_valid_after_utc < now:
            why = "expired"
        elif cert.not_valid_before_utc > now:
            why = "not_yet"
    return StoreCert(thumb=hashlib.sha1(der).hexdigest(), fp=info.fp, name=info.name, email=info.email,
                     org=info.org, issuer=str(issuer), not_after=info.not_after, der=der,
                     usable=not why, why=why, hardware=hardware)


def list_certs() -> list:
    """개인 키가 딸린 인증서 목록(못 쓰는 것도 `usable=False` 로 함께 — 화면에서 흐리게)."""
    if _fake_dir():
        return [_meta(der) for der, _key, _cancel in _fake_items()]
    if sys.platform != "win32":
        raise StoreError("unavailable")
    return _win_list()


def cert_der(thumb: str) -> bytes:
    for c in list_certs():
        if c.thumb == thumb:
            return c.der
    raise StoreError("not_found", thumb)


def make_signer(thumb: str, hwnd: int = 0):
    """pyHanko Signer — 서명할 때마다 저장소에서 키를 열어 `NCryptSignHash`(PIN 은 Windows 가 묻는다)."""
    thumb = (thumb or "").lower()
    if _fake_dir():
        for der, key, cancel in _fake_items():
            if hashlib.sha1(der).hexdigest() == thumb:
                return _pyhanko_signer(der, lambda h, alg, _k=key, _c=cancel: _fake_sign(_k, _c, h, alg))
        raise StoreError("not_found", thumb)
    if sys.platform != "win32":
        raise StoreError("unavailable")
    der = cert_der(thumb)
    return _pyhanko_signer(der, lambda h, alg: _win_sign(thumb, h, alg, hwnd))


def _pyhanko_signer(der: bytes, sign_digest):
    """`sign_digest(해시, 'sha256')` → RSA PKCS#1 v1.5 서명 또는 ECDSA 원시 r‖s(Windows 와 같은 꼴)."""
    from asn1crypto import algos, x509 as ax
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    acert = ax.Certificate.load(der)
    kind = acert.public_key.algorithm
    bits = int(acert.public_key.bit_size)
    if kind == "rsa":
        mech, size = "sha256_rsa", bits // 8
    elif kind == "ec":
        mech, size = "sha256_ecdsa", 2 * ((bits + 7) // 8) + 9
    else:
        raise StoreError("bad_key", kind)

    class _StoreSigner(signers.Signer):
        async def async_sign_raw(self, data: bytes, digest_algorithm: str, dry_run=False) -> bytes:
            if dry_run:
                return bytes(size)
            h = hashlib.new(digest_algorithm, data).digest()
            sig = sign_digest(h, digest_algorithm)
            if kind == "ec":
                sig = algos.DSASignature.from_p1363(sig).dump()
            return sig

    return _StoreSigner(signing_cert=acert, signature_mechanism=algos.SignedDigestAlgorithm({"algorithm": mech}),
                        cert_registry=SimpleCertificateStore.from_certs([]))


# ---------------------------------------------------------------------------
# 가짜 저장소 — 검사용
# ---------------------------------------------------------------------------

def _fake_items():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    folder = _fake_dir()
    pw = os.environ.get(FAKE_PW_ENV, FAKE_PW_DEFAULT).encode("utf-8")
    out = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith((".pfx", ".p12")):
            continue
        with open(os.path.join(folder, fn), "rb") as f:
            key, cert, _extra = pkcs12.load_key_and_certificates(f.read(), pw)
        out.append((cert.public_bytes(serialization.Encoding.DER), key, "cancel" in fn.lower()))
    return out


def _fake_sign(key, cancel: bool, digest: bytes, alg: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
    if cancel:
        raise StoreCancelled("0x80090036")
    h = {"sha256": hashes.SHA256(), "sha384": hashes.SHA384(), "sha512": hashes.SHA512()}[alg]
    if isinstance(key, rsa.RSAPrivateKey):
        return key.sign(digest, padding.PKCS1v15(), utils.Prehashed(h))
    if isinstance(key, ec.EllipticCurvePrivateKey):
        r, s = utils.decode_dss_signature(key.sign(digest, ec.ECDSA(utils.Prehashed(h))))
        n = (key.curve.key_size + 7) // 8
        return r.to_bytes(n, "big") + s.to_bytes(n, "big")       # Windows NCryptSignHash 와 같은 원시 꼴
    raise StoreError("bad_key")


# ---------------------------------------------------------------------------
# Windows — crypt32·ncrypt (ctypes)
# ---------------------------------------------------------------------------

def _api():
    import ctypes
    from ctypes import wintypes as wt

    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [("dwCertEncodingType", wt.DWORD), ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                    ("cbCertEncoded", wt.DWORD), ("pCertInfo", ctypes.c_void_p), ("hCertStore", ctypes.c_void_p)]

    class CRYPT_HASH_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    class CRYPT_KEY_PROV_INFO(ctypes.Structure):
        _fields_ = [("pwszContainerName", wt.LPWSTR), ("pwszProvName", wt.LPWSTR), ("dwProvType", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("cProvParam", wt.DWORD), ("rgProvParam", ctypes.c_void_p),
                    ("dwKeySpec", wt.DWORD)]

    class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
        _fields_ = [("pszAlgId", wt.LPCWSTR)]

    PCC = ctypes.POINTER(CERT_CONTEXT)
    c32 = ctypes.WinDLL("crypt32", use_last_error=True)
    nc = ctypes.WinDLL("ncrypt")
    c32.CertOpenSystemStoreW.restype = ctypes.c_void_p
    c32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    c32.CertCloseStore.argtypes = [ctypes.c_void_p, wt.DWORD]
    c32.CertEnumCertificatesInStore.restype = PCC
    c32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, PCC]
    c32.CertFindCertificateInStore.restype = PCC
    c32.CertFindCertificateInStore.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p, PCC]
    c32.CertFreeCertificateContext.argtypes = [PCC]
    c32.CertGetCertificateContextProperty.restype = wt.BOOL
    c32.CertGetCertificateContextProperty.argtypes = [PCC, wt.DWORD, ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
    c32.CryptAcquireCertificatePrivateKey.restype = wt.BOOL
    c32.CryptAcquireCertificatePrivateKey.argtypes = [PCC, wt.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                                      ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.BOOL)]
    nc.NCryptSignHash.restype = ctypes.c_long
    nc.NCryptSignHash.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), wt.DWORD,
                                  ctypes.POINTER(ctypes.c_ubyte), wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
    nc.NCryptFreeObject.argtypes = [ctypes.c_size_t]
    nc.NCryptGetProperty.restype = ctypes.c_long
    nc.NCryptGetProperty.argtypes = [ctypes.c_size_t, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD,
                                     ctypes.POINTER(wt.DWORD), wt.DWORD]
    return ctypes, wt, c32, nc, CERT_CONTEXT, CRYPT_HASH_BLOB, CRYPT_KEY_PROV_INFO, BCRYPT_PKCS1_PADDING_INFO


def _ctx_der(ctypes, ctx) -> bytes:
    c = ctx.contents
    return bytes(ctypes.string_at(c.pbCertEncoded, c.cbCertEncoded))


def _prov_name(ctypes, wt, c32, PROV, ctx):
    """개인 키가 있으면 공급자 이름(없으면 None)."""
    cb = wt.DWORD(0)
    if not c32.CertGetCertificateContextProperty(ctx, _CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(cb)):
        return None
    buf = ctypes.create_string_buffer(cb.value)
    if not c32.CertGetCertificateContextProperty(ctx, _CERT_KEY_PROV_INFO_PROP_ID, buf, ctypes.byref(cb)):
        return None
    info = ctypes.cast(buf, ctypes.POINTER(PROV)).contents
    return info.pwszProvName or ""


def _win_list() -> list:
    ctypes, wt, c32, _nc, _CC, _HB, PROV, _PAD = _api()
    store = c32.CertOpenSystemStoreW(None, "MY")
    if not store:
        raise StoreError("failed", f"CertOpenSystemStore 0x{ctypes.get_last_error() & 0xFFFFFFFF:08X}")
    out, seen = [], set()
    try:
        ctx = c32.CertEnumCertificatesInStore(store, None)
        while ctx:
            prov = _prov_name(ctypes, wt, c32, PROV, ctx)
            if prov is not None:
                der = _ctx_der(ctypes, ctx)
                try:
                    m = _meta(der, hardware="smart card" in prov.lower() or "smartcard" in prov.lower())
                    if m.thumb not in seen:
                        seen.add(m.thumb)
                        out.append(m)
                except Exception:
                    pass                         # 읽지 못하는 인증서는 건너뛴다
            ctx = c32.CertEnumCertificatesInStore(store, ctx)   # 앞 문맥은 이 호출이 풀어 준다
    finally:
        c32.CertCloseStore(store, 0)
    return out


def _win_sign(thumb: str, digest: bytes, alg: str, hwnd: int) -> bytes:
    ctypes, wt, c32, nc, _CC, HB, _PROV, PAD = _api()
    store = c32.CertOpenSystemStoreW(None, "MY")
    if not store:
        raise StoreError("failed", f"CertOpenSystemStore 0x{ctypes.get_last_error() & 0xFFFFFFFF:08X}")
    ctx = None
    hkey = ctypes.c_size_t(0)
    must_free = wt.BOOL(False)
    try:
        raw = bytes.fromhex(thumb)
        hb = HB(len(raw), (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw))
        ctx = c32.CertFindCertificateInStore(store, _X509_PKCS7, 0, _CERT_FIND_SHA1_HASH, ctypes.byref(hb), None)
        if not ctx:
            raise StoreError("not_found", thumb)
        spec = wt.DWORD(0)
        flags = _ACQUIRE_ONLY_NCRYPT
        hw = ctypes.c_void_p(int(hwnd or 0))
        if hwnd:
            flags |= _ACQUIRE_WINDOW_HANDLE                       # PIN 창이 PolyPDF 창의 자식으로(앞에) 뜬다
        if not c32.CryptAcquireCertificatePrivateKey(ctx, flags, ctypes.byref(hw) if hwnd else None,
                                                     ctypes.byref(hkey), ctypes.byref(spec), ctypes.byref(must_free)):
            code = ctypes.get_last_error() & 0xFFFFFFFF
            if code in _CANCEL_CODES:
                raise StoreCancelled(f"0x{code:08X}")
            raise StoreError("no_key", f"0x{code:08X}")
        der = _ctx_der(ctypes, ctx)
        from asn1crypto import x509 as ax
        kind = ax.Certificate.load(der).public_key.algorithm
        pad, pflags = None, 0
        if kind == "rsa":
            pad_s = PAD(_HASH_NAMES.get(alg, "SHA256"))
            pad, pflags = ctypes.byref(pad_s), _BCRYPT_PAD_PKCS1
        hbuf = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
        need = wt.DWORD(0)
        st = nc.NCryptSignHash(hkey.value, pad, hbuf, len(digest), None, 0, ctypes.byref(need), pflags)
        if st != 0:
            code = st & 0xFFFFFFFF
            if code in _CANCEL_CODES:
                raise StoreCancelled(f"0x{code:08X}")
            raise StoreError("failed", f"NCryptSignHash 0x{code:08X}")
        out = (ctypes.c_ubyte * need.value)()
        got = wt.DWORD(0)
        st = nc.NCryptSignHash(hkey.value, pad, hbuf, len(digest), out, need.value, ctypes.byref(got), pflags)
        if st != 0:
            code = st & 0xFFFFFFFF
            if code in _CANCEL_CODES:
                raise StoreCancelled(f"0x{code:08X}")
            raise StoreError("failed", f"NCryptSignHash 0x{code:08X}")
        return bytes(out[: got.value])
    finally:
        if hkey.value and must_free.value:
            nc.NCryptFreeObject(hkey.value)
        if ctx:
            c32.CertFreeCertificateContext(ctx)
        c32.CertCloseStore(store, 0)
