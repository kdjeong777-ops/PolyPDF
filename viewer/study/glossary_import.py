"""용어집 임포트 — PDF/CSV 용어집을 dict_entry 로 적재 (계획서 §4.3, P3).

- 동봉 기본 용어집(JSON): resources/dict/*.json → DictStore.seed_source_if_newer 로 시드.
- PDF 용어집: 'Ÿ' 불릿 + `한글명(English)` 형식 파서(아스팔트 지침 등).
- CSV 용어집: 컬럼 매핑으로 적재.

기본 사전은 계속 보강 가능: 동봉 JSON 의 version 을 올리거나 새 파일을 추가하면
다음 실행 때 해당 출처만 멱등 재적재(중복 없음, 사용자 항목·on/off 보존).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

_PAREN = re.compile(r"\(([^()]*)\)")
_LATIN = re.compile(r"[A-Za-z]")
_HANJA = re.compile(r"[㐀-鿿豈-﫿]")
_SECTION = re.compile(r"^[ㄱ-ㅎ]$")          # 자모 섹션 헤더
_PAGENO = re.compile(r"^\d{1,4}$")


def _split_term(head: str) -> tuple[str, str, str]:
    """표제어 라인 → (term_ko, term_en, hanja).

    예: '개질(改質) 아스팔트(Modified Asphalt)' → ('개질 아스팔트','Modified Asphalt','改質')
        '가열밀링' → ('가열밀링','','')
    """
    s = (head or "").strip()
    groups = _PAREN.findall(s)
    en = [g.strip() for g in groups if _LATIN.search(g)]
    hj = [g.strip() for g in groups if _HANJA.search(g) and not _LATIN.search(g)]
    term_en = en[-1].strip() if en else ""
    hanja = hj[0].strip() if hj else ""
    term_ko = re.sub(r"\s+", " ", _PAREN.sub("", s)).strip()
    return term_ko, term_en, hanja


def parse_glossary_pdf(path: str, *,
                       drop_titles: Iterable[str] = (),
                       bullet: str = "Ÿ") -> list[dict]:
    """'Ÿ' 불릿 용어집 PDF → [{term_ko, term_en, hanja, def_ko}]."""
    import fitz
    doc = fitz.open(path)
    drop = {t.strip() for t in drop_titles}
    lines: list[str] = []
    for i in range(doc.page_count):
        for ln in doc[i].get_text("text").splitlines():
            s = ln.strip()
            if not s:
                continue
            if s in drop or _SECTION.match(s) or _PAGENO.match(s) or s == "숫자":
                continue
            lines.append(s)
    doc.close()
    text = "\n".join(lines)
    out: list[dict] = []
    for chunk in (c.strip() for c in text.split(bullet)):
        if not chunk:
            continue
        head, _, body = chunk.partition("\n")
        term_ko, term_en, hanja = _split_term(head)
        if not term_ko and not term_en:
            continue
        def_ko = re.sub(r"\s+", " ", body).strip()
        out.append({"term_ko": term_ko, "term_en": term_en,
                    "hanja": hanja, "def_ko": def_ko})
    return out


def parse_glossary_csv(path: str, mapping: dict) -> list[dict]:
    """CSV 용어집 → 항목 리스트. mapping: {필드: 컬럼명 또는 인덱스}.
    지원 필드: term_ko, term_en, def_ko, def_en, examples, reference, level, hanja."""
    import csv
    fields = ("term_ko", "term_en", "def_ko", "def_en",
              "examples", "reference", "level", "hanja", "image")
    out: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return out
    header = rows[0]
    col_idx = {h: i for i, h in enumerate(header)}

    def resolve(spec):
        if spec is None:
            return None
        if isinstance(spec, int):
            return spec
        return col_idx.get(spec)

    idx = {fld: resolve(mapping.get(fld)) for fld in fields}
    # 헤더로 매핑되면 데이터는 1행부터, 인덱스 매핑이면 전체
    data = rows[1:] if any(isinstance(v, str) for v in mapping.values()) else rows
    for r in data:
        e = {}
        for fld in fields:
            i = idx[fld]
            e[fld] = r[i].strip() if (i is not None and i < len(r)) else ""
        if e.get("term_ko") or e.get("term_en"):
            out.append(e)
    return out


# --- 동봉 기본 용어집 시드 ------------------------------------------------
def bundled_glossary_dir() -> Optional[Path]:
    from viewer.resources_path import resource_path
    p = resource_path("dict")
    return Path(p) if p else None


def load_bundled_glossaries(store) -> list[str]:
    """resources/dict/*.json 을 출처별로 시드(version 비교, 멱등). 시드된 출처명 반환.

    JSON 형식: {source_id, name, reference, version, entries:[{term_ko,...}]}.
    """
    d = bundled_glossary_dir()
    if not d or not d.exists():
        return []
    seeded: list[str] = []
    for jf in sorted(d.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            sid = data["source_id"]
            if store.seed_source_if_newer(
                    sid, data.get("name", sid),
                    reference=data.get("reference", ""),
                    version=int(data.get("version", 1)),
                    rows=data.get("entries", []),
                    priority=int(data.get("priority", 50)),
                    is_termbase=bool(data.get("is_termbase", True)),
                    category=data.get("category", "")):
                seeded.append(data.get("name", sid))
        except Exception:
            continue
    return seeded


def import_glossary_file(store, path: str, *, source_id: str, name: str,
                         reference: str = "", kind: str = "base",
                         csv_mapping: Optional[dict] = None,
                         version: int = 1, is_termbase: bool = True,
                         category: str = "") -> int:
    """사용자 업로드 용어집(PDF/CSV) 임포트 → 새 출처로 적재(멱등). 적재 항목 수 반환."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        rows = parse_glossary_pdf(path)
    elif ext in (".csv", ".tsv", ".txt"):
        rows = parse_glossary_csv(path, csv_mapping or {})
        # 260615-8(P10): CSV 의 image(경로/URL) → dict_images 로 복사·다운로드해 등록
        from viewer.study.image_fetch import resolve_csv_image
        base_dir = Path(path).parent
        for r in rows:
            iv = (r.get("image") or "").strip()
            if iv:
                fn, ref = resolve_csv_image(iv, r.get("term_ko") or r.get("term_en") or "img",
                                            base_dir=base_dir)
                r["image"], r["image_ref"] = fn, ref
    else:
        raise ValueError(f"지원하지 않는 형식: {ext}")
    store.add_source(source_id, name, kind=kind, reference=reference,
                     priority=60, version=version, is_termbase=is_termbase,
                     category=category)
    return store.replace_source_entries(source_id, rows)
