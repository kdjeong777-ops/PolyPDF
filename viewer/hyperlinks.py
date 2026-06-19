"""260609-3 (C): 페이지별 외부 하이퍼링크 — 사이드카 JSON 저장 + 보안 검증.

설계 결정(사용자):
- 저장: PDF 폴더 루트의 `hyperlinks.json` (원본 PDF 미수정, 이식·백업 용이).
- 파일 링크: 책갈피 폴더(루트) **내부**의 작업파일만(화이트리스트 확장자),
  실행/스크립트 파일은 이중 차단. 상대경로로 저장(폴더 이동에 강건).
- URL 링크: `https://` 만 + 도메인 허용목록(youtube 등) suffix 매칭.

이 모듈은 순수 로직(검증·직렬화)만 담당 — UI/실행은 호출측에서.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# 작업 파일 화이트리스트(문서·미디어). 소문자 확장자(점 제외).
ALLOWED_EXT = {
    # 문서
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "hwp", "hwpx", "txt", "csv", "rtf", "odt", "odp", "ods",
    # 이미지
    "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "svg",
    # 동영상/오디오
    "mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg",
    "mp3", "wav", "m4a", "flac", "ogg", "aac",
}

# 실행/스크립트 — 화이트리스트와 무관하게 항상 차단(이중 방어).
BLOCKED_EXT = {
    "exe", "bat", "cmd", "com", "ps1", "psm1", "vbs", "vbe", "js", "jse",
    "jar", "msi", "scr", "lnk", "reg", "sh", "bash", "py", "pyw", "pyc",
    "dll", "cpl", "hta", "wsf", "wsh", "gadget", "msc", "inf", "url",
}

# URL 도메인 허용목록(기본). 사용자가 설정에서 확장 가능.
DEFAULT_URL_ALLOWLIST = [
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "vimeo.com",
]

SIDECAR_NAME = "hyperlinks.json"
SCHEMA_VERSION = 1


# ===== 검증기 =============================================================
def _ext_of(p) -> str:
    return Path(str(p)).suffix.lower().lstrip(".")


def validate_file_target(base_folder, target_path):
    """파일 링크 대상 검증.

    반환: (ok: bool, rel_or_err: str). ok 면 base_folder 기준 정규화 상대경로,
    실패면 사용자용 오류 메시지.
    """
    try:
        base = Path(base_folder).resolve(strict=False)
    except Exception:
        return False, "기준 폴더가 유효하지 않습니다."
    if not base.exists() or not base.is_dir():
        return False, "기준 폴더가 없습니다. 폴더를 먼저 여세요."
    try:
        tgt = Path(target_path).resolve(strict=False)
    except Exception:
        return False, "파일 경로가 유효하지 않습니다."
    if not tgt.exists() or not tgt.is_file():
        return False, "파일이 존재하지 않습니다."

    ext = _ext_of(tgt)
    if ext in BLOCKED_EXT:
        return False, f"보안상 등록할 수 없는 형식입니다(.{ext})."
    if ext not in ALLOWED_EXT:
        return False, (f"허용되지 않은 형식입니다(.{ext}). "
                       "문서·이미지·동영상 등 작업 파일만 등록할 수 있습니다.")

    # 경로 봉쇄: 대상이 base 내부여야 함(심볼릭/.. 우회 방지)
    try:
        common = os.path.commonpath([str(base), str(tgt)])
    except ValueError:
        return False, "다른 드라이브의 파일은 등록할 수 없습니다."
    if os.path.normcase(common) != os.path.normcase(str(base)):
        return False, "책갈피 폴더 안의 파일만 등록할 수 있습니다."

    rel = os.path.relpath(str(tgt), str(base)).replace("\\", "/")
    return True, rel


def validate_url(url, allowlist=None):
    """URL 링크 검증. 반환: (ok, normalized_url_or_err)."""
    allow = [d.lower().lstrip(".") for d in (allowlist or DEFAULT_URL_ALLOWLIST)]
    u = (url or "").strip()
    if not u:
        return False, "주소가 비어 있습니다."
    try:
        pr = urlparse(u)
    except Exception:
        return False, "주소 형식이 올바르지 않습니다."
    if pr.scheme.lower() != "https":
        return False, "보안을 위해 https:// 주소만 등록할 수 있습니다."
    host = (pr.hostname or "").lower()
    if not host:
        return False, "주소에 도메인이 없습니다."
    ok = any(host == d or host.endswith("." + d) for d in allow)
    if not ok:
        return False, ("허용 목록에 없는 도메인입니다. "
                       "유튜브 등 허용된 주소만 등록할 수 있습니다.")
    return True, u


def is_safe_to_open_file(base_folder, rel_path):
    """실행 직전 재검증(심층 방어). rel_path(상대) → 절대경로 또는 None."""
    try:
        base = Path(base_folder).resolve(strict=False)
        tgt = (base / rel_path).resolve(strict=False)
    except Exception:
        return None
    if not tgt.exists() or not tgt.is_file():
        return None
    ext = _ext_of(tgt)
    if ext in BLOCKED_EXT or ext not in ALLOWED_EXT:
        return None
    try:
        common = os.path.commonpath([str(base), str(tgt)])
    except ValueError:
        return None
    if os.path.normcase(common) != os.path.normcase(str(base)):
        return None
    return str(tgt)


# ===== 저장소 ============================================================
class HyperlinkStore:
    """폴더 단위 사이드카(hyperlinks.json) 로드/저장.

    키: 파일은 base_folder 기준 상대경로(/ 구분), 페이지는 0-based 문자열.
    값: [{"name","kind"("file"|"url"),"target"}].
    """

    def __init__(self, base_folder, url_allowlist=None):
        self.base = Path(base_folder) if base_folder else None
        self.url_allowlist = url_allowlist or list(DEFAULT_URL_ALLOWLIST)
        self._data = {"version": SCHEMA_VERSION, "links": {}}
        self._load()

    # --- 경로/키 ---
    def _sidecar_path(self) -> Optional[Path]:
        if not self.base:
            return None
        return Path(self.base) / SIDECAR_NAME

    def _rel_key(self, file_path) -> Optional[str]:
        if not self.base:
            return None
        try:
            base = Path(self.base).resolve(strict=False)
            f = Path(file_path).resolve(strict=False)
            common = os.path.commonpath([str(base), str(f)])
            if os.path.normcase(common) != os.path.normcase(str(base)):
                return None
            return os.path.relpath(str(f), str(base)).replace("\\", "/")
        except Exception:
            return None

    # --- IO ---
    def _load(self):
        p = self._sidecar_path()
        if p and p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("links"), dict):
                    self._data = {"version": int(d.get("version", SCHEMA_VERSION)),
                                  "links": d["links"]}
            except Exception:
                pass  # 손상 시 빈 상태로 시작(앱 계속)

    def save(self) -> bool:
        p = self._sidecar_path()
        if not p:
            return False
        try:
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(str(tmp), str(p))
            return True
        except Exception:
            return False

    # --- 조회/수정 ---
    def links_for(self, file_path, page0) -> list:
        key = self._rel_key(file_path)
        if key is None:
            return []
        return list(self._data["links"].get(key, {}).get(str(int(page0)), []))

    def _bucket(self, key, page0, create=False):
        links = self._data["links"]
        if key not in links:
            if not create:
                return None
            links[key] = {}
        pg = str(int(page0))
        if pg not in links[key]:
            if not create:
                return None
            links[key][pg] = []
        return links[key][pg]

    def add_file_link(self, file_path, page0, name, target_path):
        key = self._rel_key(file_path)
        if key is None:
            return False, "현재 파일이 책갈피 폴더 안에 있지 않습니다."
        ok, rel_or_err = validate_file_target(self.base, target_path)
        if not ok:
            return False, rel_or_err
        # 260609-15(C1): 명칭 미입력 시 파일명에서 확장자(.pdf 등) 제거
        nm = (name or "").strip() or Path(rel_or_err).stem
        self._bucket(key, page0, create=True).append(
            {"name": nm, "kind": "file", "target": rel_or_err})
        return True, "등록되었습니다."

    def add_url_link(self, file_path, page0, name, url):
        key = self._rel_key(file_path)
        if key is None:
            return False, "현재 파일이 책갈피 폴더 안에 있지 않습니다."
        ok, url_or_err = validate_url(url, self.url_allowlist)
        if not ok:
            return False, url_or_err
        nm = (name or "").strip() or url_or_err
        self._bucket(key, page0, create=True).append(
            {"name": nm, "kind": "url", "target": url_or_err})
        return True, "등록되었습니다."

    def rename_link(self, file_path, page0, index, new_name) -> bool:
        """260609-11: 등록 링크의 명칭 변경."""
        key = self._rel_key(file_path)
        if key is None:
            return False
        bucket = self._bucket(key, page0, create=False)
        if bucket is None or not (0 <= index < len(bucket)):
            return False
        nm = (new_name or "").strip()
        if not nm:
            return False
        bucket[index]["name"] = nm
        return True

    def move_link(self, file_path, page0, index, delta) -> int:
        """260609-11: 링크 순서 이동(delta=-1 위/+1 아래). 새 인덱스 반환(실패 -1)."""
        key = self._rel_key(file_path)
        if key is None:
            return -1
        bucket = self._bucket(key, page0, create=False)
        if bucket is None:
            return -1
        j = index + (1 if delta > 0 else -1)
        if not (0 <= index < len(bucket)) or not (0 <= j < len(bucket)):
            return -1
        bucket[index], bucket[j] = bucket[j], bucket[index]
        return j

    def remove_link(self, file_path, page0, index) -> bool:
        key = self._rel_key(file_path)
        if key is None:
            return False
        bucket = self._bucket(key, page0, create=False)
        if bucket is None or not (0 <= index < len(bucket)):
            return False
        bucket.pop(index)
        if not bucket:                       # 빈 버킷 정리
            del self._data["links"][key][str(int(page0))]
            if not self._data["links"][key]:
                del self._data["links"][key]
        return True

    def pages_with_links(self, file_path) -> set:
        key = self._rel_key(file_path)
        if key is None:
            return set()
        return {int(p) for p in self._data["links"].get(key, {}).keys()}
