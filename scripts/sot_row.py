# -*- coding: utf-8 -*-
"""SOT §0 한 줄을 한 번에 넣는다 — 그 SOT §0 첫 행 + `뷰어 변경 이력 아카이브.md` 의 그 문서 절 첫 행 (261025-9).

CLAUDE.md §4 '§0 은 한 줄만': 같은 날짜·버전·제목을 SOT §0 과 아카이브 그 절에 **함께** 적는다. 손으로 적으면
문서 수 × 2 곳에 같은 제목을 복사하게 되고(261025-9 는 8곳), 한 곳이 어긋나면 `test_sot_compliance` 가 짝을 못 찾는다.

    python scripts/sot_row.py add --ver 1.0.0 --title "제목 (작업번호, 근거)" --docs 디자인,다국어 \
        --detail "아카이브에 남길 원문(무엇을·왜)" [--detail-for 다국어="그 문서만의 원문"] [--date 2026-10-25] [--master] [--dry-run]

- `--docs` 는 SOT 파일 이름의 일부(`디자인`·`검색창`·`단어학습` …). 하나에만 맞아야 한다.
- 마스터 §0 은 **지휘 세션 몫**(CLAUDE.md §1.6) — `--master` 를 줄 때만 넣는다.
- 넣기 전에 본다: 행 길이 ≤ `MAXLEN`, 날짜가 그 표 첫 행보다 앞서지 않음(내림차순), 같은 행이 이미 있으면 건너뜀.
  넣은 뒤 디스크에서 다시 읽어 SOT 와 아카이브 둘 다에 있는지 확인한다.
- 줄 끝(CRLF/LF)은 파일마다 그대로 둔다.
SOT 폴더는 공개 저장소 한 단계 위(`POLYPDF_SOT_DIR` 로 바꿀 수 있다 — 검사가 임시 사본에 돌린다).
"""
import argparse, datetime, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = "PolyPDF 뷰어 통합 작업 계획서.md"
ARCHIVE = "뷰어 변경 이력 아카이브.md"
HEAD = ("| 날짜 | 버전 | 내용 |", "| --- | --- | --- |")
MAXLEN = 220            # test_sot_compliance.py 의 MAXLEN 과 같다(§0 행 한 줄 요약)


def sot_dir() -> Path:
    return Path(os.environ.get("POLYPDF_SOT_DIR") or ROOT.parent)


def _read(p: Path):
    raw = p.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), nl


def _write(p: Path, text: str, nl: str) -> None:
    p.write_bytes(text.replace("\n", nl).encode("utf-8"))


def resolve(name: str, d: Path) -> str:
    names = [p.name for p in d.glob("*.md") if "아카이브" not in p.name and p.name != "CLAUDE.md"]
    if name in names:
        return name
    hit = [n for n in names if name in n]
    if len(hit) != 1:
        raise SystemExit("문서 '%s' 가 %s — 더 길게 적는다: %s" % (name, "없다" if not hit else "여럿에 맞는다", hit))
    return hit[0]


def make_row(date: str, ver: str, title: str) -> str:
    t = title.strip().strip("*").strip()
    if not t.endswith("."):
        t += "."
    return "| %s | %s | **%s** |" % (date, ver, t)


def _table_start(lines, i0: int) -> int:
    """i0 이후 첫 §0 표 머리의 다음 줄(첫 행 자리)."""
    for i in range(i0, len(lines) - 1):
        if lines[i].strip() == HEAD[0] and lines[i + 1].strip() == HEAD[1]:
            return i + 2
        if i > i0 and lines[i].startswith("## "):
            break
    return -1


def _check_order(lines, k: int, date: str, where: str) -> None:
    m = re.match(r"^\| (\d{4}-\d{2}-\d{2}) \|", lines[k]) if k < len(lines) else None
    if m and m.group(1) > date:
        raise SystemExit("%s: 첫 행 날짜 %s 가 새 행 %s 보다 늦다 — 날짜 내림차순을 깨뜨린다" % (where, m.group(1), date))


