# -*- coding: utf-8 -*-
"""261107-17(사용자 지시·결정) 사전 고르기를 환경설정 '고급 › 사전' 으로 — 단어장 SOT §11.1, 디자인 SOT §2.14·§2.9.1.

실제 창(MainWindow)과 실제 환경설정 창(SettingsDialog)으로 누른다. 사전은 시험 프로필의 진짜 dict.db.
A. 목록 자리 — '사전' 은 '고급' 의 '외부 연결' 바로 아래 · 인터넷 사전 키 묶음은 사전 쪽, 법령·KCSC·특허는 외부 연결 쪽
B. 한국 전용 — 한국어 화면이 아니면 '사전' 항목을 숨긴다(외부 연결과 같은 규칙)
C. [취소] — 기본 선택·우선순위(▲▼)·스타일을 바꾼 뒤 [취소] 하면 dict.db·settings 그대로
D. [적용] — 기본 선택·우선순위가 dict.db 에, 스타일이 settings 에 · 이 PDF 의 선택(dict_file_off)은 건드리지 않는다
E. 바로 실행 — [사전 지우기] 는 누르면 바로(창을 [취소] 해도 지운 그대로)
F. 도구 탭에 '사전 관리' 단추가 없다(명령 id tools.dict 없음)
G. 단어장 창 '이 PDF 사전' — 누르면 이 PDF 의 사전 창, 닫으면 이 PDF 의 선택으로 저장
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths, QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더(dict.db·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_dict_settings_%d" % os.getpid())
import modal_guard                    # 모달이 떠서 검사가 멈추지 않게(마스터 §14.7.2 의 6) — 창 안을 누르는 검사라 exec 는 그대로
guard = modal_guard.install(label=lambda: "검사", dialogs=False)
fails = []


def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra if not c else "")
    if not c:
        fails.append(m)


QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
root = Path(tempfile.mkdtemp(prefix="polypdf_dictsettings_"))
pdf = str(root / "a.pdf")
Path(pdf).write_bytes(b"%PDF-1.4\n%%EOF\n")

from viewer.app import MainWindow
from viewer.widgets import settings_dialog as sd
mw = MainWindow(); mw.show(); app.processEvents()
dic = mw._study_get_dict()
for sid, name in (("g1", "도로 용어집 시험"), ("g2", "건설 용어집 시험")):
    dic.add_source(sid, name, kind="base", priority=5)
dic.add_entry(source_id="g1", term_ko="포장시험어zq", def_ko="도로 포장")
dic.add_entry(source_id="g2", term_ko="골재시험어zq", def_ko="모래·자갈")


def enabled():
    return {s["source_id"]: bool(s["enabled"]) for s in mw._study_get_dict().list_sources()}


def order():
    return [s["source_id"] for s in mw._study_get_dict().list_sources()]


def open_dlg():
    d = sd.SettingsDialog(mw._prefs, mw, host=mw, page="dict")
    d.show(); QTest.qWait(10)
    return d


def select(lst, sids):
    lst.clearSelection()
    for i in range(lst.count()):
        it = lst.item(i)
        if it.data(Qt.ItemDataRole.UserRole) in sids:
            it.setSelected(True); lst.setCurrentItem(it)


# ---- A 자리 ----
d = open_dlg()
pids = [d.nav.item(i).data(sd.PAGE_ROLE) for i in range(d.nav.count()) if d.nav.item(i).data(sd.PAGE_ROLE)]
chk("dict" in pids and pids.index("dict") == pids.index("external") + 1, "A1 '사전' 은 '외부 연결' 바로 아래", str(pids))
chk(d.current_page() == "dict" and not d._page_items["dict"].isHidden(), "A2 open_settings(page='dict') 로 그 항목이 열린다")
chk(d._scrolls["dict"].widget().isAncestorOf(d.adv.grp_online_dict)
    and d._scrolls["external"].widget().isAncestorOf(d.adv.grp_law),
    "A3 인터넷 사전 키는 사전 쪽, 법령·KCSC·특허는 외부 연결 쪽")
p = getattr(d, "dict_panel", None)
chk(p is not None and d._scrolls["dict"].widget().isAncestorOf(p) and p.grp_run is not None,
    "A4 사전 쪽에 기본 선택 판과 바로 실행 묶음")
d.reject()

# ---- B 한국 전용 ----
_orig = sd.korea_only_visible
sd.korea_only_visible = lambda: False
d = sd.SettingsDialog(mw._prefs, mw, host=mw)
chk(d._page_items["dict"].isHidden() and d._page_items["external"].isHidden(), "B1 한국어 화면이 아니면 '사전' 항목을 숨긴다")
d.reject()
sd.korea_only_visible = _orig

# ---- C [취소] ----
en0, ord0, st0 = enabled(), order(), list(mw._prefs.get("dict_styles") or [])
d = open_dlg(); p = d.dict_panel
QTest.mouseClick(p.btn_remove_all, Qt.MouseButton.LeftButton)
select(p.lst_wait, {"g2"}); QTest.mouseClick(p.btn_add, Qt.MouseButton.LeftButton)
select(p.lst_wait, {"g1"}); QTest.mouseClick(p.btn_add, Qt.MouseButton.LeftButton)
select(p.lst_use, {"g1"}); QTest.mouseClick(p.btn_up, Qt.MouseButton.LeftButton)
QInputDialog.getText = staticmethod(lambda *a, **k: ("시험 스타일", True))
QTest.mouseClick(p.btn_style_save, Qt.MouseButton.LeftButton)
chk(d.btn_apply.isEnabled(), "C1 바꾸면 [적용] 이 켜진다")
d.reject()
chk(enabled() == en0 and order() == ord0, "C2 [취소] — 기본 선택·우선순위가 그대로", str(enabled()))
chk(list(mw._prefs.get("dict_styles") or []) == st0, "C3 [취소] — 스타일도 저장하지 않는다")

# ---- D [적용] ----
from viewer.pathutil import norm_key
mw._study_pdf = Path(pdf)
key = norm_key(mw._study_pdf)
mw._prefs["dict_file_off"] = {key: ["g2"]}
d = open_dlg(); p = d.dict_panel
select(p.lst_use, {"g2"}); QTest.mouseClick(p.btn_remove, Qt.MouseButton.LeftButton)
nxt = p.use_ids()[p.use_ids().index("g1") + 1]          # 같은 종류(기본 사전) 이웃 — 사용자 사전은 종류로 늘 맨 앞이다
select(p.lst_use, {"g1"}); QTest.mouseClick(p.btn_dn, Qt.MouseButton.LeftButton)
QTest.mouseClick(p.btn_style_save, Qt.MouseButton.LeftButton)
QTest.mouseClick(d.btn_apply, Qt.MouseButton.LeftButton)
e = enabled()
chk(e.get("g2") is False and e.get("g1") is True, "D1 [적용] — 기본 선택이 dict.db 에", str({k: e.get(k) for k in ("g1", "g2")}))
o = order()
chk(ord0.index("g1") < ord0.index(nxt) and o.index("g1") > o.index(nxt), "D2 [적용] — ▼ 우선순위가 dict.db 에", f"{ord0[:4]} → {o[:4]}")
chk([s["name"] for s in mw._prefs.get("dict_styles") or []] == ["시험 스타일"], "D3 [적용] — 스타일이 settings 에")
chk(mw._prefs.get("dict_file_off") == {key: ["g2"]}, "D4 이 PDF 의 선택은 그대로", str(mw._prefs.get("dict_file_off")))
chk("dict_default" not in mw._prefs, "D5 결과 키 dict_default 는 settings.json 에 넣지 않는다")
d.reject()
mw._prefs["dict_file_off"] = {}
mw._apply_dict_default([s for s in order()], order())        # 다시 모두 켬

# ---- E 바로 실행 ----
d = open_dlg(); p = d.dict_panel
select(p.lst_use, {"g2"})
QTest.mouseClick(p.btn_delete, Qt.MouseButton.LeftButton)
d.reject()
chk("g2" not in enabled(), "E1 [사전 지우기] 는 누르면 바로 — [취소] 해도 지운 그대로")

# ---- F 도구 탭 ----
from viewer.widgets.ribbon import cmd_id
chk("tools.dict" not in mw._cmds, "F1 명령 id tools.dict 없음")
row = [a.text() for a in mw._ribbon.row("tools").actions() if cmd_id(a)]
chk(not [t for t in row if "사전 관리" in t], "F2 도구 탭 줄에 '사전 관리' 단추 없음", str(row))

# ---- G 단어장 창 '이 PDF 사전' ----
sp = mw.study_panel
btn = getattr(sp, "btn_file_dict", None)
chk(btn is not None and btn.text() == "이 PDF 사전", "G1 단어장 창에 '이 PDF 사전' 단추")
seen = []


def drive():
    dlg = getattr(mw, "_dict_file_dialog", None)
    if dlg is None or not dlg.isVisible():
        QTimer.singleShot(30, drive)
        return
    seen.append(dlg.windowTitle())
    select(dlg.lst_use, {"g1"})
    QTest.mouseClick(dlg.btn_remove, Qt.MouseButton.LeftButton)
    dlg.reject()                                   # 창 X 와 같은 길 — 그래도 저장


QTimer.singleShot(30, drive)
if btn is not None:
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
chk(seen == ["이 PDF 의 사전"], "G2 누르면 '이 PDF 의 사전' 창", str(seen))
chk("g1" in (mw._prefs.get("dict_file_off") or {}).get(key, []), "G3 닫으면 이 PDF 의 선택으로 저장(g1 꺼짐)",
    str(mw._prefs.get("dict_file_off")))
chk(enabled().get("g1") is True, "G4 기본 선택은 그대로")

mw._skip_save_on_close = True
mw.close()
print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
