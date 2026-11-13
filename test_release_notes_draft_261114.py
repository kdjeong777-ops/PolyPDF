# -*- coding: utf-8 -*-
"""261114-9(릴리스 SOT §6·§14.5 U14): 공개 릴리스 설명을 '주요 기능 + 써 볼 것' 으로.

사용자 지시: "이후 릴리즈시 보여주는 태그는 중요사항 위주로 홍보하거나, 확인할 내용으로 정리해서 만들도록 수정 보완해"
종전에는 커밋 제목·본문을 늘어놓아 무엇이 중요한지 보이지 않았다.

A. 초안 `release_notes/<태그>.md` 가 있으면 그 글 + '그 밖의 고침'(feat·fix·perf 제목 한 줄씩, 본문·docs·test 없음)
B. 영어 절 — 초안의 영어 글 + 꼬리말(Release-Note-en)의 '그 밖의 고침'
C. 초안이 이미 '그 밖의 고침' 을 두면 다시 붙이지 않는다
D. 초안이 없으면 종전 꼴(커밋 메시지)
E. 앱 업데이트 창(실제 QTextBrowser.setMarkdown)에 제목·글이 보이고 '#' 가 글자로 남지 않는다
F. --check — 영어 절 없음·'###' 제목·HTML(접기)·내부 시험 낱말은 막고, 주요 항목 3~6 밖은 경고
G. 저장소에 있는 초안은 모두 --check 통과
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QTextBrowser

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


SCRIPT = os.path.join(HERE, "scripts", "release_notes.py")

DRAFT = """<!-- lang:ko -->
#### 이번 판에서 달라진 점
- **해시태그 수정** — 고른 파일에만 태그를 넣고 되돌릴 수 있습니다
- **책갈피 모두 접기** — 위아래로 옮겨도 다시 펼쳐지지 않습니다
- **클립보드 복사** — 다른 프로그램이 멈추지 않습니다

#### 이렇게 써 보세요
- 파일 탭 → 해시태그 수정 → 파일 고르기 → 저장

<!-- lang:en -->
#### What's new
- **Edit hashtags** — tag only the files you pick, with undo
- **Collapse all** — stays collapsed while moving with arrow keys
- **Clipboard copy** — other programs no longer freeze

