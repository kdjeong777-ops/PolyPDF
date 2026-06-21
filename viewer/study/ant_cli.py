"""Anthropic CLI(`ant`) 관리 — 앱 내 'Claude 로그인(구독 OAuth)'용.

SOT: `PDF 번역·요약 작업 계획서.md` §4.1b.
- 콘솔 API 키 없이 Claude 구독 계정으로 쓰기 위해, 공식 Anthropic CLI(`ant`)를 이용한다.
  ① 없으면 GitHub 릴리스에서 자동 설치(앱 전용 bin), ② `ant auth login`(브라우저)으로 로그인,
  ③ `ant auth print-credentials --access-token`(만료 시 자동 갱신)로 토큰을 받아 SDK 에 전달.
- 터미널 타이핑 불필요(앱 버튼이 ant 를 대신 실행).
표준 라이브러리만 사용(urllib/zipfile/subprocess).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

_GH_LATEST = "https://api.github.com/repos/anthropics/anthropic-cli/releases/latest"
_UA = "PolyPDF-ant-installer"
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def managed_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "PolyPDF" / "bin"
    return d


def _exe_name() -> str:
    return "ant.exe" if os.name == "nt" else "ant"


def managed_ant() -> Path:
    return managed_dir() / _exe_name()


def ant_path() -> str:
    """사용 가능한 ant 경로(앱 전용 bin 우선, 없으면 PATH). 없으면 ''."""
    m = managed_ant()
    if m.exists():
        return str(m)
    # PATH 탐색
    from shutil import which
    p = which("ant")
    return p or ""


def is_installed() -> bool:
    return bool(ant_path())


def _run(args, timeout=60):
    """ant 서브프로세스 실행 → (rc, stdout, stderr). 콘솔창 숨김."""
    exe = ant_path()
    if not exe:
        return 127, "", "ant not installed"
    try:
        p = subprocess.run(
            [exe] + list(args),
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
            timeout=timeout, creationflags=_CREATE_NO_WINDOW)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "시간 초과"
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


# ── 설치 ────────────────────────────────────────────────────────────────
def _asset_suffix() -> str:
    sysname = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    m = (platform.machine() or "").lower()
    arch = "arm64" if ("arm64" in m or "aarch64" in m) else "amd64"
    ext = "zip" if sysname in ("windows", "macos") else "tar.gz"
    return f"{sysname}_{arch}.{ext}"


def ensure_installed(progress=None) -> str:
    """ant 가 없으면 GitHub 최신 릴리스에서 받아 앱 bin 에 설치. ant 경로 반환(실패 시 예외)."""
    cur = ant_path()
    if cur:
        return cur

    def say(m):
        if progress:
            try:
                progress(m)
            except Exception:
                pass

    say("Anthropic CLI 최신 버전 확인 중…")
    req = urllib.request.Request(_GH_LATEST, headers={
        "User-Agent": _UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.loads(r.read().decode("utf-8"))
    suffix = _asset_suffix()
    url = ""
    for a in rel.get("assets") or []:
        if str(a.get("name") or "").endswith(suffix):
            url = a.get("browser_download_url") or ""
            break
    if not url:
        raise RuntimeError(f"이 환경({suffix})용 ant 설치 파일을 찾지 못했습니다.")

    d = managed_dir()
    d.mkdir(parents=True, exist_ok=True)
    zpath = d / "ant_download.zip"
    say("Anthropic CLI 다운로드 중…")
    req2 = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req2, timeout=120) as r, open(zpath, "wb") as f:
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
    say("설치(압축 해제) 중…")
    exe_name = _exe_name()
    try:
        with zipfile.ZipFile(zpath) as z:
            member = next((n for n in z.namelist()
                           if n.split("/")[-1].lower() == exe_name), None)
            if not member:
                raise RuntimeError("다운로드 파일에 ant 실행파일이 없습니다.")
            data = z.read(member)
        with open(managed_ant(), "wb") as f:
            f.write(data)
        if os.name != "nt":
            os.chmod(managed_ant(), 0o755)
    finally:
        try:
            zpath.unlink()
        except Exception:
            pass
    p = ant_path()
    if not p:
        raise RuntimeError("ant 설치 후에도 실행파일을 찾지 못했습니다.")
    return p


# ── 인증 ────────────────────────────────────────────────────────────────
def access_token() -> str:
    """활성 프로필의 액세스 토큰(만료 시 자동 갱신). 미로그인/실패 시 ''."""
    if not is_installed():
        return ""
    rc, out, _ = _run(["auth", "print-credentials", "--access-token"], timeout=60)
    return out.strip() if rc == 0 else ""


def is_logged_in() -> bool:
    return bool(access_token())


def login(timeout: int = 240):
    """`ant auth login`(브라우저 OAuth). (성공여부, 메시지)."""
    if not is_installed():
        return False, "ant 가 설치되어 있지 않습니다."
    rc, out, err = _run(["auth", "login"], timeout=timeout)
    if rc == 0 and is_logged_in():
        return True, "로그인 완료"
    msg = (err or out or "로그인 실패").splitlines()[-1] if (err or out) else "로그인 실패"
    if rc == 124:
        msg = "시간 초과 — 브라우저에서 로그인을 완료하지 못했습니다."
    return False, msg


def logout():
    rc, out, err = _run(["auth", "logout"], timeout=30)
    return rc == 0, (err or out or "")
