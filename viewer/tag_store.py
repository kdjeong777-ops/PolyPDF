"""파일 해시태그 저장소 — 책갈피창 파일에 태그(#종류)를 붙여 분류·검색.

설계(타 프로그램 검토 — macOS Finder 태그·Obsidian #태그·Eagle):
- 파일 1개 = 태그 N개(자유 입력 + 기존 태그 재사용). 태그는 폴더/이름과 독립.
- 저장: `settings_dir()/file_tags.json` — {절대경로(소문자): [태그…]}. 경로 이동 시 단순.
- 표시: 트리에서 파일명 뒤 ` #태그` 회색 접미. 검색: 검색박스에 `#태그` 토큰으로 필터,
  '#' 버튼으로 기존 태그 목록을 보여주고 클릭해 검색.
- 매칭은 대소문자 무시, 접두 일치 허용(예: '#도' → '도로').
표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def normalize_tags(tags) -> list:
    """문자열('#도로 콘크리트, 지침') 또는 리스트 → 정규화 태그 리스트(앞 '#'·공백 제거, 중복 제거)."""
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out, seen = [], set()
    for t in (tags or []):
        t = (t or "").lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


class TagStore:
    def __init__(self, path=None):
        if path is None:
            try:
                from viewer.settings_store import settings_dir
                path = Path(settings_dir()) / "file_tags.json"
            except Exception:
                path = Path.home() / ".polypdf_file_tags.json"
        self._path = Path(path)
        self._data = {}          # key(절대경로 소문자) -> [태그]
        self._load()

    def _load(self):
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8")) or {}
        except Exception:
            self._data = {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=0), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _key(p) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except Exception:
            return str(p or "").lower()

    def get(self, path) -> list:
        return list(self._data.get(self._key(path), []))

    def set(self, path, tags):
        tags = normalize_tags(tags)
        k = self._key(path)
        if tags:
            self._data[k] = tags
        else:
            self._data.pop(k, None)
        self._save()

    def all_tags(self) -> list:
        """등록된 모든 태그(사용 빈도 내림차순 → 이름순)."""
        cnt = {}
        for v in self._data.values():
            for t in v:
                cnt[t] = cnt.get(t, 0) + 1
        return sorted(cnt, key=lambda t: (-cnt[t], t.lower()))
