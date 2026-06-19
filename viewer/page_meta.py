"""260609-14 (D4·D5): 페이지별 메타(크롭·숨김) — 폴더 사이드카 JSON, lazy 로드.

시작 속도 영향 최소화: 폴더 열 때 한 번 읽고, 변경 시에만 저장.
크롭은 페이지 높이 대비 백분율(상/하), 0~45%. 페이지별 값이 전역보다 우선.
숨김은 0-based 페이지 집합. 키=base_folder 기준 상대경로(/).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

SIDECAR_NAME = "page_meta.json"
SCHEMA_VERSION = 1
CROP_MAX = 45.0


def _clamp_crop(v) -> float:
    try:
        v = float(v)
    except Exception:
        return 0.0
    return max(0.0, min(CROP_MAX, v))


class PageMetaStore:
    def __init__(self, base_folder):
        self.base = Path(base_folder) if base_folder else None
        self._data = {"version": SCHEMA_VERSION, "files": {}}
        self._load()

    # --- 경로/키 ---
    def _sidecar(self) -> Optional[Path]:
        return (Path(self.base) / SIDECAR_NAME) if self.base else None

    def _key(self, file_path) -> Optional[str]:
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

    def _file(self, key, create=False):
        files = self._data["files"]
        if key not in files:
            if not create:
                return None
            files[key] = {"crop_global": [0.0, 0.0], "crop_pages": {},
                          "hidden": [], "rotation": {}, "drawings": {}}
        files[key].setdefault("rotation", {})       # 260609-15(A1): 구버전 보강
        files[key].setdefault("drawings", {})       # 260609-22(J3): 선긋기
        files[key].setdefault("images", {})         # 260611-15: 삽입 이미지(주석)
        return files[key]

    # --- IO ---
    def _load(self):
        p = self._sidecar()
        if p and p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("files"), dict):
                    self._data = {"version": int(d.get("version", SCHEMA_VERSION)),
                                  "files": d["files"]}
            except Exception:
                pass

    def save(self) -> bool:
        p = self._sidecar()
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

    # --- 크롭(D4) ---
    def get_crop(self, file_path, page0):
        """(top%, bottom%) — 페이지별 값 우선, 없으면 전역."""
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr:
            return (0.0, 0.0)
        pg = str(int(page0))
        if pg in fr.get("crop_pages", {}):
            t, b = fr["crop_pages"][pg]
            return (_clamp_crop(t), _clamp_crop(b))
        g = fr.get("crop_global", [0.0, 0.0])
        return (_clamp_crop(g[0]), _clamp_crop(g[1]))

    def get_global_crop(self, file_path):
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        g = (fr or {}).get("crop_global", [0.0, 0.0])
        return (_clamp_crop(g[0]), _clamp_crop(g[1]))

    def has_page_crop(self, file_path, page0) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return bool(fr and str(int(page0)) in fr.get("crop_pages", {}))

    def set_global_crop(self, file_path, top, bottom) -> bool:
        key = self._key(file_path)
        if key is None:
            return False
        self._file(key, create=True)["crop_global"] = [_clamp_crop(top), _clamp_crop(bottom)]
        return True

    def set_page_crop(self, file_path, page0, top, bottom) -> bool:
        key = self._key(file_path)
        if key is None:
            return False
        self._file(key, create=True)["crop_pages"][str(int(page0))] = \
            [_clamp_crop(top), _clamp_crop(bottom)]
        return True

    def clear_page_crop(self, file_path, page0) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if fr and str(int(page0)) in fr.get("crop_pages", {}):
            del fr["crop_pages"][str(int(page0))]
            return True
        return False

    def reset_crop(self, file_path) -> bool:
        """전역+페이지별 크롭 초기화."""
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if fr:
            fr["crop_global"] = [0.0, 0.0]
            fr["crop_pages"] = {}
            return True
        return False

    # --- 회전(A1) ---
    def get_rotation(self, file_path, page0) -> int:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr:
            return 0
        return int(fr.get("rotation", {}).get(str(int(page0)), 0)) % 360

    def rotations(self, file_path) -> dict:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return {int(k): int(v) % 360 for k, v in (fr or {}).get("rotation", {}).items()
                if int(v) % 360 != 0}

    def rotate_pages(self, file_path, pages, delta) -> bool:
        """delta=±90. 누적 후 0 이면 항목 제거."""
        key = self._key(file_path)
        if key is None:
            return False
        rot = self._file(key, create=True)["rotation"]
        for p in (pages if hasattr(pages, "__iter__") else [pages]):
            cur = int(rot.get(str(int(p)), 0))
            nv = (cur + int(delta)) % 360
            if nv == 0:
                rot.pop(str(int(p)), None)
            else:
                rot[str(int(p))] = nv
        return True

    def clear_rotation(self, file_path) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if fr and fr.get("rotation"):
            fr["rotation"] = {}
            return True
        return False

    # --- 선긋기(J3) — 정규화 좌표(0..1) ---
    def get_drawings(self, file_path, page0) -> list:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr:
            return []
        return list(fr.get("drawings", {}).get(str(int(page0)), []))

    def set_drawings(self, file_path, page0, strokes) -> bool:
        key = self._key(file_path)
        if key is None:
            return False
        dr = self._file(key, create=True)["drawings"]
        pg = str(int(page0))
        if strokes:
            dr[pg] = list(strokes)
        else:
            dr.pop(pg, None)
        return True

    def pages_with_drawings(self, file_path) -> set:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return {int(p) for p, v in (fr or {}).get("drawings", {}).items() if v}

    def clear_drawings(self, file_path, page0=None) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr or not fr.get("drawings"):
            return False
        if page0 is None:
            fr["drawings"] = {}
        else:
            fr["drawings"].pop(str(int(page0)), None)
        return True

    # --- 삽입 이미지(주석) 260611-15 ---
    def get_images(self, file_path, page0) -> list:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr:
            return []
        return list(fr.get("images", {}).get(str(int(page0)), []))

    def set_images(self, file_path, page0, images) -> bool:
        key = self._key(file_path)
        if key is None:
            return False
        im = self._file(key, create=True)["images"]
        pg = str(int(page0))
        if images:
            im[pg] = list(images)
        else:
            im.pop(pg, None)
        return True

    def pages_with_images(self, file_path) -> set:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return {int(p) for p, v in (fr or {}).get("images", {}).items() if v}

    def clear_images(self, file_path, page0=None) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if not fr or not fr.get("images"):
            return False
        if page0 is None:
            fr["images"] = {}
        else:
            fr["images"].pop(str(int(page0)), None)
        return True

    # --- 숨김(D5) ---
    def is_hidden(self, file_path, page0) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return bool(fr and int(page0) in set(fr.get("hidden", [])))

    def hidden_pages(self, file_path) -> set:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        return set(int(p) for p in (fr or {}).get("hidden", []))

    def set_hidden(self, file_path, pages, hidden: bool) -> bool:
        key = self._key(file_path)
        if key is None:
            return False
        fr = self._file(key, create=True)
        cur = set(int(p) for p in fr.get("hidden", []))
        for p in (pages if hasattr(pages, "__iter__") else [pages]):
            if hidden:
                cur.add(int(p))
            else:
                cur.discard(int(p))
        fr["hidden"] = sorted(cur)
        return True

    def clear_hidden(self, file_path) -> bool:
        key = self._key(file_path)
        fr = self._data["files"].get(key) if key else None
        if fr and fr.get("hidden"):
            fr["hidden"] = []
            return True
        return False
