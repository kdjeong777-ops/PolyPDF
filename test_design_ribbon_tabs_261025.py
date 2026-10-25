# -*- coding: utf-8 -*-
"""261025-1·-2(사용자 지시·결정): 보기 탭 차례·Ctrl+Shift+1~9(입력 SOT §3.2.1), 도구 '등록·설치', 설정창 '고급 설정'(디자인 SOT §2.14).

A. 보기 탭 세부 줄 차례: 1단·2단·텍스트·단어장·검색·스크린샷 | 법령·고시·특허·건설기준 | 발표보기, 이름 '법령·고시'
B. 실제 키 입력: Ctrl+Shift+1 → 1단(2단 끔·오른쪽 창 숨김), Ctrl+Shift+2 → 2단 **으로만**(두 번 눌러도 2단),
   Ctrl+Shift+3/5/6 → 텍스트·검색·스크린샷, 키가 없는 법령(Ctrl+Shift+7)은 아무 일도 하지 않는다 · 키가 있으면 연다
C. 항목 오른쪽 칸에 각자 키(상태와 무관)
D. 도구 탭: '등록·설치' ▾ 하나(종전 세 단추 없음)
E. 환경설정 창에 API 키 칸이 없고 '고급 설정...' 단추 — 눌러 [확인] 하면 곧바로 저장·게이팅, 환경설정 [취소] 해도 남는다
"""
import os, sys, faulthandler, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from PyQt6.QtCore import QStandardPaths, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


