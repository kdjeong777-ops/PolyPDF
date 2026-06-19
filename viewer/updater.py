"""260618-11: GitHub Releases 기반 앱 내 업데이트(확인·다운로드·자동 교체).

- check_latest(repo): 공개 저장소의 최신 릴리스(태그·자산·노트) 조회 (urllib, 토큰 불필요).
- is_newer: SemVer(major.minor.patch) 비교.
- download_asset: 진행 콜백과 함께 릴리스 zip 다운로드.
- apply_update: 실행 중인 exe 는 자기 자신을 덮어쓸 수 없으므로, 도우미 .bat 가
  '앱 종료 대기 → 압축 해제 → 설치폴더 덮어쓰기 → 재실행' 한다. 호출 후 앱을 종료해야 함.

배포(frozen) exe 에서만 실제 교체가 의미 있음(소스 실행 시엔 확인만).
릴리스 자산: 이름에 'win' 이 든 .zip 우선(없으면 첫 .zip). CI 는 PolyPDF-<tag>-win64.zip 생성.
zip 루트에 PolyPDF.exe·_internal/ … 또는 PolyPDF/ 하위 — 둘 다 처리.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import subprocess
import urllib.request
from pathlib import Path

ASSET_NAME = "PolyPDF-windows.zip"
_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_UA = "PolyPDF-Updater"
CREATE_NO_WINDOW = 0x08000000


def current_version() -> str:
    try:
        from viewer import __version__
        return __version__
    except Exception:
        return "0.0.0"


def _vtuple(s: str) -> tuple:
    """'v2.23.0' / '2.23.0-rc1' → (2,23,0). 숫자 외 토큰에서 중단."""
    s = (s or "").strip().lstrip("vV")
    out: list = []
    for p in re.split(r"[.\-+_]", s):
        if p.isdigit():
            out.append(int(p))
        else:
            break
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def is_newer(latest: str, current: str) -> bool:
    return _vtuple(latest) > _vtuple(current)


def valid_repo(repo: str) -> bool:
    repo = (repo or "").strip()
    return bool(repo) and "/" in repo and not repo.upper().startswith("OWNER")


def check_latest(repo: str, timeout: float = 8.0):
    """최신 릴리스 정보 dict 또는 None(네트워크/없음). 외부 입력은 데이터로만 취급."""
    if not valid_repo(repo):
        return None
    req = urllib.request.Request(
        _API_LATEST.format(repo=repo.strip()),
        headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name") or "")
    asset_url = None
    asset_name = None
    # 자산 zip 선택: 'win'/'windows' 포함 zip 우선, 없으면 첫 zip.
    #   (CI 는 PolyPDF-<tag>-win64.zip, 수동 스크립트도 -win64.zip 로 통일)
    zips = [a for a in (data.get("assets") or [])
            if str(a.get("name") or "").lower().endswith(".zip")]
    pick = None
    for a in zips:
        if "win" in str(a.get("name") or "").lower():
            pick = a
            break
    if pick is None and zips:
        pick = zips[0]
    if pick is not None:
        asset_url = pick.get("browser_download_url")
        asset_name = str(pick.get("name") or "")
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "notes": str(data.get("body") or ""),
        "asset_url": asset_url,
        "asset_name": asset_name,
        "html_url": str(data.get("html_url") or ""),
    }


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent      # 개발 실행: 패키지 상위


def download_asset(url: str, progress=None, timeout: float = 30.0):
    """릴리스 zip 다운로드. progress(done,total)->False 면 취소. 성공 시 파일경로, 실패 None."""
    if not url:
        return None
    dest_dir = tempfile.mkdtemp(prefix="polypdf_upd_")
    dest = os.path.join(dest_dir, ASSET_NAME)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    try:
                        if progress(done, total) is False:
                            return None
                    except Exception:
                        pass
        return dest
    except Exception:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except Exception:
            pass
        return None


def apply_update(zip_path: str) -> bool:
    """실행 중 교체 도우미 실행(앱 종료 대기→해제→덮어쓰기→재실행). 성공 시 True 반환 후
    호출측이 앱을 종료해야 한다. frozen(배포 exe)에서만 의미 있음."""
    if not (zip_path and os.path.isfile(zip_path)):
        return False
    inst = str(install_dir())
    exe = sys.executable if is_frozen() else os.path.join(inst, "PolyPDF.exe")
    pid = os.getpid()
    extract = os.path.join(tempfile.mkdtemp(prefix="polypdf_ext_"), "new")
    bat = os.path.join(tempfile.gettempdir(), f"polypdf_update_{pid}.bat")
    # %%~f0 → 배치 자기 경로(자기 삭제). 압축 루트에 PolyPDF\ 하위가 있으면 그 안을 원본으로.
    script = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "echo PolyPDF 업데이트 적용 중입니다. 잠시만 기다려 주세요...\r\n"
        ":waitloop\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        "if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )\r\n"
        f'powershell -NoProfile -Command "Expand-Archive -LiteralPath \'{zip_path}\' '
        f"-DestinationPath '{extract}' -Force\"\r\n"
        f'powershell -NoProfile -Command "$s=\'{extract}\'; '
        "if (Test-Path (Join-Path $s 'PolyPDF\\PolyPDF.exe')) { $s=Join-Path $s 'PolyPDF' }; "
        f"Copy-Item -Path (Join-Path $s '*') -Destination '{inst}' -Recurse -Force\"\r\n"
        f'start "" "{exe}"\r\n'
        'del "%~f0"\r\n'
    )
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write(script)
        # 진행 콘솔을 보이게 띄움(교체 중임을 사용자가 인지)
        subprocess.Popen(["cmd", "/c", bat], close_fds=True)
        return True
    except Exception:
        return False
