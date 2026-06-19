"""단어 이미지 — 무료 이미지(Openverse) 검색·다운로드 + 로컬 업로드 (계획서 §9.2 P10).

- 저장 폴더: settings_dir()/dict_images/  (별도 폴더 관리)
- Openverse API(키 불필요·CC 라이선스): https://api.openverse.org/v1/images/
- 다운로드는 **사용자 클릭 시에만**. 라이선스/저작자(출처)를 함께 저장.
표준 라이브러리만 사용(urllib) — 추가 의존성 없음.
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

_UA = "PolyPDF/1.0 (educational dictionary; +https://example.local)"
_OPENVERSE = "https://api.openverse.org/v1/images/"


def dict_images_dir() -> Path:
    try:
        from viewer.settings_store import settings_dir
        d = settings_dir() / "dict_images"
    except Exception:
        d = Path.home() / ".polypdf_dict_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(term: str, ext: str) -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(term or "img").strip())[:40] or "img"
    import time
    return f"{base}_{int(time.time()*1000)%100000000}{ext}"


def search_openverse(query: str, *, limit: int = 12, timeout: float = 8.0) -> list[dict]:
    """Openverse 이미지 검색 → [{title,url,thumbnail,license,creator,source,attribution}]."""
    q = urllib.parse.urlencode({"q": query, "page_size": max(1, min(20, limit))})
    req = urllib.request.Request(_OPENVERSE + "?" + q, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = []
    for it in data.get("results", []):
        lic = it.get("license", "") or ""
        lv = it.get("license_version", "") or ""
        creator = it.get("creator", "") or ""
        src = it.get("source", "") or ""
        lic_str = f"{lic.upper()} {lv}".strip()
        attr = f"Openverse · {lic_str}" + (f" · {creator}" if creator else "") \
               + (f" · {src}" if src else "")
        out.append({
            "title": it.get("title", "") or query,
            "url": it.get("url", ""),               # 원본
            "thumbnail": it.get("thumbnail", "") or it.get("url", ""),
            "license": lic_str, "creator": creator, "source": src,
            "attribution": attr,
        })
    return out


def download_bytes(url: str, *, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ext_from_url(url: str) -> str:
    m = re.search(r"\.(png|jpe?g|gif|webp|bmp)(?:\?|$)", url, re.I)
    return ("." + m.group(1).lower()) if m else ".jpg"


def save_image_for_term(term: str, url: str, attribution: str = "",
                        *, timeout: float = 15.0) -> tuple[str, str]:
    """URL 이미지를 dict_images/ 에 저장 → (파일명, 출처문자열). 실패 시 예외."""
    data = download_bytes(url, timeout=timeout)
    fn = _safe_name(term, _ext_from_url(url))
    (dict_images_dir() / fn).write_bytes(data)
    return fn, (attribution or url)


def import_local_image(term: str, src_path: str) -> str:
    """로컬 이미지 파일을 dict_images/ 로 복사 → 파일명."""
    p = Path(src_path)
    fn = _safe_name(term, p.suffix.lower() or ".png")
    shutil.copyfile(str(p), str(dict_images_dir() / fn))
    return fn


def resolve_csv_image(value: str, term: str, base_dir: Optional[Path] = None) -> tuple[str, str]:
    """CSV 의 image 값(로컬 경로 또는 http URL) → (파일명, 출처). 실패 시 ('','')."""
    v = (value or "").strip()
    if not v:
        return "", ""
    try:
        if v.lower().startswith(("http://", "https://")):
            return save_image_for_term(term, v, attribution=v)
        p = Path(v)
        if not p.is_absolute() and base_dir:
            p = Path(base_dir) / v
        if p.exists():
            return import_local_image(term, str(p)), str(v)
    except Exception:
        pass
    return "", ""


def image_path(filename: str) -> Optional[str]:
    """저장 파일명 → 절대 경로(없으면 None)."""
    if not filename:
        return None
    p = dict_images_dir() / filename
    return str(p) if p.exists() else None
