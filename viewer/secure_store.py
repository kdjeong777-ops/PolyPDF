"""260611-57: 암호 PDF 비밀번호 보안 저장.

Windows DPAPI(CryptProtectData)로 보호 — 현재 Windows 사용자 계정에 귀속되어
다른 계정·다른 PC 로 파일을 복사해도 복호화되지 않는다(평문/단순 난독화보다 안전).
DPAPI 사용 불가 환경에서는 저장하지 않는다(평문 저장 금지).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path


def _store_path() -> Path:
    # 260618-4: 다른 앱 데이터(settings.json·dict.db 등)와 동일한 폴더로 통일 —
    #   설정 초기화/프로그램 제거 시 함께 정리되도록(구 위치는 _legacy_store_path 로 1회 이전).
    try:
        from viewer import settings_store
        d = settings_store.settings_dir()
    except Exception:
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "PolyPDF"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return d / "pdf_pw.json"


def _legacy_store_path() -> Path:
    """260618-4: 구 저장 위치(%APPDATA%\\PolyPDF\\pdf_pw.json) — 1회 이전용."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "PolyPDF" / "pdf_pw.json"


def _key(path) -> str:
    """파일 경로 + 크기로 식별 키(경로 노출 최소화 위해 해시)."""
    try:
        st = os.stat(path)
        sig = f"{os.path.abspath(str(path))}|{int(st.st_size)}"
    except Exception:
        sig = os.path.abspath(str(path))
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()


def available() -> bool:
    try:
        import win32crypt  # noqa: F401
        return True
    except Exception:
        return False


def _protect(text: str) -> str:
    import win32crypt
    blob = win32crypt.CryptProtectData(text.encode("utf-8"), "PolyPDF PDF password",
                                       None, None, None, 0)
    return base64.b64encode(blob).decode("ascii")


def _unprotect(b64: str) -> str:
    import win32crypt
    blob = base64.b64decode(b64)
    _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    return data.decode("utf-8")


# 260628: 범용 텍스트 보호 API — settings.json 의 API 키 암호화에 재사용(마스터 SOT §8.2.0).
#   PDF 암호(위 _protect/_unprotect)와 같은 DPAPI 사용자 범위이며, 설명 문자열만 다르다.
DPAPI_PREFIX = "dpapi:v1:"


def protect_text(text: str) -> str:
    """평문 → `dpapi:v1:<base64>`. DPAPI 불가·빈 값·이미 보호된 값이면 **원본 그대로**.

    (원본 반환 = 저장 자체를 막지 않음. 키를 잃는 편이 평문 저장보다 나쁘다는 판단.)"""
    if not text or not isinstance(text, str):
        return text
    if text.startswith(DPAPI_PREFIX):
        return text
    if not available():
        return text
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(text.encode("utf-8"), "PolyPDF secret",
                                           None, None, None, 0)
        return DPAPI_PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception:
        return text


def unprotect_text(value: str) -> str:
    """`dpapi:v1:<base64>` → 평문. 마커가 없으면(구버전 평문) **그대로 반환**.

    ★ 복호화 실패(다른 계정·PC 로 복사된 설정, DPAPI 불가 환경 등)면 **암호문을 그대로
    돌려준다**. 빈 문자열을 반환하면 그 빈 값이 다음 저장 때 파일에 기록되어 **키가 영구
    소실**된다(복구 불가). 암호문을 유지하면 파일의 원본이 보존되고(`protect_text` 가
    마커 붙은 값을 건드리지 않음), 해당 API 호출만 실패하므로 사용자가 다시 입력하거나
    원래 계정에서 정상 복호화할 수 있다 — '키를 잃는 편이 더 나쁘다'(SOT §8.2.0)."""
    if not value or not isinstance(value, str):
        return value
    if not value.startswith(DPAPI_PREFIX):
        return value                      # 구버전 평문 — 다음 저장 때 자동 암호화
    try:
        import win32crypt
        blob = base64.b64decode(value[len(DPAPI_PREFIX):])
        _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return data.decode("utf-8")
    except Exception:
        return value                      # 복호화 실패 — 원본 보존(소실 방지)


def _load() -> dict:
    p = _store_path()
    if not p.exists():
        # 260618-4: 구 위치에서 1회 이전(있으면 새 위치로 복사)
        lp = _legacy_store_path()
        if lp != p and lp.exists():
            try:
                data = json.loads(lp.read_text(encoding="utf-8")) or {}
                _save(data)
                return data
            except Exception:
                return {}
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    # 260618-4: 원자적 쓰기 — 임시파일에 쓰고 os.replace 로 교체.
    #   (비원자적 write_text 는 중간 크래시 시 JSON 손상 → 저장암호 전체 손실 위험)
    try:
        p = _store_path()
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def remember_password(path, pw: str) -> bool:
    """성공 시 True. DPAPI 불가하거나 빈 암호면 저장하지 않음."""
    if not pw or not available():
        return False
    try:
        data = _load()
        data[_key(path)] = _protect(pw)
        _save(data)
        return True
    except Exception:
        return False


def recall_password(path):
    """저장된 암호(복호화) 반환. 없으면 None."""
    if not available():
        return None
    try:
        enc = _load().get(_key(path))
        return _unprotect(enc) if enc else None
    except Exception:
        return None


# 260611-61: 세션(메모리) 암호 캐시 — '기억' 미체크라도 같은 실행 중에는
#   썸네일·인덱서 등 보조 렌더러가 같은 암호로 잠금 해제할 수 있게 공유.
_SESSION: dict = {}


def set_session(path, pw: str) -> None:
    if pw:
        _SESSION[_key(path)] = pw


def get_session(path):
    return _SESSION.get(_key(path))


def recall_any(path):
    """세션 캐시 우선, 없으면 DPAPI 저장값."""
    return get_session(path) or recall_password(path)


def forget_password(path) -> None:
    _SESSION.pop(_key(path), None)
    try:
        data = _load()
        if data.pop(_key(path), None) is not None:
            _save(data)
    except Exception:
        pass
