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
# 260618-11: 기본 업데이트 저장소(설정 update_repo 가 비어 있으면 이 값 사용 — 입력 불필요).
DEFAULT_REPO = "kdjeong777-ops/PolyPDF"
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


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _to_info(rel):
    """릴리스 dict → 표준 info. 자산 zip 은 'win' 포함분 우선, 없으면 첫 zip."""
    if not isinstance(rel, dict):
        return None
    tag = str(rel.get("tag_name") or "")
    zips = [a for a in (rel.get("assets") or [])
            if str(a.get("name") or "").lower().endswith(".zip")]

    # 260618-14: 자동 업데이트는 경량 'update' zip 우선(없으면 win64 full, 그다음 첫 zip).
    #   update zip 은 안 바뀌는 무거운 부분(ffmpeg·tesseract·모델)을 제외 → 기존 설치분 보존.
    def _score(a):
        n = str(a.get("name") or "").lower()
        return (1 if "update" in n else 0, 1 if "win" in n else 0)
    pick = max(zips, key=_score) if zips else None
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "notes": str(rel.get("body") or ""),
        "asset_url": pick.get("browser_download_url") if pick else None,
        "asset_name": str(pick.get("name") or "") if pick else None,
        "html_url": str(rel.get("html_url") or ""),
    }


def check_latest(repo: str, timeout: float = 8.0):
    """최신 '버전' 릴리스 정보 dict 또는 None.

    260618-13: `/releases` 목록에서 **유효 SemVer 태그 중 최고 버전**을 고른다
    (`components` 등 비버전 태그·draft 는 제외). 과거 `/releases/latest` 만 쓰면 `components`
    릴리스를 나중에 올렸을 때 그게 'latest' 로 반환돼(버전=0.0.0) 업데이트를 못 찾던 문제가
    있었다. 목록 조회 실패 시 `/releases/latest` 로 폴백."""
    if not valid_repo(repo):
        return None
    repo = repo.strip()
    data = _get_json(f"https://api.github.com/repos/{repo}/releases", timeout)
    best = None
    best_v = (-1, -1, -1)
    if isinstance(data, list):
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            v = _vtuple(str(rel.get("tag_name") or ""))
            if v == (0, 0, 0):              # 비버전 태그(components 등) 제외
                continue
            if v > best_v:
                best_v = v
                best = rel
    if best is None:                        # 폴백: /releases/latest
        best = _get_json(_API_LATEST.format(repo=repo), timeout)
    return _to_info(best)


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
