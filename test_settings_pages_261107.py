# -*- coding: utf-8 -*-
"""261107-12: 환경설정 재구성 — 왼쪽 목록 일반/고급 · 한 창 · [확인][적용][취소] · 설정 찾기 (디자인 SOT §2.14).

A. 모든 설정 키가 **어느 한 항목**에만 있다 — 쪽마다 입력 칸을 모두 바꿔 보고 result_prefs 에서 바뀐 키를 모은다(겹침·빠짐 없음)
B. [취소] 는 마지막 [적용] 뒤의 바꿈을 버린다(저장 안 함), [적용] 은 저장하고 창은 그대로, 바뀐 것이 없으면 [적용] 꺼짐
C. 설정 찾기 — 맞는 항목만 목록에, 맞는 줄 강조, 지우면 되돌림, 숨긴 쪽(사진 — PDF 전용일 때)은 찾지 않음
D. open_settings(page=…)·Ctrl+, — 그 항목으로 열리고, 마지막 항목·크기를 기억한다
E. 해시태그 내용 자리 — tag_content_layout 에 붙이고 add_result_fn 으로 저장 값이 합쳐진다
F. 단추 글자에 '…'·'...' 가 없다(앱 전체 — 상태 글은 빼고)
종전 코드로 실패한다(목록·[적용]·찾기·open_settings 가 없다).
"""
import os, re, sys, glob
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QSpinBox, QLineEdit, QKeySequenceEdit, QRadioButton,
                             QMessageBox, QWidget)
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_settings_pages_%d" % os.getpid())   # 마스터 §14.7.2 의 3
import modal_guard
modal_guard.install(label=lambda: "환경설정 261107", watch_ms=0, echo=False)       # 마스터 §14.7.2 의 6
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def flat(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and k != "shortcuts":
            for k2, v2 in v.items():
                out["%s.%s" % (k, k2)] = v2
        else:
            out[k] = v
    return out


def poke(w) -> None:
    """입력 칸 하나의 값을 바꾼다."""
    if isinstance(w, QRadioButton):
        if not w.isChecked():
            w.setChecked(True)
    elif isinstance(w, QCheckBox):
        w.setChecked(not w.isChecked())
    elif isinstance(w, QComboBox):
        if w.isEditable():
            w.setEditText(w.currentText() + "x")
        elif w.count() > 1:
            w.setCurrentIndex((w.currentIndex() + 1) % w.count())
    elif isinstance(w, QSpinBox):
        w.setValue(w.value() + 1 if w.value() < w.maximum() else w.value() - 1)
    elif isinstance(w, QKeySequenceEdit):
        w.setKeySequence(QKeySequence("Ctrl+Alt+Shift+F9"))
    elif isinstance(w, QLineEdit):
        w.setText(w.text() + "x")


try:
    from viewer.app import MainWindow
    from viewer.widgets import settings_dialog as sd
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); QTest.qWait(200)
    saved = []
    mw._save_settings_now = lambda *a, **k: saved.append(1)
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"     # '사진' 쪽이 보이게
    mw._prefs["external_language_packs"] = False

    # A — 키는 한 항목에만
    owner = {}
    dup = []
    for pid in sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw).page_ids():
        d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page=pid)
        before = flat(d.result_prefs())
        content = d._scrolls[pid].widget()
        for w in content.findChildren(QWidget):
            if w is d.cmb_view_kind:
                continue                                 # 보기 종류를 바꾸면 '사진' 쪽이 숨는다 — 따로 본다
            if isinstance(w, (QCheckBox, QRadioButton, QComboBox, QSpinBox, QKeySequenceEdit, QLineEdit)):
                if isinstance(w, QRadioButton) and w.isChecked():
                    continue                             # 고른 라디오는 그대로 — 다른 하나를 고르면 값이 바뀐다
                if isinstance(w, QLineEdit) and isinstance(w.parent(), (QComboBox, QSpinBox)):
                    continue
                poke(w)
        if pid == "general":
            poke(d.cmb_view_kind)
        if pid == "ribbon" and d.ribbon_panel is not None:
            d.ribbon_panel._add_sep()
        if pid == "dict" and getattr(d, "dict_panel", None) is not None:   # 261107-17: 사전 판 — 차례·고름·스타일
            dp = d.dict_panel
            if dp.lst_use.count() > 1:
                dp.lst_use.setCurrentRow(0); dp._move(+1)
            dp._move_all(False)
            dp._styles.append({"name": "시험", "sources": []})
        after = flat(d.result_prefs())
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        for k in changed:
            if k in owner and owner[k] != pid:
                dup.append((k, owner[k], pid))
            owner[k] = pid
        d.done(0)
    allkeys = set(flat(sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw).result_prefs()))
    derived = {"restore_session", "restore_screenshots", "ffmpeg_path",   # 다른 칸에서 끌어오거나 화면에 없는 값
               "picture.view_kind_261114"}                            # 보기 종류를 한 번 혼용으로 바꿨다는 표식(사진 보기 SOT §4.10, 261114-7)
    missing = sorted(allkeys - set(owner) - derived)
    chk(not dup, "A 설정 키는 한 항목에만 있다", str(dup))
    chk(not missing, "A 모든 설정 키가 어느 항목에 있다", str(missing))
    want = {"language": "general", "theme": "general", "startup_mode": "general", "picture.view_kind": "general",
            "page_scroll_mode": "view", "show_panel_toolbar": "view", "picture.slide_interval_s": "photo",
            "auto_tag_enabled": "tags", "screenshot_max": "shots", "shortcuts": "shortcuts", "capture_global": "shortcuts",
            "ribbon_collection": "ribbon", "law_oc": "external", "online_dict_enabled": "dict", "stdict_key": "dict",
            "dict_styles": "dict", "recording_dir": "recording", "lite_flip": "tuning",
            "hyperlink_top_offset_px": "tuning", "external_language_packs": "manage"}
    wrong = {k: (owner.get(k), v) for k, v in want.items() if owner.get(k) != v}
    chk(not wrong, "A 키의 자리 = 디자인 SOT §2.14 표", str(wrong))

    # B — [적용]·[취소]
    d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="shots"); d.show(); QTest.qWait(50)
    chk(not d.btn_apply.isEnabled(), "B 바뀐 것이 없으면 [적용] 꺼짐")
    v0 = int(mw._prefs.get("screenshot_max", 30))
    d.spin_screenshot.setValue(v0 + 7)
    chk(d.btn_apply.isEnabled(), "B 바꾸면 [적용] 켜짐")
    saved.clear()
    QTest.mouseClick(d.btn_apply, Qt.MouseButton.LeftButton); QTest.qWait(30)
    chk(int(mw._prefs.get("screenshot_max")) == v0 + 7 and saved and d.isVisible() and not d.btn_apply.isEnabled(),
        "B [적용] — 저장하고 창은 그대로, [적용] 다시 꺼짐")
    d.spin_screenshot.setValue(v0 + 20)
    d.sc_panel._edits["save_as"].setKeySequence(QKeySequence("Ctrl+F11"))
    saved.clear()
    QTest.mouseClick(d.btn_cancel, Qt.MouseButton.LeftButton); QTest.qWait(30)
    chk(int(mw._prefs.get("screenshot_max")) == v0 + 7 and not saved
        and (mw._prefs.get("shortcuts") or {}).get("save_as", "F12") == "F12" and not d.isVisible(),
        "B [취소] — 적용 뒤의 바꿈(단축키 쪽 포함)은 버린다", str((mw._prefs.get("screenshot_max"), saved)))
    d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="shortcuts"); d.show(); QTest.qWait(50)
    d.sc_panel._edits["save_as"].setKeySequence(QKeySequence("Ctrl+F11"))
    QTest.mouseClick(d.btn_ok, Qt.MouseButton.LeftButton); QTest.qWait(30)
    kind, obj = mw._sc_objs["save_as"]
    chk((mw._prefs.get("shortcuts") or {}).get("save_as") == "Ctrl+F11" and [k.toString() for k in obj.keys()] == ["Ctrl+F11"],
        "B [확인] — 단축키 쪽 바꿈이 곧바로 걸린다", str(mw._prefs.get("shortcuts", {}).get("save_as")))
    mw._prefs["shortcuts"]["save_as"] = "F12"; mw._apply_shortcuts(mw._prefs["shortcuts"])

    # C — 찾기
    d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="general"); d.show(); QTest.qWait(50)
    d.ed_search.setText("슬라이드쇼"); QTest.qWait(30)
    vis = [p for p in d.page_ids() if not d._page_items[p].isHidden()]
    chk(vis == ["photo"] and d.current_page() == "photo" and d.sp_slide_s.parentWidget() is not None
        and any(d._scrolls["photo"].widget().isAncestorOf(w) for w in d._hits),
        "C '슬라이드쇼' → 사진 항목만, 그 쪽으로, 맞는 줄 강조", str(vis))
    d.ed_search.setText(""); QTest.qWait(30)
    chk(all(not d._page_items[p].isHidden() for p in d.page_ids() if p != "external" or d.adv.has_visible())
        and not d._hits, "C 지우면 목록·강조 되돌림")
    d.cmb_view_kind.setCurrentIndex(0)            # PDF 전용 → 사진 쪽 숨김
    d.ed_search.setText("슬라이드쇼"); QTest.qWait(30)
    chk(d._page_items["photo"].isHidden(), "C 숨긴 쪽(사진, PDF 전용)은 찾지 않는다")
    d.ed_search.setText("단축키"); QTest.qWait(30)
    chk(not d._page_items["shortcuts"].isHidden(), "C '단축키' → 단축키 항목")
    d.done(0)

    # D — open_settings·Ctrl+,·기억
    seen = []
    _orig = sd.SettingsDialog.exec

    def _fake_exec(self):
        seen.append(self.current_page())
        self.resize(900, 600)
        self.reject()                             # 실제 창처럼 닫기 길(기억)을 지난다
        return 0
    sd.SettingsDialog.exec = _fake_exec
    try:
        mw.open_settings(page="tuning")
        mw.open_settings()                        # 마지막 항목
        mw.activateWindow(); QTest.qWait(50)
        mw.main_view.setFocus(); QTest.qWait(30)
        QTest.keyClick(mw.main_view, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier); QTest.qWait(50)
    finally:
        sd.SettingsDialog.exec = _orig
    chk(seen[:2] == ["tuning", "tuning"], "D open_settings(page) 와 마지막 항목 기억", str(seen))
    chk(len(seen) == 3, "D Ctrl+, 로 환경설정이 열린다", str(seen))
    mem = mw._prefs.get("settings_window") or {}
    chk(mem.get("page") == "tuning" and int(mem.get("w", 0)) == 900, "D 창 크기·마지막 항목을 설정 settings_window 에", str(mem))

    # E — 해시태그 내용 자리
    d = sd.SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="tags"); d.show(); QTest.qWait(30)
    from PyQt6.QtWidgets import QCheckBox as _QC
    extra = _QC("테스트 낱말")
    d.tag_content_layout.addWidget(extra)
    d.add_result_fn(lambda: {"tag_test_word": extra.isChecked()})
    extra.toggled.connect(d.mark_changed)
    chk(d._scrolls["tags"].widget().isAncestorOf(extra) and not d.btn_apply.isEnabled(), "E 해시태그 쪽에 붙인 위젯")
    extra.setChecked(True)
    chk(d.btn_apply.isEnabled() and d.result_prefs().get("tag_test_word") is True, "E 붙인 값이 저장 값에 합쳐지고 [적용] 이 켜진다")
    d.done(0)

    # F — 단추 글자에 '…' 없음
    pat = re.compile(r'(QPushButton|QToolButton|addButton)\(\s*tr\("[^"]*(\.\.\.|…)"\)')
    allow = ("멈추는 중…", "취소하는 중…")
    bad = []
    root = os.path.dirname(os.path.abspath(__file__))
    for f in glob.glob(os.path.join(root, "viewer", "**", "*.py"), recursive=True):
        for n, ln in enumerate(open(f, encoding="utf-8"), 1):
            if pat.search(ln) and not any(a in ln for a in allow):
                bad.append("%s:%d" % (os.path.relpath(f, root), n))
    chk(not bad, "F 단추 글자에 '…'·'...' 가 없다(상태 글 빼고)", str(bad[:6]))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m_ in fails:
    print(" -", m_)
sys.stdout.flush()
os._exit(1 if fails else 0)
