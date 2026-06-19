"""resources/en_ko_dict.csv 생성 — kengdic 역방향(영어→한국어). 영어 단어의 한글 뜻.

kengdic: surface(한)→gloss(영). 역으로 영어 단일어 gloss → 한국어 surface 매핑.
영어 표제어(lemmatized lower) → 한국어 뜻 목록(최대 4). 런타임 vocab.define_en_ko 가 사용.
사용: python gen_en_ko_dict.py  (smart_pdf_viewer/ 에서)
"""
from __future__ import annotations
import csv
import re
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "study_spike" / "kengdic.tsv"
OUT = HERE / "resources" / "en_ko_dict.csv"
_HANGUL = re.compile(r"[가-힣]")
_EN_WORD = re.compile(r"^(?:a |an |the |to )?([a-z][a-z\-]{1,})$")


def main() -> None:
    if not SRC.exists():
        print(f"[!] {SRC} 없음")
        return
    table: "OrderedDict[str, list[str]]" = OrderedDict()
    n = 0
    with open(SRC, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            surface = (row.get("surface") or "").strip()
            gloss = (row.get("gloss") or "").strip()
            if not surface or not gloss or " " in surface or not _HANGUL.search(surface):
                continue
            # gloss 를 ,;/ 로 분리, 각 조각이 '단일 영어 단어'면 키로
            for piece in re.split(r"[,;/]", gloss.lower()):
                m = _EN_WORD.match(piece.strip())
                if not m:
                    continue
                key = m.group(1)
                if len(key) < 2:
                    continue
                lst = table.setdefault(key, [])
                if surface not in lst and len(lst) < 4:
                    lst.append(surface)
                    n += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for en, kos in table.items():
            w.writerow([en, ", ".join(kos)])
    print(f"생성: {OUT} ({len(table)}개 영어표제어, {n} 매핑)")
    for s in ("love", "school", "material", "water", "run", "construction", "thickness"):
        print(f"  {s}: {table.get(s)}")


if __name__ == "__main__":
    main()
