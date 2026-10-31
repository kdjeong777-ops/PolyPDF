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
from PyQt6.QtCore import QCoreApplication as _QCA
_QCA.setApplicationName("polypdf_ribbon_tabs_%d" % os.getpid())   # 마스터 §14.7.2 의 3 — 공유 시험 설정(qttest/python)에 남기지 않는다
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
        [["1단", "2단"], ["텍스트", "단어장", "검색", "스크린샷"], ["법령·고시", "특허", "건설기준"], ["발표보기"]],
        "A 구분선 셋(1단·2단 따로 — 261031-15, 법령 앞·발표 앞)", str([[b.text() for b in g] for g in row.groups()]))
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

    # ── 261025-5·261025-6 (사용자 지시·결정) ─────────────────────────────────────────────
    # F 최근 검색어 — 실제 Enter 로 검색하면 기록, 누르면 지금 폴더에서 다시(대소문자 토글도 되살림)
    import tempfile, shutil
    from pathlib import Path
    import test_fixtures as _fx
    _root = Path(tempfile.mkdtemp(prefix="polypdf_rs_"))
    shutil.copy(_fx.text_pdf(), _root / "a.pdf")
    mw.open_folder(_root); QTest.qWait(500)
    mw._recent_searches = []; mw._refresh_recent_searches_menu()
    sb = mw.search_bar
    sb.btn_regex.setChecked(False)                # 다른 검사가 남긴 토글 상태를 이어받지 않게
    sb.edit.setText("가나다"); sb.btn_case.setChecked(True)
    QTest.keyClick(sb.edit, Qt.Key.Key_Return); QTest.qWait(200)
    sb.edit.setText("라마"); sb.btn_case.setChecked(False)      # 토글을 바꾸면 지금 글로 다시 찾는다(그것도 실행한 검색)
    QTest.keyClick(sb.edit, Qt.Key.Key_Return); QTest.qWait(200)
    rs = [a.text() for a in mw.menu_recent_searches.actions()]
    chk(rs == ["🔍 라마", "🔍 가나다  Aa"], "F 실행한 검색어가 최근 검색어 맨 위에(토글 표시)", str(rs))
    ran = []
    _orig_as = mw.action_search
    mw.action_search = lambda q: ran.append((q, sb.btn_case.isChecked()))
    mw.menu_recent_searches.actions()[1].trigger(); QTest.qWait(50)
    mw.action_search = _orig_as
    chk(ran == [("가나다", True)] and sb.edit.text() == "가나다", "F 누르면 그 검색어·토글로 지금 폴더에서 다시 찾는다", str(ran))
    chk("recent_searches" in __import__("viewer.settings_store", fromlist=["x"]).PERSONAL_TOP_KEYS,
        "F 최근 검색어는 개인 항목(배포 기본값에서 빠짐)")
    shutil.rmtree(_root, ignore_errors=True)

    # G 리본 숨김 — 탭을 누르면 잠깐 보이고, 명령을 누르면 다시 숨는다 · 리본 밖을 눌러도
    rb = mw._ribbon
    mw._set_ribbon_visible(False); QTest.qWait(50)
    chk(not rb.stack.isVisible(), "G '리본 메뉴 보이기' 를 끄면 리본이 숨는다")
    QTest.mouseClick(rb.tab_button("view"), Qt.MouseButton.LeftButton); QTest.qWait(80)
    chk(rb.stack.isVisible() and rb.peeking(), "G 숨긴 채 탭을 누르면 리본이 잠깐 보인다")
    _b = [b for b in rb.row("view").buttons() if b.text() == "검색"][0]
    QTest.mouseClick(_b, Qt.MouseButton.LeftButton); QTest.qWait(80)
    chk(not rb.stack.isVisible() and not rb.peeking(), "G 명령을 누르면 다시 숨는다")
    QTest.mouseClick(rb.tab_button("file"), Qt.MouseButton.LeftButton); QTest.qWait(80)
    QTest.mouseClick(mw.main_view, Qt.MouseButton.LeftButton); QTest.qWait(80)
    chk(not rb.stack.isVisible(), "G 리본 밖을 눌러도 다시 숨는다")
    chk(mw._prefs.get("show_panel_toolbar") is False, "G 설정은 꺼진 채로 남는다")

    # H 탭 줄 우클릭 — 리본 메뉴 보이기·모음 메뉴 관리
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    from PyQt6.QtCore import QPoint
    seen = []
    _orig_mexec = QMenu.exec
    QMenu.exec = lambda self, *a, **k: (seen.append([x.text() for x in self.actions() if not x.isSeparator()]),
                                         [x for x in self.actions() if x.text() == "리본 메뉴 보이기"][0].setChecked(True))[1]
    try:
        QApplication.sendEvent(rb.tab_row, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5),
                                                             rb.tab_row.mapToGlobal(QPoint(5, 5))))
        QTest.qWait(50)
    finally:
        QMenu.exec = _orig_mexec
    chk(seen and seen[0] == ["리본 메뉴 보이기", "모음 메뉴 관리..."], "H 탭 줄 우클릭 메뉴", str(seen))
    chk(rb.stack.isVisible() and mw._prefs.get("show_panel_toolbar") is True, "H 우클릭 '리본 메뉴 보이기' 로 다시 보인다")

    # I 설정창 배치 — 화면 스타일이 언어 바로 아래, 고급 설정 아래 '발표화면 녹화 설정...'
    from PyQt6.QtWidgets import QGroupBox, QScrollArea
    d3 = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw); d3.show(); QTest.qWait(50)
    content = d3.findChild(QScrollArea).widget()
    titles = [g.title() for g in sorted((g for g in content.findChildren(QGroupBox) if g.parent() is content and g.isVisibleTo(d3)),
                                         key=lambda g: g.y())]
    chk(titles[:2] == ["언어 / Language", "스타일"], "I '스타일' 묶음은 언어 바로 아래", str(titles))
    _grp_style = [g for g in content.findChildren(QGroupBox) if g.title() == "스타일"][0]
    chk(_grp_style.isAncestorOf(d3.btn_shortcuts) and d3.btn_shortcuts.mapTo(d3, d3.btn_shortcuts.rect().topLeft()).y()
        > d3.cmb_theme.mapTo(d3, d3.cmb_theme.rect().topLeft()).y(), "I '단축키 설정...' 단추는 스타일 묶음의 테마 아래")
    from viewer.widgets import shortcuts_dialog as _scd
    _sc_par = []
    _orig_scexec = _scd.ShortcutsDialog.exec
    _scd.ShortcutsDialog.exec = lambda self: (_sc_par.append(self.parent()), 0)[1]
    try:
        QTest.mouseClick(d3.btn_shortcuts, Qt.MouseButton.LeftButton); QTest.qWait(50)
    finally:
        _scd.ShortcutsDialog.exec = _orig_scexec
    chk(_sc_par == [d3], "I 단추를 누르면 단축키 설정 창이 환경설정 창 위에 뜬다", str(_sc_par))
    chk("tools.shortcuts" not in mw._cmds, "I 도구 탭에서 '단축키 설정' 을 뺐다")
    chk("리본 메뉴" in titles and d3.chk_show_panel_toolbar.text() == "리본 메뉴 보이기"
        and d3.btn_edit_collection.text() == "모음 메뉴 관리...", "I '리본 메뉴 보이기'·'모음 메뉴 관리...' 이름", str(titles))
    chk(d3.btn_recording.mapTo(d3, d3.btn_recording.rect().topLeft()).y()
        > d3.btn_advanced.mapTo(d3, d3.btn_advanced.rect().topLeft()).y(), "I '발표화면 녹화 설정...' 은 고급 설정 아래")
    got = []
    _orig_rexec = sd.RecordingSettingsDialog.exec

    def _rexec(self):
        self.ed_rec_dir.setText("D:/녹화")
        got.append(self.windowTitle())
        return QDialog.DialogCode.Accepted
    sd.RecordingSettingsDialog.exec = _rexec
    saved.clear(); mw._save_settings_now = lambda *a, **k: saved.append(1)
    try:
        QTest.mouseClick(d3.btn_recording, Qt.MouseButton.LeftButton); QTest.qWait(50)
    finally:
        sd.RecordingSettingsDialog.exec = _orig_rexec
        mw._save_settings_now = lambda *a, **k: None   # 공유 시험 설정에 고급 키를 남기지 않는다(다른 검사로 샌다)
    chk(got == ["발표화면 녹화 설정"] and mw._prefs.get("recording_dir") == "D:/녹화" and saved,
        "I 녹화 설정 창 [확인] → 곧바로 저장", str((got, mw._prefs.get("recording_dir"))))
    d3.reject()
    called = []
    _orig_rexec2 = sd.RecordingSettingsDialog.exec
    sd.RecordingSettingsDialog.exec = lambda self: (called.append(self.windowTitle()), QDialog.DialogCode.Rejected)[1]
    try:
        mw._open_recording_settings()            # 발표 중 '녹화 설정'
    finally:
        sd.RecordingSettingsDialog.exec = _orig_rexec2
    chk(called == ["발표화면 녹화 설정"], "I 발표 중 녹화 설정도 이 창을 바로 연다", str(called))

    # J '변환' — 파일·도구 탭 모두, 도구는 이미지→PDF 오른쪽 · K 모음 탭 Alt+C
    tn = [a.iconText() for a in rb.row("tools").actions() if a.iconText()]
    fn = [a.iconText() for a in rb.row("file").actions() if a.iconText()]
    from viewer.widgets.ribbon import cmd_id
    tid = [cmd_id(a) for a in rb.row("tools").actions() if cmd_id(a)]
    chk("변환" in fn and tid[tid.index("file.export") + 1] == "tools.translate",
        "J '변환' 은 파일 탭과 도구 탭(번역 왼쪽 — 261031-16)", str(tid))
    rb.select("file"); QTest.qWait(30)
    mw.activateWindow(); QTest.qWait(30)
    QTest.keyClick(mw, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier); QTest.qWait(300)   # 니모닉은 animateClick
    chk(rb.current_key() == "collection", "K Alt+C → 모음 탭", rb.current_key())
    mw._save_settings_now = lambda *a, **k: None   # 공유 시험 설정에 고급 키를 남기지 않는다(다른 검사로 샌다)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
