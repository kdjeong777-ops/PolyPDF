"""단어장 폴더 동기화 (하이브리드) — 폴더의 표준 단어장 파일을 dict.db 출처로 등록.

SOT: `단어장 작업 계획서.md`.
- 폴더(`…/PolyPDF/glossaries/`, 설정 `glossary_dir` 로 변경 가능)의 CSV/TSV/JSON 단어장을
  dict.db 출처로 동기화(파일 mtime=version, 변경분만 재적재, 사라진 파일은 출처 삭제).
- 사이드카 `{이름}.meta.json`: {name, category, priority, is_termbase, enabled}.
- 조회는 단일 dict.db 유지(빠름) — 관리·공유·교체는 폴더 파일로.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PREFIX = "folder__"
_EXTS = (".csv", ".tsv", ".txt", ".json")


def glossaries_dir(prefs: dict = None) -> Path:
    d = ((prefs or {}).get("glossary_dir") or "").strip()
    if d:
        return Path(d)
    try:
        from viewer.settings_store import settings_dir
        base = settings_dir()
    except Exception:
        base = Path.home()
    return Path(base) / "glossaries"


def _slug(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", s or "").strip("_").lower() or "g"


def _read_meta(fp: Path) -> dict:
    meta = {"name": fp.stem, "category": "", "priority": 100,
            "is_termbase": True, "enabled": True}
    side = fp.with_suffix(fp.suffix + ".meta.json")
    side2 = fp.with_name(fp.stem + ".meta.json")
    for s in (side, side2):
        if s.exists():
            try:
                d = json.loads(s.read_text(encoding="utf-8"))
                for k in ("name", "category"):
                    if d.get(k):
                        meta[k] = str(d[k])
                if "priority" in d:
                    meta["priority"] = int(d["priority"])
                if "is_termbase" in d:
                    meta["is_termbase"] = bool(d["is_termbase"])
                if "enabled" in d:
                    meta["enabled"] = bool(d["enabled"])
            except Exception:
                pass
            break
    return meta


def _parse_rows(fp: Path) -> list:
    ext = fp.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        import csv
        from viewer.study.glossary_import import parse_glossary_csv
        try:
            with open(fp, encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f), [])
        except Exception:
            header = []
        fields = ("term_ko", "term_en", "def_ko", "def_en",
                  "examples", "reference", "level", "hanja", "image")
        mapping = {fld: fld for fld in fields if fld in header}   # 표준 양식: 헤더=필드명
        return parse_glossary_csv(str(fp), mapping)
    if ext == ".json":
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return []
        entries = data.get("entries") if isinstance(data, dict) else data
        out = []
        for e in (entries or []):
            if not isinstance(e, dict):
                continue
            if e.get("term_ko") or e.get("term_en"):
                out.append(e)
        return out
    return []


def sync_folder(store, prefs: dict = None) -> dict:
    """폴더 → dict.db 출처 동기화. {files, updated, removed} 반환."""
    folder = glossaries_dir(prefs)
    summary = {"files": 0, "updated": 0, "removed": 0, "dir": str(folder)}
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        return summary
    seen = set()
    for fp in sorted(folder.iterdir()):
        if not fp.is_file() or fp.suffix.lower() not in _EXTS:
            continue
        if fp.name.endswith(".meta.json"):
            continue
        summary["files"] += 1
        sid = _PREFIX + _slug(fp.stem)
        seen.add(sid)
        meta = _read_meta(fp)
        try:
            ver = int(fp.stat().st_mtime)
        except Exception:
            ver = 0
        # 메타(이름/구분/우선순위/켜짐)는 항상 최신화
        try:
            store.add_source(sid, meta["name"], kind="base",
                             category=meta["category"], priority=meta["priority"],
                             enabled=meta["enabled"], is_termbase=meta["is_termbase"],
                             version=ver)
        except Exception:
            continue
        if store.source_version(sid) == ver and store.count(sid) > 0:
            continue  # 내용 변경 없음
        rows = _parse_rows(fp)
        if rows:
            store.replace_source_entries(sid, rows)
            store.add_source(sid, meta["name"], kind="base",
                             category=meta["category"], priority=meta["priority"],
                             enabled=meta["enabled"], is_termbase=meta["is_termbase"],
                             version=ver)
            summary["updated"] += 1
    # 폴더에서 사라진 파일의 출처 삭제
    try:
        for s in store.list_sources():
            sid = s.get("source_id", "")
            if sid.startswith(_PREFIX) and sid not in seen:
                store.delete_source(sid)
                summary["removed"] += 1
    except Exception:
        pass
    return summary


_SAMPLE = (
    "term_en,term_ko,def_ko,def_en,examples,level,category\n"
    "recycling agent,재생첨가제,노화된 아스팔트의 물성을 회복시키는 첨가제,,,전문용어,도로\n"
    "asphalt binder,아스팔트 바인더,골재를 결합하는 역청 결합재,,,전문용어,도로\n"
    "RAP,순환골재 아스팔트(RAP),재생 아스팔트 포장 골재,,,전문용어,도로\n"
)


def write_sample(folder: Path = None, prefs: dict = None) -> Path:
    """표준 양식 예제 CSV + meta 를 폴더에 저장하고 경로 반환."""
    folder = Path(folder) if folder else glossaries_dir(prefs)
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "예제_단어장.csv"
    csv_path.write_text(_SAMPLE, encoding="utf-8-sig")
    meta = {"name": "예제 단어장", "category": "도로", "priority": 50,
            "is_termbase": True, "enabled": True}
    (folder / "예제_단어장.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path
