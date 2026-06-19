"""resources/ko_en_dict.csv 생성 — kengdic(한영사전, CC-BY-SA-3.0) → surface→영어뜻.

입력: study_spike/kengdic.tsv (id,surface,hanja,gloss,level,...). 단일어 한국어 표제어만.
출력: resources/ko_en_dict.csv (surface, gloss[; 로 최대3개]).
런타임(vocab.define_ko_en)은 이 CSV 만 읽음 → 오프라인. 출처고지는 도움말 About.

사용: python gen_ko_en_dict.py   (smart_pdf_viewer/ 에서)
"""
from __future__ import annotations
import csv
import re
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "study_spike" / "kengdic.tsv"
OUT = HERE / "resources" / "ko_en_dict.csv"
_HANGUL = re.compile(r"[가-힣]")
_CLEAN = re.compile(r"\s+")


def clean_gloss(g: str) -> str:
    g = _CLEAN.sub(" ", (g or "").strip())
    g = g.strip(" ;,/")
    return g[:70]


def main() -> None:
    if not SRC.exists():
        print(f"[!] {SRC} 없음 — 먼저 kengdic.tsv 다운로드 필요")
        return
    table: "OrderedDict[str, list[str]]" = OrderedDict()
    n = 0
    with open(SRC, encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            surface = (row.get("surface") or "").strip()
            gloss = clean_gloss(row.get("gloss") or "")
            if not surface or not gloss:
                continue
            if " " in surface or len(surface) < 1:   # 단일어만(구/문장 제외)
                continue
            if not _HANGUL.search(surface):
                continue
            if not re.search(r"[A-Za-z]", gloss):    # 영어 알파벳 포함 뜻만
                continue
            lst = table.setdefault(surface, [])
            low = gloss.lower()
            if low not in {x.lower() for x in lst} and len(lst) < 3:
                lst.append(gloss)
            n += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for surface, glosses in table.items():
            w.writerow([surface, "; ".join(glosses)])
    print(f"생성: {OUT} ({len(table)}개 표제어, 원본 {n} 매핑)")
    for s in ("재료", "시공", "두께", "포장", "역청", "골재", "학교", "사랑", "물", "먹다"):
        print(f"  {s}: {table.get(s)}")


if __name__ == "__main__":
    main()
