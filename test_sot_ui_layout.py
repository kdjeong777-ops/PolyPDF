# -*- coding: utf-8 -*-
"""261025-9(SOT 점검 개선안 2): 디자인 SOT §2.9 의 탭 표가 **실제 창의 자리**와 같다 — 자리는 `ui_layout` 이 실제 `MainWindow` 에서 읽는다.

종전에는 검사마다 단추 글자 목록을 손으로 적었고, SOT 표는 사람이 맞췄다. 자리를 옮기면 SOT 표·검사 기대가 따로 낡았다
(261025-1 뒤 검사 실패 2건, SOT 표 번호 어긋남). 이제 원본은 코드 하나, SOT 표는 이 검사가 그 원본과 대조한다.

A. `모음` 탭 — 디자인 SOT §2.9 표의 명령 id·그룹 = 실제 모음 줄(기본값, 키·한국어로 모두 보일 때)
B. `즐겨찾기` 탭 — §2.9.5 표의 명령 id 차례·구분선 = 실제 줄(등록 항목이 없을 때 — 개별 단추 없음)
C. `보기` 탭 — §2.9.5 '보기 탭' 표의 그룹별 단추 이름 = 실제 줄
D. `ui_layout.where` — 하위 메뉴(▾) 안 명령도 찾는다(`tools.vprinter` → `등록·설치` 안)
SOT 문서가 없으면(공개 저장소 단독) 건너뛴다.
"""
import os, re, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
SOT_DIR = Path(os.environ.get("POLYPDF_SOT_DIR") or ROOT.parent)
DESIGN = SOT_DIR / "화면 디자인 작업 계획서.md"
if not DESIGN.exists():
    print("SKIP — SOT 문서가 없다(공개 저장소 단독)")
    sys.stdout.flush(); os._exit(0)

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def table_after(text: str, marker: str) -> list:
    """marker 다음 첫 표의 행(머리·구분선 뺌)."""
    i = text.find(marker)
    if i < 0:
        return []
    rows, started = [], False
    for l in text[i:].splitlines()[1:]:
        if l.startswith("|"):
            started = True
            rows.append(l)
        elif started:
            break
    return [r for r in rows[2:]]


dz = DESIGN.read_text(encoding="utf-8")

# 문서 쪽
doc_col = []                                       # A: [[id…]…] — 그룹 열이 바뀌면 새 묶음
last = None
for r in table_after(dz, "**`모음` 탭**"):
    c = [x.strip() for x in r.strip("|").split("|")]
    m = re.match(r"^`([a-z0-9_.]+)`$", c[3]) if len(c) > 3 else None
    if m:
        if c[1] != last:
            doc_col.append([]); last = c[1]
        doc_col[-1].append(m.group(1))
doc_fav = [[]]                                     # B: '─ 구분선' 행이 묶음 경계, '—' 은 개별 단추(항목이 없으면 없다)
for r in table_after(dz, "**`즐겨찾기` 탭**"):
    c = [x.strip() for x in r.strip("|").split("|")]
    if c[0].startswith("─"):
        doc_fav.append([])
        continue
    m = re.match(r"^`([a-z0-9_.]+)`$", c[-1])
    if m:
        doc_fav[-1].append(m.group(1))
doc_fav = [g for g in doc_fav if g]
doc_view = []                                      # C: 그룹별 단추 이름 — 괄호 안 설명(종전 이름)은 뺀다
for r in table_after(dz, "**`보기` 탭**"):
    c = [x.strip() for x in r.strip("|").split("|")]
    if len(c) > 1:
        doc_view.append(re.findall(r"`([^`]+)`", re.sub(r"\([^)]*\)", "", c[1])))

try:
    from viewer.app import MainWindow
    from viewer.widgets.ribbon import DEFAULT_COLLECTION, SEP
    from ui_layout import layout, where
    mw = MainWindow()
    mw.resize(1600, 900); mw.show(); QTest.qWait(150)
    mw._favorites = []
    mw._law_favorites, mw._kcsc_favorites, mw._kipo_favorites = [{"name": "도로법", "kind_label": "법률"}], [], []
    mw._prefs.update({"law_oc": "x", "kcsc_key": "y", "kipo_signkey": "z", "anthropic_api_key": "k"})   # 키 게이팅으로 숨는 것 없이
    mw._gate_api_dependent_ui(mw._prefs); QTest.qWait(80)
    lay = layout(mw)

    code_col, cur = [], []
    for x in DEFAULT_COLLECTION:
        if x == SEP:
            code_col.append(cur); cur = []
        else:
            cur.append(x)
    code_col.append(cur)
    chk(bool(doc_col) and doc_col == code_col, "A 디자인 SOT §2.9 모음 표 = DEFAULT_COLLECTION", "문서 %s / 코드 %s" % (doc_col, code_col))
    live_col = lay.get("collection")
    chk(live_col == code_col, "A 실제 모음 줄 = DEFAULT_COLLECTION(시험 모드 새 설정)", str(live_col))

    live_fav = [[x for x in g if not x.startswith("item:")] for g in lay.get("fav", [])]
    live_fav = [g for g in live_fav if g]
    chk(bool(doc_fav) and doc_fav == live_fav, "B 디자인 SOT §2.9.5 즐겨찾기 표 = 실제 줄", "문서 %s / 실제 %s" % (doc_fav, live_fav))

    live_view = [[mw._cmds[x].iconText() if x in mw._cmds else x for x in g] for g in lay.get("view", [])]
    chk(bool(doc_view) and doc_view == live_view, "C 디자인 SOT §2.9.5 보기 탭 표 = 실제 줄", "문서 %s / 실제 %s" % (doc_view, live_view))

    w = where(mw, "tools.vprinter")
    chk(bool(w) and w[0] == "tools" and len(w) == 4 and w[3] == "tools.install", "D where — ▾ 안 명령은 그 ▾ 의 자리와 함께", str(w))
    chk(where(mw, "view.law")[:1] == ("view",), "D where — 보기 탭 명령", str(where(mw, "view.law")))
    mw.close()
except Exception as e:
    import traceback; traceback.print_exc()
    fails.append("예외: %r" % e)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
