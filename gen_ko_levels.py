"""resources/ko_levels.csv 생성 — wordfreq 한국어 빈도 데이터로 등급 산출 (오프라인).

wordfreq.get_frequency_dict('ko') 는 MeCab 없이 읽힌다(저장된 빈도 데이터).
zipf = log10(freq)+9 로 환산 → 계획 §3.3 밴딩(초/중/고).
런타임(viewer.study.vocab.level_ko)은 이 CSV 만 읽으므로 배포 EXE 에 MeCab 불필요.

사용:  python gen_ko_levels.py   (smart_pdf_viewer/ 에서)
출력:  resources/ko_levels.csv  (word,level)
"""
from __future__ import annotations
import csv
import math
import re
from pathlib import Path

import wordfreq

OUT = Path(__file__).resolve().parent / "resources" / "ko_levels.csv"
_HANGUL = re.compile(r"[가-힣]")


def band(z: float) -> str:
    if z >= 4.5:
        return "초급"
    if z >= 3.0:
        return "중급"
    return "고급"


def main() -> None:
    d = wordfreq.get_frequency_dict("ko")
    rows = []
    counts = {"초급": 0, "중급": 0, "고급": 0}
    for word, freq in d.items():
        # 내용어 후보만: 길이>=2 + 한글 포함 (단일 조사/어미 토큰 제외)
        if len(word) < 2 or not _HANGUL.search(word):
            continue
        if freq <= 0:
            continue
        z = math.log10(freq) + 9.0
        lv = band(z)
        rows.append((word, lv, round(z, 2)))
        counts[lv] += 1

    rows.sort(key=lambda r: -r[2])     # 쉬운(빈도 높은) 순
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for word, lv, _z in rows:
            w.writerow([word, lv])     # level_ko 는 (word, level) 2열만 사용
    print(f"생성: {OUT}  ({len(rows)}개)  초급 {counts['초급']} / "
          f"중급 {counts['중급']} / 고급 {counts['고급']}")
    print("샘플(초급):", [r[0] for r in rows[:8]])
    print("샘플(고급):", [r[0] for r in rows[-8:]])


if __name__ == "__main__":
    main()
