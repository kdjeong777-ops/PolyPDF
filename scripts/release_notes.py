# -*- coding: utf-8 -*-
"""261008-18(마스터 SOT §14.5 U14): 릴리스 설명을 **커밋 메시지로** 만든다.

`gh release create --generate-notes` 는 PR 을 기준으로 뽑아, PR 없이 커밋하는 이 저장소에서는
'Full Changelog' 링크 한 줄만 남았다 — 앱의 업데이트 창에 보여 줄 내용이 없었다.

사용:  python scripts/release_notes.py v0.45.0-beta.197 notes.md
  - 파일로 직접 쓴다(UTF-8). CI 의 PowerShell 파이프로 받으면 콘솔 인코딩에 따라 한글이 깨진다.
  - 이전 버전 태그(같은 줄기에서 가장 가까운 `v*`)부터 이 태그까지의 커밋을 모은다.
  - 제목: `fix:`/`feat:`/`docs(…):` 머리를 '수정'/'기능'/'문서' 로, 끝의 `(작업번호, 버전)` 괄호는 뺀다.
  - 본문: `- ` 로 시작하는 항목만(검사 파일 이름이 든 줄·Co-Authored-By 는 뺀다).
"""
import re
import subprocess
import sys

REPO_URL = "https://github.com/kdjeong777-ops/PolyPDF"
KIND = {"feat": "기능", "fix": "수정", "docs": "문서", "perf": "성능", "refactor": "정리",
        "build": "빌드", "ci": "빌드", "chore": "정리", "test": "검사"}
_HEAD = re.compile(r"^(\w+)(?:\([^)]*\))?!?:\s*")
_TAIL = re.compile(r"\s*\([^()]*\d+\.\d+\.\d+[^()]*\)\s*$")     # 끝의 '(…, 0.45.0-beta.197)'


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", check=False).stdout


def previous_tag(tag: str) -> str:
    return git("describe", "--tags", "--abbrev=0", "--match", "v*", tag + "^").strip()


def commits(prev: str, tag: str):
    rng = f"{prev}..{tag}" if prev else tag
    raw = git("log", "--no-merges", "--format=%s%x1f%b%x1e", rng)
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        subj, _, body = rec.partition("\x1f")
        yield subj.strip(), body


def render(tag: str, prev: str) -> str:
    lines = []
    for subj, body in commits(prev, tag):
        m = _HEAD.match(subj)
        kind = KIND.get(m.group(1).lower(), "") if m else ""
        title = _TAIL.sub("", subj[m.end():] if m else subj).strip()
        if not title:
            continue
        lines.append(f"- **{kind}** {title}" if kind else f"- {title}")
        keep = False                       # 지금 줄이 살린 항목의 이어지는 줄인가
        for b in body.splitlines():
            t = b.strip()
            if t.startswith("- "):
                keep = not ("test_" in t)
                if keep:
                    lines.append("    " + t)
            elif keep and t and b[:1].isspace():          # 들여 쓴 다음 줄 = 앞 항목의 이어짐
                lines[-1] += " " + t
            else:
                keep = False
    out = ["## 바뀐 내용", ""]
    out += lines or ["- (설명할 변경이 없습니다)"]
    if prev:
        out += ["", f"**전체 비교**: {REPO_URL}/compare/{prev}...{tag}"]
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) < 2:
        print("usage: release_notes.py <tag> [out.md]", file=sys.stderr)
        return 2
    tag = sys.argv[1]
    text = render(tag, previous_tag(tag))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
