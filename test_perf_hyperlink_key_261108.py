# -*- coding: utf-8 -*-
"""쪽이 바뀔 때 하이퍼링크 키를 만들며 PDF 파일 자체를 열지 않는다 (261108-10, 응답성 SOT §6).

beta.7 설치 시험 T3(598쪽) 첫 쪽 표시가 1.24초 섰다 — 메인 `_on_pane_page_changed` → `links_for` →
`HyperlinkStore._rel_key` → `Path(pdf).resolve()` → Windows `realpath` 가 막 연 PDF 의 핸들을 두 번 열었다
(`_getfinalpathname`). 고친 뒤: 폴더만 풀고(폴더마다 한 번) 파일 이름은 그대로 붙인다.

F. 처음 보는 PDF 로 `links_for` 를 쪽마다 불러도 `_getfinalpathname` 이 그 파일 경로로 불리지 않는다(수정 전: 2번)
   · 같은 폴더의 다른 파일 20개를 처음 물어도 폴더 풀기는 폴더 수만큼(파일 수가 아니다)
   · 쪽 꾸밈 저장소(`PageMetaStore` — 회전·자르기)도 같은 키 함수(`pathutil.rel_key`)라 파일을 열지 않는다
K. 키는 종전과 같다 — 기준 폴더 기준 상대 경로('/'), 하위 폴더 파일·폴더 밖 파일(None)
C. 저장된 키와 대소문자만 다른 경로로 물어도 저장된 링크를 찾는다(종전 `resolve` 는 디스크 대소문자로 맞췄다)
R. 이름 바꾸기(`rename_file`) — 옛 경로가 이미 없어도 링크가 새 키로 옮겨 간다(책갈피창·저장 SOT §4.7.14)
"""
import ntpath, os, shutil, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # 검사 작성 SOT §14.7
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3

from viewer.hyperlinks import HyperlinkStore
from viewer.page_meta import PageMetaStore

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


calls = []
_orig = ntpath._getfinalpathname


def _spy(p):
    calls.append(str(p))
    return _orig(p)


def opened(path) -> int:
    n = os.path.normcase(os.path.abspath(str(path)))
    return sum(1 for c in calls if os.path.normcase(c.replace("\\\\?\\", "")) == n)


tmp = tempfile.mkdtemp(prefix="polypdf_hlkey_")
base = os.path.join(tmp, "Base")
sub = os.path.join(base, "Sub")
os.makedirs(sub)
pdf = os.path.join(base, "Doc.pdf")
others = [os.path.join(base, "f%02d.pdf" % i) for i in range(20)]
for p in [pdf, os.path.join(sub, "In.pdf")] + others:
    with open(p, "wb") as fh:
        fh.write(b"%PDF-1.4\n%%EOF\n")

ntpath._getfinalpathname = _spy
try:
    # F
    st = HyperlinkStore(base)
    calls.clear()
    for pg in range(30):
        st.links_for(pdf, pg)
    chk(opened(pdf) == 0, "F 쪽 30번 links_for 동안 PDF 파일을 열지 않는다", "%d번" % opened(pdf))
    calls.clear()
    for p in others:
        st.links_for(p, 0)
    n_file = sum(opened(p) for p in others)
    chk(n_file == 0, "F 처음 묻는 파일 20개도 파일 자체를 열지 않는다", "%d번" % n_file)
    chk(len(calls) <= 4, "F 폴더 풀기는 폴더 수만큼(파일 수가 아니다)", "_getfinalpathname %d번" % len(calls))
    # 쪽 꾸밈(숨김·회전·자르기) 저장소도 같은 키 함수 — 문서를 열 때 메인에서 묻는다
    pm = PageMetaStore(base)
    calls.clear()
    for pg in range(30):
        pm.get_rotation(pdf, pg)
        pm.get_crop(pdf, pg)
    chk(opened(pdf) == 0, "F PageMetaStore 도 쪽 30번 묻는 동안 PDF 파일을 열지 않는다", "%d번" % opened(pdf))
finally:
    ntpath._getfinalpathname = _orig

# K
st = HyperlinkStore(base)
chk(st._rel_key(pdf) == "Doc.pdf", "K 기준 폴더 파일 키", str(st._rel_key(pdf)))
chk(st._rel_key(os.path.join(sub, "In.pdf")) == "Sub/In.pdf", "K 하위 폴더 키 '/'", str(st._rel_key(os.path.join(sub, "In.pdf"))))
chk(st._rel_key(os.path.join(tmp, "out.pdf")) is None, "K 폴더 밖 파일은 None")

# C
ok_add = st.add_url_link(pdf, 0, "site", "https://www.youtube.com/watch?v=x")
chk(ok_add[0], "C 링크 넣기", str(ok_add))
st.save()
st2 = HyperlinkStore(base)
got = st2.links_for(os.path.join(base, "DOC.PDF"), 0)
chk(len(got) == 1 and got[0].get("name") == "site", "C 대소문자만 다른 경로로도 저장된 링크", str(got))

# R
new = os.path.join(base, "Renamed.pdf")
os.replace(pdf, new)
st3 = HyperlinkStore(base)
moved = st3.rename_file(pdf, new)
chk(moved and len(st3.links_for(new, 0)) == 1 and not st3.links_for(pdf, 0), "R 이름 바꾼 뒤 링크가 새 키로", str(st3._data))

shutil.rmtree(tmp, ignore_errors=True)
print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
