# -*- coding: utf-8 -*-
"""공동인증서(NPKI) 가져오기 (보안 SOT §3.8).

`signCert.der`(X.509) + `signPri.key`(PKCS#8 `EncryptedPrivateKeyInfo`) 를 풀어 우리 형식 `.pfx`(§3.2)로
바꾼다. 원본 인증서 폴더는 읽기만 한다. 국내 SEED 암호는 pyHanko·OpenSSL 기본 경로가 열지 못해 여기서 푼다:

  ① seedCBCWithSHA1 (1.2.410.200004.1.15) — PBKDF1-SHA1 20바이트 → 키 = 앞 16, IV = SHA-1(뒤 4) 앞 16
  ② PBES2 (PBKDF2, 기본 HMAC-SHA1) + SEED-CBC (1.2.410.200004.1.4, IV 는 매개변수)
  ③ 그 밖의 표준 PBES2(AES 등) — cryptography 가 바로 연다

SEED 는 cryptography `decrepit` 묶음(SOT §8). 화면(Qt)을 모른다 — 배경에서 부른다(SOT §10).
비밀번호는 인자로만 받고 어디에도 남기지 않는다(SOT §6.4).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import sys
from dataclasses import dataclass

OID_SEED_SHA1 = "1.2.410.200004.1.15"       # seedCBCWithSHA1
OID_SEED_CBC = "1.2.410.200004.1.4"          # seedCBC
OID_PBES2 = "1.2.840.113549.1.5.13"
OID_PBKDF2 = "1.2.840.113549.1.5.12"
_PRF = {"1.2.840.113549.2.7": "sha1", "1.2.840.113549.2.8": "sha224", "1.2.840.113549.2.9": "sha256",
        "1.2.840.113549.2.10": "sha384", "1.2.840.113549.2.11": "sha512"}
CERT_NAME, KEY_NAME = "signcert.der", "signpri.key"


@dataclass
class NpkiCert:
    folder: str
    cert_path: str
    key_path: str
    name: str
    issuer: str
    not_after: str
    usable: bool
    why: str = ""               # expired · not_yet · bad_usage · unreadable


# ---------------------------------------------------------------------------
# ASN.1 — 필요한 꼴만
# ---------------------------------------------------------------------------

def _asn():
    from asn1crypto import core

    class Alg(core.Sequence):
        _fields = [("algorithm", core.ObjectIdentifier), ("parameters", core.Any, {"optional": True})]

    class EPKI(core.Sequence):
        _fields = [("alg", Alg), ("data", core.OctetString)]

    class PBEParam(core.Sequence):
        _fields = [("salt", core.OctetString), ("iterations", core.Integer)]

    class PBKDF2Params(core.Sequence):
        _fields = [("salt", core.OctetString), ("iterations", core.Integer),
                   ("key_length", core.Integer, {"optional": True}), ("prf", Alg, {"optional": True})]

    class PBES2Params(core.Sequence):
        _fields = [("kdf", Alg), ("enc", Alg)]
    return core, Alg, EPKI, PBEParam, PBKDF2Params, PBES2Params


def _pbkdf1_sha1(pw: bytes, salt: bytes, iterations: int, n: int) -> bytes:
    d = hashlib.sha1(pw + salt).digest()
    for _ in range(max(1, int(iterations)) - 1):
        d = hashlib.sha1(d).digest()
    return d[:n]


def _seed(key: bytes, iv: bytes, data: bytes, decrypt: bool = True) -> bytes:
    import warnings
    from cryptography.hazmat.primitives.ciphers import Cipher, modes
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from cryptography.hazmat.decrepit.ciphers.algorithms import SEED
    c = Cipher(SEED(key), modes.CBC(iv))
    op = c.decryptor() if decrypt else c.encryptor()
    return op.update(data) + op.finalize()


def _unpad(b: bytes) -> bytes:
    from viewer.sign_core import WrongPassword
    if not b or len(b) % 16:
        raise WrongPassword()
    n = b[-1]
    if not 1 <= n <= 16 or b[-n:] != bytes([n]) * n:
        raise WrongPassword()                    # 채움이 맞지 않으면 = 비밀번호가 틀렸다
    return b[:-n]


def _seed_params(alg, password: str):
    """(키, IV) — ① seedCBCWithSHA1 또는 ② PBES2+SEED. SEED 가 아니면 None."""
    core, _Alg, _EPKI, PBEParam, PBKDF2Params, PBES2Params = _asn()
    oid = alg["algorithm"].dotted
    pw = (password or "").encode("utf-8")
    if oid == OID_SEED_SHA1:
        p = PBEParam.load(alg["parameters"].dump())
        dk = _pbkdf1_sha1(pw, p["salt"].native, p["iterations"].native, 20)
        return dk[:16], hashlib.sha1(dk[16:20]).digest()[:16]
    if oid == OID_PBES2:
        pp = PBES2Params.load(alg["parameters"].dump())
        if pp["enc"]["algorithm"].dotted != OID_SEED_CBC or pp["kdf"]["algorithm"].dotted != OID_PBKDF2:
            return None
        kp = PBKDF2Params.load(pp["kdf"]["parameters"].dump())
        prf = "sha1"
        if kp["prf"].native is not None:
            prf = _PRF.get(kp["prf"]["algorithm"].dotted, "")
            if not prf:
                return None
        iv = core.OctetString.load(pp["enc"]["parameters"].dump()).native
        key = hashlib.pbkdf2_hmac(prf, pw, kp["salt"].native, int(kp["iterations"].native), 16)
        return key, iv
    return None


def decrypt_key(epki_der: bytes, password: str):
    """`signPri.key` → cryptography 개인 키. 비밀번호가 틀리면 `WrongPassword`, 모르는 방식이면 SignError(unsupported_cipher)."""
    from cryptography.hazmat.primitives import serialization
    from viewer.sign_core import SignError, WrongPassword
    _core, _Alg, EPKI, *_ = _asn()
    try:
        e = EPKI.load(epki_der)
        alg = e["alg"]
        oid = alg["algorithm"].dotted
        data = e["data"].native
    except Exception:
        raise SignError("unreadable") from None
    try:
        kv = _seed_params(alg, password)
    except Exception:
        raise SignError("unreadable") from None
    if kv is None:
        # ③ 표준 PBES2(AES 등) — cryptography 가 바로 연다
        try:
            return serialization.load_der_private_key(epki_der, (password or "").encode("utf-8"))
        except (ValueError, TypeError) as ex:
            msg = str(ex).lower()
            if "unsupported" in msg or "not supported" in msg:
                raise SignError("unsupported_cipher", oid) from None
            raise WrongPassword() from None
        except Exception:
            raise SignError("unsupported_cipher", oid) from None
    plain = _unpad(_seed(kv[0], kv[1], data))
    try:
        return serialization.load_der_private_key(plain, None)
    except Exception:
        raise WrongPassword() from None          # 우연히 채움이 맞은 틀린 비밀번호


def _cert_from(path: str):
    from cryptography import x509
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return x509.load_der_x509_certificate(raw)
    except Exception:
        return x509.load_pem_x509_certificate(raw)


def _check_cert(cert) -> str:
    """못 쓰는 까닭(빈 글 = 쓸 수 있다) — SOT §3.8 확인."""
    from cryptography import x509
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (ku.digital_signature or ku.content_commitment):
            return "bad_usage"
    except x509.ExtensionNotFound:
        pass
    now = _dt.datetime.now(_dt.timezone.utc)
    if cert.not_valid_after_utc < now:
        return "expired"
    if cert.not_valid_before_utc > now:
        return "not_yet"
    return ""


def load(cert_path: str, key_path: str, password: str):
    """(개인 키, 인증서). 짝이 안 맞으면 SignError(key_mismatch), 만료 등은 SignError(그 까닭)."""
    from cryptography.hazmat.primitives import serialization
    from viewer.sign_core import SignError
    try:
        cert = _cert_from(cert_path)
    except Exception:
        raise SignError("unreadable") from None
    with open(key_path, "rb") as f:
        key = decrypt_key(f.read(), password)
    pub = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    if key.public_key().public_bytes(*pub) != cert.public_key().public_bytes(*pub):
        raise SignError("key_mismatch")
    why = _check_cert(cert)
    if why:
        raise SignError(why)
    return key, cert


def to_pfx(cert_path: str, key_path: str, password: str):
    """우리 형식 `.pfx`(PBES2-AES256, 같은 비밀번호)와 IdInfo — SOT §3.8 '보관'."""
    from viewer import sign_core
    key, cert = load(cert_path, key_path, password)
    info = sign_core._cert_info(cert)
    return sign_core._pfx_bytes(key, cert, info.name, password), info


# ---------------------------------------------------------------------------
# 찾기
# ---------------------------------------------------------------------------

def default_roots() -> list:
    """`NPKI` 폴더 후보 — 사용자 폴더 LocalLow, 준비된 드라이브의 `X:\\NPKI`(A·B·CD·네트워크 제외), 그 밖의 OS 는 ~/NPKI."""
    roots = []
    if sys.platform == "win32":
        prof = os.environ.get("USERPROFILE", "")
        if prof:
            roots.append(os.path.join(prof, "AppData", "LocalLow", "NPKI"))
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            old = k32.SetErrorMode(0x0001)           # SEM_FAILCRITICALERRORS — 빈 드라이브에 '디스크 넣기' 창이 뜨지 않게
            try:
                mask = k32.GetLogicalDrives()
                for i in range(2, 26):
                    if mask & (1 << i):
                        d = f"{chr(65 + i)}:\\"
                        if k32.GetDriveTypeW(d) in (4, 5):   # 네트워크·CD
                            continue
                        roots.append(os.path.join(d, "NPKI"))
            finally:
                k32.SetErrorMode(old)
        except Exception:
            pass
    else:
        roots.append(os.path.join(os.path.expanduser("~"), "NPKI"))
    return roots


def _pair_in(folder: str):
    try:
        names = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    if CERT_NAME in names and KEY_NAME in names:
        return os.path.join(folder, names[CERT_NAME]), os.path.join(folder, names[KEY_NAME])
    return None


def describe(folder: str):
    """폴더 하나 → NpkiCert(짝이 없으면 None)."""
    from cryptography.x509.oid import NameOID
    pair = _pair_in(folder)
    if pair is None:
        return None
    try:
        from viewer import sign_core
        cert = _cert_from(pair[0])
        info = sign_core._cert_info(cert)
        iss = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) or \
            cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        why = _check_cert(cert)
        return NpkiCert(folder, pair[0], pair[1], info.name, iss[0].value if iss else "", info.not_after,
                        usable=not why, why=why)
    except Exception:
        return NpkiCert(folder, pair[0], pair[1], os.path.basename(folder), "", "", usable=False, why="unreadable")


def find(roots=None) -> list:
    """`<NPKI>\\<기관>\\USER\\<폴더>\\signCert.der+signPri.key` 를 찾는다. 고른 폴더 자체에 짝이 있어도 받는다."""
    out, seen = [], set()
    for root in (default_roots() if roots is None else roots):
        cands = [root]
        try:
            for ca in sorted(os.listdir(root)):
                user = os.path.join(root, ca, "USER")
                if os.path.isdir(user):
                    cands.extend(os.path.join(user, s) for s in sorted(os.listdir(user)))
                cands.append(os.path.join(root, ca))
        except OSError:
            pass
        for c in cands:
            key = os.path.normcase(os.path.abspath(c))
            if key in seen:
                continue
            seen.add(key)
            got = describe(c)
            if got is not None:
                out.append(got)
    return out