CS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
try:
    from viewer.app import MainWindow
    mw = MainWindow()
    mw.resize(1600, 900); mw.show(); mw.activateWindow(); QTest.qWait(200)
    mw._prefs.update({"law_oc": "", "kcsc_key": "", "kipo_signkey": ""})
    mw._gate_api_dependent_ui(mw._prefs); QTest.qWait(50)

    # A
    mw._ribbon.select("view"); QTest.qWait(50)
    row = mw._ribbon.row("view")
    names = [a.iconText() for a in row.actions() if not a.isSeparator() and row.widgetForAction(a)
             and not row.widgetForAction(a).property("ribbonSpacer")]
    chk(names == ["1단", "2단", "텍스트", "단어장", "검색", "스크린샷", "법령·고시", "특허", "건설기준", "발표보기"],
        "A 보기 탭 차례·이름", str(names))
    mw._prefs.update({"law_oc": "x", "kcsc_key": "y", "kipo_signkey": "z"})
    mw._gate_api_dependent_ui(mw._prefs); QTest.qWait(50)
    chk([[b.text() for b in g] for g in row.groups()] ==
        [["1단", "2단", "텍스트", "단어장", "검색", "스크린샷"], ["법령·고시", "특허", "건설기준"], ["발표보기"]],
        "A 구분선 둘(법령 앞·발표 앞)", str([[b.text() for b in g] for g in row.groups()]))
    mw._prefs.update({"law_oc": "", "kcsc_key": "", "kipo_signkey": ""})
    mw._gate_api_dependent_ui(mw._prefs); QTest.qWait(50)

    # B 실제 키
    tgt = mw.main_view.view if hasattr(mw.main_view, "view") else mw
    QTest.keyClick(tgt, Qt.Key.Key_2, CS); QTest.qWait(150)
    chk(mw.act_split.isChecked(), "B Ctrl+Shift+2 → 2단")
    QTest.keyClick(tgt, Qt.Key.Key_2, CS); QTest.qWait(150)
    chk(mw.act_split.isChecked(), "B Ctrl+Shift+2 를 또 눌러도 2단(바꾸기가 아니다)")
    QTest.keyClick(tgt, Qt.Key.Key_1, CS); QTest.qWait(150)
    chk(not mw.act_split.isChecked() and not mw.act_toggle_search.isChecked() and not mw.act_toggle_shot.isChecked(),
        "B Ctrl+Shift+1 → 1단(오른쪽 창 숨김)")
    QTest.keyClick(tgt, Qt.Key.Key_3, CS); QTest.qWait(100)
    chk(mw.act_toggle_search.isChecked() and mw.search_tabs.currentWidget() is mw.text_panel, "B Ctrl+Shift+3 → 텍스트")
    QTest.keyClick(tgt, Qt.Key.Key_5, CS); QTest.qWait(100)
    chk(mw.search_tabs.currentWidget() is mw.search_area, "B Ctrl+Shift+5 → 검색")
    QTest.keyClick(tgt, Qt.Key.Key_6, CS); QTest.qWait(100)
    chk(mw.act_toggle_shot.isChecked() and not mw.act_toggle_search.isChecked(), "B Ctrl+Shift+6 → 스크린샷")
    called = []
    orig = mw._action_law_search
    mw._view_acts["law"].triggered.disconnect()
    mw._view_acts["law"].triggered.connect(lambda *_: called.append("law"))
    QTest.keyClick(tgt, Qt.Key.Key_7, CS); QTest.qWait(100)
    chk(not called, "B 키가 없는(숨긴) 법령은 Ctrl+Shift+7 로 열리지 않는다", str(called))
    mw._prefs.update({"law_oc": "x"}); mw._gate_api_dependent_ui(mw._prefs)
    QTest.keyClick(tgt, Qt.Key.Key_7, CS); QTest.qWait(100)
    chk(called == ["law"], "B 키가 있으면 Ctrl+Shift+7 → 법령·고시", str(called))

    # C
    va = mw._view_acts
    keys = {k: va[k].text().split("\t")[-1] if "\t" in va[k].text() else "" for k in va}
    want = {"single": "Ctrl+Shift+1", "split": "Ctrl+Shift+2", "text": "Ctrl+Shift+3", "study": "Ctrl+Shift+4",
            "search": "Ctrl+Shift+5", "shot": "Ctrl+Shift+6", "law": "Ctrl+Shift+7", "kipo": "Ctrl+Shift+8",
            "kcsc": "Ctrl+Shift+9", "present": "F5"}
    chk(keys == want, "C 보기 항목 오른쪽 칸에 각자 키", str(keys))

    # D
    mw._ribbon.select("tools"); QTest.qWait(50)
    trow = mw._ribbon.row("tools")                        # 폭이 모자라면 넘침(») 안이라 단추가 아니라 액션으로 본다
    tacts = [x for x in trow.actions() if not x.isSeparator() and trow.widgetForAction(x)
             and not trow.widgetForAction(x).property("ribbonSpacer")]
    tnames = [x.iconText() for x in tacts]
    chk("등록·설치" in tnames and not any(t in tnames for t in ("기본 PDF 앱 등록", "구성요소 설치", "가상 프린터")),
        "D 도구 탭: '등록·설치' ▾ 하나", str(tnames))
    a_inst = [x for x in tacts if x.iconText() == "등록·설치"][0]
    chk(a_inst.isEnabled() and a_inst.menu() is not None, "D '등록·설치' 는 켜진 ▾ 단추")

    # E 고급 설정
    from viewer.widgets import settings_dialog as sd
    saved = []
    orig_save = mw._save_settings_now
    mw._save_settings_now = lambda *a, **k: saved.append(dict(mw._prefs))
    mw._prefs.update({"law_oc": "", "kcsc_key": ""}); mw._gate_api_dependent_ui(mw._prefs)
    d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw); d.show(); QTest.qWait(50)
    chk(not hasattr(d, "ed_law_oc") and not hasattr(d, "chk_show_keys"), "E 환경설정 창에 API 키 칸이 없다")
    chk(d.btn_advanced.isVisible(), "E '고급 설정...' 단추가 보인다(한국어)")

    def _fake_exec(self):
        self.ed_law_oc.setText("NEWOC")
        self.ed_kcsc_key.setText("KC")
        pw = [e for e in self._key_edits if e.echoMode() == QLineEdit.EchoMode.Password]
        chk(len(pw) == len(self._key_edits), "E 고급 창의 키는 *** 로 가린다")
        return QDialog.DialogCode.Accepted
    orig_exec = sd.AdvancedSettingsDialog.exec
    sd.AdvancedSettingsDialog.exec = _fake_exec
    try:
        QTest.mouseClick(d.btn_advanced, Qt.MouseButton.LeftButton); QTest.qWait(50)
    finally:
        sd.AdvancedSettingsDialog.exec = orig_exec
    chk(mw._prefs.get("law_oc") == "NEWOC" and mw._prefs.get("kcsc_key") == "KC" and saved,
        "E 고급 창 [확인] → 곧바로 저장", str((mw._prefs.get("law_oc"), len(saved))))
    chk(mw._view_acts["law"].isVisible() and mw._view_acts["kcsc"].isVisible(), "E 키 게이팅이 바로 따라간다")
    d.reject()
    chk(mw._prefs.get("law_oc") == "NEWOC", "E 환경설정 [취소] 해도 고급 값은 남는다")
    d2 = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw)
    mw._apply_prefs(d2.result_prefs())                     # 환경설정 [확인] 경로 — 키를 지우지 않는다(허용목록 old 폴백)
    chk(mw._prefs.get("law_oc") == "NEWOC" and mw._prefs.get("kcsc_key") == "KC", "E 환경설정 [확인] 이 고급 값을 지우지 않는다")
    d2.done(0)
    mw._save_settings_now = orig_save
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
