r"""260618-12: 선택 구성요소(ffmpeg=녹화, Tesseract=OCR)를 설치 폴더로 내려받기.

무거운 ffmpeg(≈100MB)·Tesseract(≈90MB)는 앱 배포본에 동봉하지 않고, 필요할 때만
GitHub 릴리스의 고정 태그 `components` 에 올려둔 자산(ffmpeg.exe / tesseract.zip)을
**설치 폴더(PolyPDF.exe 옆)**로 받아 둔다(재시작 불필요).
- ffmpeg.exe        → <설치폴더>\ffmpeg.exe      (recorder.find_ffmpeg 가 탐색)
- tesseract.zip     → <설치폴더>\tesseract\      (study.ocr._candidate_dirs 가 탐색)

자산 출처: `releases/tags/components` 우선, 없으면 `releases/latest`.
공개 저장소 전제(urllib, 토큰 불필요). 모든 외부 응답은 데이터로만 취급.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
import urllib.request
from pathlib import Path

from viewer.updater import install_dir, valid_repo, DEFAULT_REPO, _UA

COMPONENTS_TAG = "components"


def repo_or_default(repo: str = "") -> str:
    repo = (repo or "").strip()
    return repo if valid_repo(repo) else DEFAULT_REPO


def _assets(repo: str, timeout: float = 8.0) -> dict:
    """{자산이름: 다운로드URL}. components 태그 우선, 없으면 latest. 실패 시 {}."""
    out: dict = {}
    for tag in (COMPONENTS_TAG, "latest"):
        api = (f"https://api.github.com/repos/{repo}/releases/latest" if tag == "latest"
               else f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        req = urllib.request.Request(
            api, headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        for a in (data.get("assets") or []):
            n = str(a.get("name") or "")
            u = a.get("browser_download_url")
            if n and u and n not in out:
                out[n] = u
        if out:
            break
    return out


def _download(url: str, progress=None, timeout: float = 60.0):
    """URL → 바이트(메모리). progress(done,total)->False 면 취소. 실패/취소 None."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    buf = io.BytesIO()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                buf.write(chunk)
                done += len(chunk)
                if progress is not None:
                    try:
                        if progress(done, total) is False:
                            return None
                    except Exception:
                        pass
        return buf.getvalue()
    except Exception:
        return None


# --- 상태 ---------------------------------------------------------------
def ffmpeg_installed() -> bool:
    try:
        from viewer.recorder import find_ffmpeg
        return bool(find_ffmpeg(""))
    except Exception:
        return False


def tesseract_installed() -> bool:
    try:
        from viewer.study import ocr
        return bool(ocr.ensure_tesseract().get("ok"))
    except Exception:
        return False


# --- 설치 ---------------------------------------------------------------
def install_ffmpeg(repo: str = "", progress=None) -> tuple[bool, str]:
    repo = repo_or_default(repo)
    url = _assets(repo).get("ffmpeg.exe")
    if not url:
        return False, "릴리스에서 ffmpeg.exe 자산을 찾지 못했습니다."
    data = _download(url, progress)
    if data is None:
        return False, "다운로드가 취소되었거나 실패했습니다."
    dest = install_dir() / "ffmpeg.exe"
    try:
        tmp = str(dest) + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)            # 원자적 교체
        return True, str(dest)
    except Exception as e:
        return False, f"저장 실패: {e}"


def install_tesseract(repo: str = "", progress=None) -> tuple[bool, str]:
    repo = repo_or_default(repo)
    url = _assets(repo).get("tesseract.zip")
    if not url:
        return False, "릴리스에서 tesseract.zip 자산을 찾지 못했습니다."
    data = _download(url, progress)
    if data is None:
        return False, "다운로드가 취소되었거나 실패했습니다."
    base = install_dir()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            # zip 루트가 'tesseract/...' 이면 설치폴더에 그대로 풀고,
            # 아니면 설치폴더\tesseract\ 아래로 푼다.
            rooted = all(n.replace("\\", "/").startswith("tesseract/") for n in names if n.strip())
            dest = base if rooted else (base / "tesseract")
            dest.mkdir(parents=True, exist_ok=True)
            z.extractall(dest)
    except Exception as e:
        return False, f"압축 해제 실패: {e}"
    try:
        from viewer.study import ocr
        ocr.reset_cache()                # 재탐색
    except Exception:
        pass
    return True, str(base / "tesseract")
