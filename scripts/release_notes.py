# -*- coding: utf-8 -*-
"""261008-18(마스터 SOT §14.5 U14): 릴리스 설명을 **커밋 메시지로** 만든다.

`gh release create --generate-notes` 는 PR 을 기준으로 뽑아, PR 없이 커밋하는 이 저장소에서는
'Full Changelog' 링크 한 줄만 남았다 — 앱의 업데이트 창에 보여 줄 내용이 없었다.

사용:  python scripts/release_notes.py v0.45.0-beta.197 notes.md
  - 파일로 직접 쓴다(UTF-8). CI 의 PowerShell 파이프로 받으면 콘솔 인코딩에 따라 한글이 깨진다.
  - 이전 버전 태그(같은 줄기에서 가장 가까운 `v*`)부터 이 태그까지의 커밋을 모은다.
  - 제목: `fix:`/`feat:`/`docs(…):` 머리를 '수정'/'기능'/'문서' 로, 끝의 `(작업번호, 버전)` 괄호는 뺀다.
  - 본문: `- ` 로 시작하는 항목만(검사 파일 이름이 든 줄·Co-Authored-By 는 뺀다).
  - 261008-27(다국어 SOT §10.4): 커밋 꼬리말 `Release-Note-<코드>: …`(한 줄에 한 항목, 여러 개 가능)으로
    다른 언어 설명을 쓴다. 본문은 언어마다 `<!-- lang:<코드> -->` 로 시작하는 절로 나뉜다(GitHub 페이지에서는
    표시가 보이지 않는다). 한국어 절은 언제나 있고, 꼬리말이 없는 커밋은 한국어 절에만 들어간다.
  - ★ 261114-9(릴리스 SOT §6, 사용자 지시): 판마다 초안 `release_notes/<태그>.md` 가 있으면 커밋 목록 대신 그 글을 쓴다
    ('이번 판에서 달라진 점'·'이렇게 써 보세요', 언어별 절). '그 밖의 고침' 이 초안에 없으면 feat·fix·perf 커밋 제목을
    한 줄씩(영어는 꼬리말) 붙인다. 초안이 없으면 위의 종전 꼴.

초안 점검:  python scripts/release_notes.py --check release_notes/v1.1.0-beta.13.md   (오류면 종료 코드 1)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from viewer.branding import UPDATE_REPO as _REPO      # noqa: E402 — 261114-8: 저장소 주소(이사 스위치)
REPO_URL = "https://github.com/" + _REPO
KIND = {"feat": "기능", "fix": "수정", "docs": "문서", "perf": "성능", "refactor": "정리",
        "build": "빌드", "ci": "빌드", "chore": "정리", "test": "검사"}
_HEAD = re.compile(r"^(\w+)(?:\([^)]*\))?!?:\s*")
_TAIL = re.compile(r"\s*\([^()]*\d+\.\d+\.\d+[^()]*\)\s*$")     # 끝의 '(…, 0.45.0-beta.197)'
_TRAILER = re.compile(r"^Release-Note-([A-Za-z_]+):\s*(.+?)\s*$")
# 언어마다 절 머리·비교 링크 이름·빈 절(앱 업데이트 창이 이 머리를 지운다 — update_dialog._NOTES_HEAD)
_CODE = re.compile(r"(`[^`\n]*`)")


def escape_angles(text: str) -> str:
    """261105-3: 글의 `<이름>`·`<N>` 을 `\\<…\\>` 로 — 앱 업데이트 창(QTextBrowser 마크다운)이 HTML 태그로 읽어
    뒤 글이 사라지고 점만 있는 빈 줄이 남았다. 이미 설치된 옛 판 창도 고칠 수 없으니 설명 쪽에서 막는다
    (GitHub 페이지에서도 `\\<` 는 `<` 로 보인다). 코드 표기(`…`) 안은 그대로."""
    parts = _CODE.split(text)
    return "".join(pt if i % 2 else pt.replace("<", r"\<").replace(">", r"\>") for i, pt in enumerate(parts))


HEADS = {"ko": ("## 바뀐 내용", "**전체 비교**", "- (설명할 변경이 없습니다)"),
         "en": ("## What's changed", "**Full comparison**", "- (No notable changes)")}


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


DRAFT_DIR = "release_notes"
# 초안의 절 제목(언어마다): 주요 기능 · 써 볼 것 · 그 밖의 고침 — 업데이트 창의 버전 제목이 `###` 라 `####` 부터
DRAFT_HEADS = {"ko": ("이번 판에서 달라진 점", "이렇게 써 보세요", "그 밖의 고침"),
               "en": ("What's new", "Try it", "Other fixes")}
SHORT_KINDS = ("feat", "fix", "perf")       # '그 밖의 고침' 에 한 줄로 드는 커밋(docs·test·build 등은 사용자 몫이 아니다)
HIGHLIGHTS = (3, 6)                         # 사용자 결정: 주요 항목 3~6개
_LANG_MARK = re.compile(r"^<!--\s*lang:([A-Za-z_\-]+)\s*-->\s*$", re.M)     # = update_dialog._LANG_MARK
_HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
_HTML = re.compile(r"<\s*/?\s*[A-Za-z!]")
# 내부 시험 기록은 비공개(릴리스 SOT §6, 261109-2)
_INTERNAL = ("test_", "_review", "summary.md", "확인한 것", "못 한 것", "release_test")


def split_sections(text: str) -> dict:
    """`<!-- lang:xx -->` 로 나뉜 글 → {코드: 절}. 표시가 없으면 {"ko": 전체}."""
    marks = list(_LANG_MARK.finditer(text or ""))
    if not marks:
        return {"ko": (text or "").strip()}
    return {m.group(1).lower(): text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))].strip()
            for i, m in enumerate(marks)}


def _heads(code):
    return DRAFT_HEADS.get(code, DRAFT_HEADS["en"])


def check_draft(text: str):
    """초안 점검 → (오류, 경고). 오류는 앱 창에서 깨지거나 비공개가 새는 것, 경고는 꼴의 권장."""
    errs, warns = [], []
    secs = split_sections(text)
    if not _LANG_MARK.search(text or ""):
        errs.append("언어 표시(<!-- lang:ko -->·<!-- lang:en -->)가 없다")
    for need in ("ko", "en"):
        if not secs.get(need):
            errs.append("%s 절이 없다 — 영어 화면의 업데이트 창도 설명을 보인다(다국어 SOT §10.4)" % need)
    for code, body in secs.items():
        new, tryit, _other = _heads(code)
        titles, items, cur = [], {}, None
        for ln in body.splitlines():
            m = _HEADING.match(ln)
            if m:
                cur = m.group(2)
                titles.append(cur)
                if len(m.group(1)) < 4:
                    errs.append("[%s] '%s' — 제목은 #### 부터(업데이트 창의 버전 제목이 ###)" % (code, ln.strip()))
                continue
            if ln.startswith("- ") and cur is not None:
                items[cur] = items.get(cur, 0) + 1
        plain = "".join(p for i, p in enumerate(_CODE.split(body)) if not i % 2)
        if _HTML.search(plain):
            errs.append("[%s] HTML(접기 <details> 등)은 업데이트 창에 글자 그대로 보인다 — 쓰지 않는다" % code)
        bad = [w for w in _INTERNAL if w in body]
        if bad:
            errs.append("[%s] 내부 시험 기록은 공개하지 않는다(릴리스 SOT §6): %s" % (code, ", ".join(bad)))
        if new not in titles:
            errs.append("[%s] '#### %s' 절이 없다" % (code, new))
        else:
            n = items.get(new, 0)
            if n == 0:
                errs.append("[%s] '%s' 에 항목(- …)이 없다" % (code, new))
            elif not HIGHLIGHTS[0] <= n <= HIGHLIGHTS[1]:
                warns.append("[%s] '%s' 항목 %d개 — 권장 %d~%d개" % (code, new, n, *HIGHLIGHTS))
        if tryit not in titles:
            warns.append("[%s] '#### %s' 절이 없다 — 새 기능이 없는 판이면 괜찮다" % (code, tryit))
    return errs, warns


def read_draft(tag: str):
    """`release_notes/<태그>.md`(저장소 맨 위 기준) — CI 는 태그를 받아 두므로 태그 때의 파일, 태그 전 미리 보기는 작업 트리."""
    top = git("rev-parse", "--show-toplevel").strip() or "."
    path = os.path.join(top, DRAFT_DIR, tag + ".md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def render_draft(draft: str, tag: str, prev: str) -> str:
    short = {"ko": []}
    for subj, body in commits(prev, tag):
        for b in body.splitlines():
            mt = _TRAILER.match(b.strip())
            if mt:
                short.setdefault(mt.group(1).lower(), []).append("- " + escape_angles(mt.group(2)))
        m = _HEAD.match(subj)
        if not m or m.group(1).lower() not in SHORT_KINDS:
            continue
        title = escape_angles(_TAIL.sub("", subj[m.end():]).strip())
        if title:
            short["ko"].append("- " + title)
    out = []
    for code, body in split_sections(draft).items():
        other = _heads(code)[2]
        _h, cmp_label, _e = HEADS.get(code, HEADS["en"])
        out += ["<!-- lang:%s -->" % code, escape_angles(body.strip()), ""]
        has_other = re.search(r"^#{1,6}\s*%s\s*$" % re.escape(other), body, re.M)
        if not has_other and short.get(code):
            out += ["#### " + other, ""] + short[code] + [""]
        if prev:
            out += [f"{cmp_label}: {REPO_URL}/compare/{prev}...{tag}", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def render(tag: str, prev: str) -> str:
    draft = read_draft(tag)
    if draft is not None:
        return render_draft(draft, tag, prev)
    lines = []
    other = {}                             # 코드 → [꼬리말 항목]
    for subj, body in commits(prev, tag):
        for b in body.splitlines():
            mt = _TRAILER.match(b.strip())
            if mt:
                other.setdefault(mt.group(1).lower(), []).append("- " + escape_angles(mt.group(2)))
        m = _HEAD.match(subj)
        kind = KIND.get(m.group(1).lower(), "") if m else ""
        title = escape_angles(_TAIL.sub("", subj[m.end():] if m else subj).strip())
        if not title:
            continue
        lines.append(f"- **{kind}** {title}" if kind else f"- {title}")
        keep = False                       # 지금 줄이 살린 항목의 이어지는 줄인가
        for b in body.splitlines():
            t = escape_angles(b.strip())
            if t.startswith("- "):
                keep = not ("test_" in t)
                if keep:
                    lines.append("    " + t)
            elif keep and t and b[:1].isspace():          # 들여 쓴 다음 줄 = 앞 항목의 이어짐
                lines[-1] += " " + t
            else:
                keep = False
    secs = [("ko", lines)] + [(c, other[c]) for c in sorted(other) if c != "ko"]
    out = []
    for code, items in secs:
        head, cmp_label, empty = HEADS.get(code, HEADS["en"])
        out += ["<!-- lang:%s -->" % code, head, ""]
        out += items or [empty]
        if prev:
            out += ["", f"{cmp_label}: {REPO_URL}/compare/{prev}...{tag}"]
        out += [""]
    return "\n".join(out).rstrip("\n") + "\n"


# 261114-8(릴리스 SOT §14.5 U26 다리 판): 옛 저장소에 내는 이사 판 — '새 이름·새 GitHub 로 옮김' 을 **언어 절마다 맨 위**에.
#   앱 업데이트 창(`update_dialog.split_lang_sections`)은 첫 `<!-- lang:… -->` 앞 글을 버리므로 노트 맨 앞에 붙이면 앱에서 안 보인다.
MOVE_NOTICE = {
    "ko": ("**PolyPDF 는 PolyPinax 로 이름을 바꾸고 https://github.com/kdjeong777-ops/PolyPinax 로 옮겼습니다.** "
           "이 업데이트로 설치한 앱이 새 이름·새 주소로 넘어가며, 설정·검색 색인은 그대로 이어집니다."),
    "en": ("**PolyPDF is now PolyPinax and has moved to https://github.com/kdjeong777-ops/PolyPinax.** "
           "This update moves your installed app to the new name and address; your settings and search index carry over."),
}


def add_move_notice(text: str) -> str:
    """언어 절마다 맨 위에 옮김 안내(이미 있으면 그대로). 언어 표시가 없는 옛 꼴은 한·영 두 줄을 맨 앞에."""
    text = text or ""
    if MOVE_NOTICE["ko"] in text:
        return text
    marks = list(_LANG_MARK.finditer(text))
    if not marks:
        return MOVE_NOTICE["ko"] + "\n\n" + MOVE_NOTICE["en"] + "\n\n" + text
    out, last = [], 0
    for m in marks:
        out.append(text[last:m.end()])
        code = m.group(1).lower()
        out.append("\n" + MOVE_NOTICE.get(code, MOVE_NOTICE["en"]) + "\n")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def main():
    if len(sys.argv) < 2:
        print("usage: release_notes.py <tag> [out.md]  |  release_notes.py --check <draft.md>", file=sys.stderr)
        return 2
    if sys.argv[1] == "--check":
        sys.stdout.reconfigure(encoding="utf-8")
        with open(sys.argv[2], encoding="utf-8") as f:
            errs, warns = check_draft(f.read())
        for e in errs:
            print("오류 -", e)
        for w in warns:
            print("경고 -", w)
        print("통과" if not errs else "고칠 것 %d" % len(errs))
        return 1 if errs else 0
    tag = sys.argv[1]
    text = render(tag, previous_tag(tag))
    if os.environ.get("APP_BRIDGE") == "1":                 # 261114-8: release.yml 이 옛 저장소에서 이사 판을 낼 때(다리 판)
        text = add_move_notice(text)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