#### Try it
- File tab → Edit hashtags → pick files → Save
"""


def make_repo(draft=None, draft_name="v1.0.1"):
    repo = tempfile.mkdtemp(prefix="polypdf_relnotes_draft_")

    def g(*a):
        return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("commit", "-q", "--allow-empty", "-m", "first"); g("tag", "v1.0.0")
    g("commit", "-q", "--allow-empty", "-m",
      "fix: 저장 오류 고침 (1, 1.0.1)\n\n- 본문 항목은 빠진다\n\nRelease-Note-en: Saving works again\n\n"
      "Co-Authored-By: x <x@x>")
    g("commit", "-q", "--allow-empty", "-m", "docs: SOT 문서 손질 (2, 1.0.1)\n\n- 문서 본문")
    g("commit", "-q", "--allow-empty", "-m", "test: 검사 더함 (3, 1.0.1)")
    g("commit", "-q", "--allow-empty", "-m", "feat(tags): 해시태그 수정 창 (4, 1.0.1)\n\n- 본문 둘")
    g("commit", "-q", "--allow-empty", "-m", "perf: 시작이 빨라짐 (5, 1.0.1)")
    if draft is not None:
        os.makedirs(os.path.join(repo, "release_notes"), exist_ok=True)
        with open(os.path.join(repo, "release_notes", draft_name + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(draft)
        g("add", "release_notes"); g("commit", "-q", "-m", "docs: 릴리스 설명 초안 (6, 1.0.1)")
    g("tag", "v1.0.1")
    return repo


def notes_for(repo, tag="v1.0.1"):
    r = subprocess.run([sys.executable, SCRIPT, tag], capture_output=True, text=True, encoding="utf-8", cwd=repo)
    return r.stdout, r.stderr


try:
    from viewer.widgets.update_dialog import changes_markdown, split_lang_sections

    # ── A·B ──
    repo = make_repo(DRAFT)
    out, err = notes_for(repo)
    shutil.rmtree(repo, ignore_errors=True)
    secs = split_lang_sections(out)
    ko, en = secs.get("ko", ""), secs.get("en", "")
    chk(ko.startswith("#### 이번 판에서 달라진 점") and "해시태그 수정" in ko and "#### 이렇게 써 보세요" in ko,
        "A 초안이 있으면 그 글이 한국어 절 맨 앞", repr(out[:300]) + err[-300:])
    chk("#### 그 밖의 고침" in ko and "- 저장 오류 고침" in ko and "- 해시태그 수정 창" in ko
        and "- 시작이 빨라짐" in ko, "A '그 밖의 고침' 에 feat·fix·perf 제목 한 줄씩", repr(ko[-400:]))
    chk("본문 항목은 빠진다" not in ko and "본문 둘" not in ko and "SOT 문서 손질" not in ko
        and "검사 더함" not in ko and "릴리스 설명 초안" not in ko and "Co-Authored-By" not in ko
        and "(1, 1.0.1)" not in ko, "A 본문·docs·test 커밋·작업 번호는 빠진다", repr(ko[-400:]))
    chk("## 바뀐 내용" not in out and "/compare/v1.0.0...v1.0.1" in ko, "A 종전 절 머리 없음·비교 링크 남음")
    chk(en.startswith("#### What's new") and "#### Other fixes" in en and "- Saving works again" in en
        and "해시태그" not in en and "/compare/v1.0.0...v1.0.1" in en, "B 영어 절 — 초안 + 꼬리말 '그 밖의 고침'",
        repr(en[-300:]))

    # ── C ──
    own = DRAFT.replace("#### 이렇게 써 보세요", "#### 그 밖의 고침\n- 손으로 쓴 줄\n\n#### 이렇게 써 보세요")
    repo = make_repo(own)
    out_c, _ = notes_for(repo)
    shutil.rmtree(repo, ignore_errors=True)
    ko_c = split_lang_sections(out_c).get("ko", "")
    chk(ko_c.count("#### 그 밖의 고침") == 1 and "손으로 쓴 줄" in ko_c and "- 저장 오류 고침" not in ko_c,
        "C 초안의 '그 밖의 고침' 을 그대로 두고 다시 붙이지 않는다", repr(ko_c[-300:]))

    # ── D ──
    repo = make_repo(None)
    out_d, _ = notes_for(repo)
    shutil.rmtree(repo, ignore_errors=True)
    chk(out_d.startswith("<!-- lang:ko -->\n## 바뀐 내용") and "본문 항목은 빠진다" in out_d,
        "D 초안이 없으면 종전 꼴(커밋 메시지·본문 항목)", repr(out_d[:200]))

    # ── E — 실제 창이 쓰는 길 ──
    for chain, want, not_want in ((["ko"], ("이번 판에서 달라진 점", "해시태그 수정", "이렇게 써 보세요", "그 밖의 고침",
                                           "저장 오류 고침", "v1.0.1"), ("What's new",)),
                                  (["en", "ko"], ("What's new", "Edit hashtags", "Try it", "Other fixes",
                                                 "Saving works again"), ("해시태그", "한국어로만"))):
        tb = QTextBrowser()
        tb.setMarkdown(changes_markdown([{"version": "1.0.1", "notes": out}], chain=chain))
        shown = tb.toPlainText()
        heads = [ln for ln in shown.splitlines() if ln.lstrip().startswith("#")]
        chk(all(s in shown for s in want) and not any(s in shown for s in not_want) and not heads
            and "<!--" not in shown, "E 업데이트 창(%s)에 제목·글이 보이고 '#' 가 남지 않는다" % chain[0],
            repr(shown[:300]))

    # ── F ──
    import release_notes as rn
    errs, warns = rn.check_draft(DRAFT)
    chk(not errs and not warns, "F 좋은 초안은 오류·경고 없음", str(errs + warns))
    ko_only = DRAFT.split("<!-- lang:en -->")[0]
    chk(any("en" in e for e in rn.check_draft(ko_only)[0]), "F 영어 절이 없으면 오류")
    chk(rn.check_draft(DRAFT.replace("#### 이번 판", "### 이번 판"))[0], "F '###' 제목은 오류(버전 제목과 같은 크기)")
    chk(rn.check_draft(DRAFT.replace("#### 이렇게 써 보세요", "<details><summary>더 보기</summary>\n\n#### 이렇게 써 보세요"))[0],
        "F HTML 접기는 오류(앱 창에 글자로 보인다)")
    chk(rn.check_draft(DRAFT.replace("- 파일 탭", "- test_tags_261113 통과 · 파일 탭"))[0], "F 내부 시험 낱말은 오류")
    chk(not rn.check_draft(DRAFT.replace("- 파일 탭", "- `<태그>` 표기 · 파일 탭"))[0], "F 코드 표기 안의 꺾쇠는 괜찮다")
    many = DRAFT.replace("- **클립보드 복사**", "\n".join("- 항목 %d" % i for i in range(5)) + "\n- **클립보드 복사**", 1)
    e7, w7 = rn.check_draft(many)
    chk(not e7 and w7, "F 주요 항목 3~6 밖이면 경고(오류 아님)", str(e7 + w7))
    chk(rn.check_draft(DRAFT.replace("#### 이번 판에서 달라진 점", "#### 다른 제목"))[0], "F '이번 판에서 달라진 점' 이 없으면 오류")
    tmp = tempfile.mkdtemp(prefix="polypdf_relnotes_chk_")
    bad = os.path.join(tmp, "bad.md")
    with open(bad, "w", encoding="utf-8") as f:
        f.write(ko_only)
    rc = subprocess.run([sys.executable, SCRIPT, "--check", bad], capture_output=True, text=True,
                        encoding="utf-8").returncode
    shutil.rmtree(tmp, ignore_errors=True)
    chk(rc == 1, "F --check 는 오류가 있으면 종료 코드 1", str(rc))

    # ── G ──
    drafts = glob.glob(os.path.join(HERE, "release_notes", "*.md"))
    bad_drafts = []
    for p in drafts:
        with open(p, encoding="utf-8") as f:
            e, _w = rn.check_draft(f.read())
        if e:
            bad_drafts.append((os.path.basename(p), e))
    chk(not bad_drafts, "G 저장소의 초안 %d개가 --check 통과" % len(drafts), str(bad_drafts))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("exception")

print("FAILS:", len(fails))
sys.exit(1 if fails else 0)
