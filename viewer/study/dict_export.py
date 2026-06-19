"""사전 내보내기 — CSV / TBX(ISO 30042 TBX-Basic) (계획서 §4 P7).

상호운용: 사용자·기본 용어사전을 외부 표준 포맷으로 내보내 CAT 툴 등과 연계.
- CSV: 헤더(term_ko,term_en,def_ko,def_en,examples,reference,level,hanja,source).
- TBX: 개념(conceptEntry) 단위 — ko/en langSec + definition/context(descrip) + source(admin).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

CSV_FIELDS = ("term_ko", "term_en", "def_ko", "def_en", "examples",
              "reference", "level", "hanja", "source")


def export_csv(store, path: str, *, source_id: Optional[str] = None) -> int:
    rows = store.export_rows(source_id)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for r in rows:
            w.writerow([
                r.get("term_ko", ""), r.get("term_en", ""),
                r.get("def_ko", ""), r.get("def_en", ""),
                (r.get("examples", "") or "").replace("\n", " / "),
                r.get("reference", "") or r.get("src_reference", ""),
                r.get("level", ""), r.get("hanja", ""),
                r.get("src_name", "") or r.get("source_id", ""),
            ])
    return len(rows)


def _lang_sec(lang: str, term: str, defi: str, examples: str) -> str:
    if not (term or defi or examples):
        return ""
    parts = [f'<langSec xml:lang="{lang}">']
    if term:
        parts.append(f"<termSec><term>{escape(term)}</term></termSec>")
    if defi:
        parts.append(f'<descrip type="definition">{escape(defi)}</descrip>')
    for ex in (examples or "").split("\n"):
        ex = ex.strip()
        if ex:
            parts.append(f'<descrip type="context">{escape(ex)}</descrip>')
    parts.append("</langSec>")
    return "".join(parts)


def export_tbx(store, path: str, *, source_id: Optional[str] = None) -> int:
    rows = store.export_rows(source_id)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<tbx type="TBX-Basic" style="dca" '
           'xmlns="urn:iso:std:iso:30042:ed-2" xml:lang="ko">',
           "<tbxHeader><fileDesc><sourceDesc><p>PolyPDF terminology export"
           "</p></sourceDesc></fileDesc></tbxHeader>",
           "<text><body>"]
    n = 0
    for i, r in enumerate(rows, 1):
        ko = _lang_sec("ko", r.get("term_ko", ""), r.get("def_ko", ""),
                       r.get("examples", ""))
        en = _lang_sec("en", r.get("term_en", ""), r.get("def_en", ""), "")
        if not (ko or en):
            continue
        ref = (r.get("reference", "") or r.get("src_reference", "")).strip()
        admin = f'<admin type="source">{escape(ref)}</admin>' if ref else ""
        out.append(f'<conceptEntry id="c{i}">{admin}{ko}{en}</conceptEntry>')
        n += 1
    out.append("</body></text></tbx>")
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return n