def insert(doc: str, row: str, detail: str, d: Path, dry: bool) -> list:
    out = []
    p = d / doc
    text, nl = _read(p)
    lines = text.split("\n")
    i0 = next((i for i, l in enumerate(lines) if l.startswith("## 0.")), -1)
    k = _table_start(lines, i0) if i0 >= 0 else -1
    if k < 0:
        raise SystemExit("%s: §0 표('%s')를 찾지 못했다" % (doc, HEAD[0]))
    if row in lines:
        out.append("건너뜀(이미 있음) %s §0" % doc)
    else:
        _check_order(lines, k, row[2:12], doc + " §0")
        lines.insert(k, row)
        out.append("넣음 %s §0 %d줄" % (doc, k + 1))
        if not dry:
            _write(p, "\n".join(lines), nl)
    ap = d / ARCHIVE
    atext, anl = _read(ap)
    alines = atext.split("\n")
    pat = re.compile(r"^## \d+\. .*`%s` §0" % re.escape(doc))
    s = next((i for i, l in enumerate(alines) if pat.match(l)), -1)
    if s < 0:
        raise SystemExit("%s 에 '## N. `%s` §0' 절이 없다 — 새 모듈이면 절을 먼저 만든다" % (ARCHIVE, doc))
    k = _table_start(alines, s)
    if k < 0:
        raise SystemExit("%s 의 %s 절에 표 머리가 없다" % (ARCHIVE, doc))
    arow = row[:-2].rstrip() + (" " + detail.strip() if detail.strip() else "") + " |"
    end = next((i for i in range(k, len(alines)) if alines[i].startswith("## ")), len(alines))   # 그 절 안만 본다
    if any(l.startswith(row[:-2].rstrip()) for l in alines[k:end]):
        out.append("건너뜀(이미 있음) 아카이브 · %s 절" % doc)
    else:
        _check_order(alines, k, row[2:12], "아카이브 " + doc)
        alines.insert(k, arow)
        out.append("넣음 아카이브 · %s 절 %d줄" % (doc, k + 1))
        if not dry:
            _write(ap, "\n".join(alines), anl)
    return out


def verify(doc: str, row: str, d: Path) -> bool:
    """SOT §0 에 그 행이 있고, 아카이브의 **그 문서 절** 안에 같은 제목으로 시작하는 행이 있다."""
    t, _ = _read(d / doc)
    a, _ = _read(d / ARCHIVE)
    m = re.search(r"^## \d+\. .*`%s` §0.*?(?=^## |\Z)" % re.escape(doc), a, re.M | re.S)
    return row in t.split("\n") and bool(m) and ("\n" + row[:-2].rstrip()) in m.group(0)


def main(argv=None) -> int:
    try:                                        # 한글·'—' 가 cp949 콘솔에서 UnicodeEncodeError 로 멈추지 않게(SystemExit 안내는 stderr)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="SOT §0 한 줄을 SOT 와 이력 아카이브에 함께 넣는다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--date", default=datetime.date.today().isoformat())
    a.add_argument("--ver", required=True, help="버전 칸 — 버전이 없는 메모 행은 —")
    a.add_argument("--title", required=True, help="굵은 제목 — '(작업번호, 근거…)' 로 끝낸다")
    a.add_argument("--docs", default="", help="모듈 SOT 이름 일부, 쉼표로")
    a.add_argument("--master", action="store_true", help="마스터 §0 에도(지휘 세션만)")
    a.add_argument("--detail", default="", help="아카이브 원문(무엇을·왜) — 문서마다 같은 글")
    a.add_argument("--detail-for", action="append", default=[], metavar="문서=원문", help="그 문서만의 원문")
    a.add_argument("--dry-run", action="store_true")
    o = ap.parse_args(argv)
    d = sot_dir()
    if not (d / MASTER).exists():
        raise SystemExit("SOT 폴더가 아니다: %s" % d)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", o.date):
        raise SystemExit("--date 는 YYYY-MM-DD")
    if not re.search(r"\(\d{6}-\d+", o.title):
        raise SystemExit("제목은 '(작업번호, 근거)' 를 담는다 — 예: '(261025-9, 사용자 지시)'")
    row = make_row(o.date, o.ver, o.title)
    if len(row) > MAXLEN:
        raise SystemExit("행이 %d자 — %d자 이하로 줄인다(상세는 --detail 로 아카이브에)" % (len(row), MAXLEN))
    docs = [resolve(x.strip(), d) for x in o.docs.split(",") if x.strip()]
    if o.master:
        docs.insert(0, MASTER)
    if not docs:
        raise SystemExit("--docs 나 --master 가 하나는 있어야 한다")
    if len(set(docs)) != len(docs):
        raise SystemExit("같은 문서를 두 번 골랐다: %s" % docs)
    per = {}
    for kv in o.detail_for:
        k, _, v = kv.partition("=")
        per[resolve(k.strip(), d)] = v
    first = docs[0]
    for doc in docs:
        det = per.get(doc, o.detail)
        if not det and doc != first:
            det = "상세는 `%s` 절 같은 행." % first
        for msg in insert(doc, row, det, d, o.dry_run):
            print(msg)
    if o.dry_run:
        print("(dry-run — 쓰지 않았다)")
        return 0
    bad = [doc for doc in docs if not verify(doc, row, d)]
    if bad:
        print("확인 실패 — 디스크에 없다:", bad)
        return 1
    if not o.master:
        print("※ 마스터 §0 행은 지휘 세션이 넣는다(CLAUDE.md §1.6) — 이 제목 줄을 보낸다:")
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
