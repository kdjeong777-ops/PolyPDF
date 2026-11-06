# -*- coding: utf-8 -*-
"""사진 모드 — PDF 전용 명령은 회색으로 남기지 않고 숨긴다 (사진 보기 SOT §4.13, 261106-4 사용자 결정 '모두 숨김').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드 — 대상 명령이 액션·리본 줄(모음 포함)·메뉴 어디에도 보이지 않는다(꺼짐도 그대로 — 단축키도 안 듣는다)
B. 사진 모드 — 리본 어느 줄에도 회색(꺼진) 단추가 남지 않고, 그림 표시만 남은 묶음·빈 묶음이 없다
C. PDF 모드로 오면 그대로 다시 보이고 켜진다(키·언어 판정은 종전대로)
D. 보기 탭 키(단어장·검색)는 사진 모드에서 아무 일도 하지 않는다
E. 숨은 채 권한 적용이 다시 켜도 꺼진 채 — 다시 보여도 회색(끄기를 숨기기보다 먼저, 숨은 것도 늘 다시 끈다)
수정 전 코드(서명만 숨김)로 A·B 4개 실패, E 는 숨김 순서 고침 전 코드로 1개 실패.
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_hide_cmds_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 PDF 전용 숨김", echo=False)   # 마스터 §14.7.2 의 6
fails = []

# 사용자 결정 때 보고한 목록(261106-4) + 목록 밖에서 함께 숨긴 '검색' 보기 · 261106-1 전자서명
TARGETS = ("file.save_as", "fav.recent_searches", "fav.searches", "fav.add_search", "view.study", "view.search",
           "tools.build_study", "tools.bookmarker", "tools.study_and_bookmarks", "tools.autotag", "tools.reindex",
           "tools.merge", "tools.nup", "tools.encrypt", "tools.sign", "tools.translate")
KEY_GATED = ("tools.translate",)                    # PDF 모드에서도 키가 없으면 숨는다(_gate_api_dependent_ui)


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(t=0.4):
    e = time.monotonic() + t
    while time.monotonic() < e:
        app.processEvents()
        time.sleep(0.01)


try:
    from viewer.app import MainWindow
    from viewer.widgets.ribbon import cmd_id
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind(); pump()
    rb = mw._ribbon

    def row_widgets(a):
        out = []
        for k in rb.keys():
            r = rb.row(k)
            w = r.widgetForAction(a) if r is not None else None
            if w is not None and a.isVisible() and w.isVisibleTo(r):
                out.append(k)
        return out

    def in_menus(a):
        seen = []
        for m in mw.findChildren(QMenu):
            if a in m.actions() and a.isVisible():
                seen.append(m.title() or m.objectName() or "?")
        return seen

    pdf_vis = {c: mw._cmds[c].isVisible() for c in TARGETS if c in mw._cmds}
    chk(all(pdf_vis.get(c) for c in TARGETS if c not in KEY_GATED), "PDF 모드 — 대상 명령이 보인다(검사 전제)",
        str([c for c, v in pdf_vis.items() if not v]))

    # A
    mw._set_photo_mode(True); pump(1.0)
    vis = [c for c in TARGETS if c in mw._cmds and mw._cmds[c].isVisible()]
    chk(not vis, "A 사진 모드 — 대상 명령이 하나도 보이지 않는다(회색이 아니라 숨김)", str(vis))
    on = [c for c in TARGETS if c in mw._cmds and mw._cmds[c].isEnabled()]
    chk(not on, "A 사진 모드 — 대상 명령은 꺼져도 있다(단축키가 듣지 않는다)", str(on))
    rows = {c: row_widgets(mw._cmds[c]) for c in TARGETS if c in mw._cmds}
    chk(not any(rows.values()), "A 리본 줄(모음·탭)에 대상 단추가 없다", str({c: v for c, v in rows.items() if v}))
    menus = {c: in_menus(mw._cmds[c]) for c in TARGETS if c in mw._cmds}
    chk(not any(menus.values()), "A 메뉴(▾ 펼침)에도 없다", str({c: v for c, v in menus.items() if v}))

    def groups_of(r):
        """보이는 구분선으로 나뉜 보이는 항목(액션 기준 — 고르지 않은 탭의 줄은 화면에 없어도 본다)."""
        gs, cur = [], []
        for a in r.actions():
            if a.isSeparator():
                if a.isVisible() and cur:
                    gs.append(cur); cur = []
                continue
            w = r.widgetForAction(a)
            if w is None or w.property("ribbonSpacer") or not a.isVisible():
                continue
            cur.append(a)
        if cur:
            gs.append(cur)
        return gs

    # B
    grey, lone = [], []
    for k in rb.keys():
        r = rb.row(k)
        for a in r.actions():
            if a.isSeparator() or not a.isVisible():
                continue
            w = r.widgetForAction(a)
            if w is None or w.property("ribbonSpacer") or a.property("ribbonMark"):
                continue
            if not a.isEnabled():
                grey.append("%s:%s" % (k, cmd_id(a) or a.text()))
        for g in groups_of(r):
            if all(a.property("ribbonMark") for a in g):
                lone.append(k)
    chk(not grey, "B 사진 모드 — 리본 어느 줄에도 회색 단추가 없다", str(grey))
    chk(not lone, "B 그림 표시만 남은 묶음이 없다", str(lone))
    chk(all(groups_of(rb.row(k)) for k in rb.keys()), "B 빈 줄이 없다",
        str([k for k in rb.keys() if not groups_of(rb.row(k))]))

    # D
    va = getattr(mw, "_view_acts", {}) or {}
    hit = []
    for vid in ("study", "search"):
        a = va.get(vid)
        if a is not None:
            n = [0]
            a.triggered.connect(lambda *_x, n=n: n.__setitem__(0, n[0] + 1))
            mw._view_key(vid)
            if n[0]:
                hit.append(vid)
    chk(not hit, "D 사진 모드 — 보기 탭 키(단어장·검색)가 아무 일도 하지 않는다", str(hit))

    # E — 숨은 채 권한 적용이 다시 켜도(setEnabled(True)) 꺼진 채 — Qt 는 숨은 액션의 켜짐 값을 기억해 보일 때 켜진 채로 낸다
    mrg = mw._cmds["tools.merge"]
    mrg.setEnabled(True)                               # 권한 적용(_apply_permissions 의 병합 줄)이 하는 일
    mw._photo_gate_actions()
    mrg.setVisible(True)
    chk(not mrg.isEnabled(), "E 사진 모드 — 숨은 명령을 권한 적용이 다시 켜도 꺼진 채(다시 보여도 회색)")
    mw._photo_gate_actions()
    chk(not mrg.isVisible(), "E 끄는 길을 다시 타면 다시 숨는다")

    # C
    mw._set_photo_mode(False); pump(1.0)
    back = [c for c in TARGETS if c not in KEY_GATED and c in mw._cmds
            and not (mw._cmds[c].isVisible() and mw._cmds[c].isEnabled())]
    chk(not back, "C PDF 모드로 오면 그대로 보이고 켜진다", str(back))
    chk(all(mw._cmds[c].isVisible() == pdf_vis[c] for c in KEY_GATED if c in pdf_vis),
        "C 키로 가리는 명령(번역)은 PDF 모드의 종전 판정 그대로")
    chk(not mw.__dict__.get("_photo_hidden"), "C 숨긴 기억이 비었다")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
