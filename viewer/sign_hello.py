# -*- coding: utf-8 -*-
"""인증서 비밀번호 1순위 — Windows Hello 로 **잠근** 보관 (보안 SOT §6.1).

자격 증명 관리자·DPAPI 에 그냥 두면 같은 계정의 다른 프로그램이 확인 없이 꺼낸다(마스터 §8.2.0 의 한계).
그래서 값 자체를 Hello 키로 잠근다:

  Windows Hello 키(`KeyCredentialManager`, TPM 안 RSA, 이름 `PolyPDF.sign`)로 고정 값(challenge)에 서명
  → 서명값에서 HKDF-SHA256 으로 AES-256-GCM 키 → 비밀번호 암호화.

키는 Hello 확인 없이는 쓸 수 없고 PC 밖으로 나가지 않는다. Hello 키 서명은 RSA PKCS#1 v1.5 라 같은
입력에 같은 서명값이 나온다(결정적) — SOT §11 실측 ⑥(Windows 에서 확인할 것). 암호문만 `signing\\hello\\<지문16>.bin` 에 둔다.

**모든 함수는 배경 스레드에서 부른다**(Hello 창이 떠 있는 동안 메인이 서면 안 된다 — SOT §10).
Windows 가 아니거나 WinRT 가 없으면 `available()` 이 False — 화면은 2순위(Google 비밀번호 관리자)로 간다(§6.2).

검사용: 환경 변수 `POLYPDF_FAKE_HELLO=1` 이면 소프트웨어 가짜 키를 쓴다(이 PC 의 Hello 를 건드리지 않는다).
`POLYPDF_FAKE_HELLO=cancel` 이면 사용자가 Hello 창을 취소한 것처럼 동작한다.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

KEY_NAME = "PolyPDF.sign"
_INFO = b"PolyPDF sign password v1"
_cached_available = None


class HelloCancelled(Exception):
    """사용자가 Hello 창을 닫았다 — 비밀번호 칸으로 넘어간다."""


class HelloError(Exception):
    """Hello 를 쓸 수 없다(정책·TPM·키 없음 등) — 2순위로 넘어간다. 메시지는 짧은 코드."""


def _fake() -> str:
    return os.environ.get("POLYPDF_FAKE_HELLO", "")


def _dir() -> Path:
    from viewer import sign_store
    d = sign_store.root() / "hello"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(fp: str) -> Path:
    return _dir() / f"{fp[:16]}.bin"


# ---- WinRT -------------------------------------------------------------------

def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _winrt():
    from winrt.windows.security.credentials import (KeyCredentialManager, KeyCredentialCreationOption,
                                                    KeyCredentialStatus)
    from winrt.windows.security.cryptography import CryptographicBuffer
    return KeyCredentialManager, KeyCredentialCreationOption, KeyCredentialStatus, CryptographicBuffer


def _raise_foreground_later():
    """데스크톱 프로그램에서 부르면 Hello 창이 PolyPDF 뒤에 뜨는 일이 있다 — 3초 동안 찾아 앞으로(최선 노력)."""
    if sys.platform != "win32":
        return
    import threading

    def _work():
        import ctypes
        import time
        u = ctypes.windll.user32
        for _ in range(30):
            h = u.FindWindowW("Credential Dialog Xaml Host", None)
            if h:
                u.SetForegroundWindow(h)
                return
            time.sleep(0.1)
    threading.Thread(target=_work, daemon=True).start()


def available() -> bool:
    """Hello 를 쓸 수 있나(설정됨·장치 있음). 결과를 기억한다. 배경 스레드에서 부른다."""
    global _cached_available
    if _fake():
        return True
    if _cached_available is not None:
        return _cached_available
    ok = False
    if sys.platform == "win32":
        try:
            KCM, *_rest = _winrt()

            async def _q():
                return await KCM.is_supported_async()
            ok = bool(_run(_q()))
        except Exception:
            ok = False
    _cached_available = ok
    return ok


def cached_available():
    """`available()` 을 이미 불렀으면 그 값, 아니면 None(화면이 기다리지 않고 판단할 때)."""
    if _fake():
        return True
    return _cached_available


def _bytes(buf, CB) -> bytes:
    try:
        return bytes(memoryview(buf))
    except Exception:
        arr = CB.copy_to_byte_array(buf)
        return bytes(arr if not isinstance(arr, tuple) else arr[0])


def _sign_challenge(challenge: bytes, create: bool) -> bytes:
    """Hello 키로 challenge 에 서명 — Hello 확인 창이 뜬다."""
    mode = _fake()
    if mode == "cancel":
        raise HelloCancelled()
    if mode:
        import hashlib
        import hmac
        return hmac.new(b"polypdf-fake-hello-key", challenge, hashlib.sha256).digest()
    if sys.platform != "win32":
        raise HelloError("unsupported")
    try:
        KCM, OPT, ST, CB = _winrt()
    except Exception:
        raise HelloError("winrt") from None

    async def _go():
        r = await KCM.open_async(KEY_NAME)
        if r.status == ST.NOT_FOUND and create:
            _raise_foreground_later()
            r = await KCM.request_create_async(KEY_NAME, OPT.FAIL_IF_EXISTS)
        if r.status == ST.USER_CANCELED:
            raise HelloCancelled()
        if r.status != ST.SUCCESS:
            raise HelloError("open:%s" % getattr(r.status, "name", r.status))
        cred = r.credential
        _raise_foreground_later()
        s = await cred.request_sign_async(CB.create_from_byte_array(challenge))
        if s.status == ST.USER_CANCELED:
            raise HelloCancelled()
        if s.status != ST.SUCCESS:
            raise HelloError("sign:%s" % getattr(s.status, "name", s.status))
        return _bytes(s.result, CB)
    try:
        return _run(_go())
    except (HelloCancelled, HelloError):
        raise
    except Exception as e:                       # noqa: BLE001
        raise HelloError(type(e).__name__) from None


def _aes_key(sig: bytes, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_INFO).derive(sig)


# ---- 보관·꺼내기 -----------------------------------------------------------------

def has(fp: str) -> bool:
    return _file(fp).exists()


def store(fp: str, password: str) -> None:
    """Hello 확인 → 비밀번호를 잠가 보관. 취소면 HelloCancelled, 못 쓰면 HelloError."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    challenge, salt, nonce = os.urandom(32), os.urandom(16), os.urandom(12)
    sig = _sign_challenge(challenge, create=True)
    # 결정성(SOT §11 ⑥)은 여기서 두 번 서명해 재지 않는다 — 서명마다 Hello 창이 다시 떠 두 번 묻게 된다.
    # 풀 때 맞지 않으면 recall 이 HelloError("decrypt") 를 내고 화면이 다시 보관하게 한다.
    ct = AESGCM(_aes_key(sig, salt)).encrypt(nonce, password.encode("utf-8"), fp.encode("ascii"))
    blob = {"v": 1, "fp": fp, "c": base64.b64encode(challenge).decode(), "s": base64.b64encode(salt).decode(),
            "n": base64.b64encode(nonce).decode(), "ct": base64.b64encode(ct).decode()}
    p = _file(fp)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob), encoding="utf-8")
    os.replace(tmp, p)


def recall(fp: str) -> str:
    """Hello 확인 → 보관한 비밀번호. 없거나 못 풀면 HelloError, 취소면 HelloCancelled."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    p = _file(fp)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise HelloError("missing") from None
    sig = _sign_challenge(base64.b64decode(blob["c"]), create=False)
    try:
        pt = AESGCM(_aes_key(sig, base64.b64decode(blob["s"]))).decrypt(
            base64.b64decode(blob["n"]), base64.b64decode(blob["ct"]), fp.encode("ascii"))
    except Exception:
        raise HelloError("decrypt") from None
    return pt.decode("utf-8")


def forget(fp: str) -> None:
    try:
        _file(fp).unlink(missing_ok=True)
    except Exception:
        pass
