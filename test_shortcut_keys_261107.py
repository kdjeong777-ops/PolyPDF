# -*- coding: utf-8 -*-
"""261107-4: 흔한 프로그램 관례 키 · 키캡 그림 (입력 SOT §3.2.3 · 디자인 SOT §2.9.2 '키캡 그림' · 마스터 §8.2 v13).

A. 기본 키 — 표의 새 키가 그 id 에, 기본 키끼리 겹치지 않는다(겹치면 Qt 가 둘 다 듣지 않는다), 클립보드로 복사는 Ctrl+Alt+C
B. 설정 v12→v13 — 옛 기본값 Ctrl+Shift+C 로 남은 clipboard_save 만 Ctrl+Alt+C 로, 바꾼 값은 그대로,
   새 키가 사용자가 다른 id 에 둔 키와 같으면 그 새 id 를 비운다, 두 번 돌려도 그대로
C. 실제 키 입력 → 메뉴와 같은 함수(대상은 포커스): F12·Ctrl+Shift+C(책갈피창 고른 파일 경로)·Ctrl+Shift+N·Alt+Shift+R·Alt+Enter·
   Ctrl+Shift+X·Ctrl+Enter·Ctrl+B·Ctrl+K·Ctrl+D·Ctrl+Alt+O
D. 키캡 — 'Ctrl++' 나누기, 작은 글자 최소 크기, 키캡 줄 폭 ≤ 글자 'Ctrl+Shift+S' 폭 + 여유, 메뉴 항목 글은 글자 그대로(낭독기), 앱 스타일이 키캡 메뉴 스타일
E. 단축키 창에서 지운 키는 빈 값으로 남는다(빼면 다음 실행에 기본 키가 되살아난다), 키캡 미리 보기 칸
M. 261107-18: Alt+1 = PDF 모드·Alt+2 = 사진 모드(토글 아님, 단추와 같은 함수), PDF 전용이면 아무 일 없음, 토글 단추 툴팁 키캡
종전 코드로 실패한다(새 id·v13·키캡 모듈이 없다 — M 은 mode_pdf·mode_photo 가 없다).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QKeySequence, QFont, QFontMetricsF
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_keys261107_%d" % os.getpid())     # 마스터 §14.7.2 의 3
import modal_guard
modal_guard.install(label=lambda: "단축키 261107", watch_ms=0, echo=False)       # 마스터 §14.7.2 의 6

fails = []
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
NOMOD = Qt.KeyboardModifier.NoModifier


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def focus(w):
    w.setFocus(Qt.FocusReason.OtherFocusReason); spin(0.05)


WANT = {"save_as": "F12", "copy_path": "Ctrl+Shift+C", "clipboard_save": "Ctrl+Alt+C", "rename_item": "F2",
        "new_folder": "Ctrl+Shift+N", "reveal": "Alt+Shift+R", "info": "Alt+Enter", "crop": "Ctrl+Shift+X",
        "new_page": "Ctrl+Enter", "add_bookmark": "Ctrl+B", "hyperlink": "Ctrl+K", "fav_add_file": "Ctrl+D",
        "ocr_read": "Ctrl+Alt+O", "mode_pdf": "Alt+1", "mode_photo": "Alt+2"}

root = Path(tempfile.mkdtemp(prefix="keys261107_"))
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(4):
        d.new_page(width=595, height=842).insert_text((72, 400), "A P%d" % (i + 1))
    d.set_toc([[1, "one", 1], [1, "two", 3]])
    d.save(str(a)); d.close()
    from viewer.app import MainWindow
    from viewer import settings_store
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1400, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mv, bt = mw.main_view, mw.bookmark_tree

    # A — 기본 키
    D = {sid: v[1] for sid, v in mw._sc_defs.items()}
    chk(all(D.get(k) == v for k, v in WANT.items()), "A1 새 기본 키(입력 SOT §3.2.3)",
        str({k: D.get(k) for k in WANT if D.get(k) != WANT[k]}))
    norm = [QKeySequence(v).toString() for v in D.values() if v]
    dup = sorted({k for k in norm if norm.count(k) > 1})
    chk(not dup, "A2 기본 키끼리 겹치지 않는다", str(dup))
    kind, obj = mw._sc_objs.get("clipboard_save", (None, None))
    chk(kind == "shortcut" and [k.toString() for k in obj.keys()] == ["Ctrl+Alt+C"], "A3 클립보드로 복사는 Ctrl+Alt+C 에 묶인다")
    chk(set(settings_store.NEW_KEYS_V13) <= set(D) and all(D[k] == v for k, v in settings_store.NEW_KEYS_V13.items()),
        "A4 설정 v13 의 새 키 목록 = _sc_defs 기본값(한 곳이 어긋나지 않게)")

    # B — 설정 v12 → v13
    old = {"schema_version": 12, "preferences": {"shortcuts": {"clipboard_save": "Ctrl+Shift+C", "save": "Ctrl+S"}}}
    new = settings_store._migrate(old)
    sc = new["preferences"]["shortcuts"]
    chk(settings_store.CURRENT_SCHEMA >= 13 and new["schema_version"] == 13 and sc["clipboard_save"] == "Ctrl+Alt+C",
        "B1 옛 기본값 Ctrl+Shift+C 만 Ctrl+Alt+C 로", str(sc))
    mine = settings_store._migrate({"schema_version": 12, "preferences": {"shortcuts": {"clipboard_save": "Ctrl+Shift+Q",
                                                                                      "draw_mode": "Ctrl+B"}}})
    sc2 = mine["preferences"]["shortcuts"]
    chk(sc2["clipboard_save"] == "Ctrl+Shift+Q", "B2 사용자가 바꾼 클립보드 키는 그대로", str(sc2))
    chk(sc2.get("add_bookmark") == "" and "hyperlink" not in sc2,
        "B3 새 키(Ctrl+B)가 사용자 키와 겹치면 그 새 id 를 비운다 — 겹치지 않는 새 id 는 기본값", str(sc2))
    again = settings_store._migrate(dict(mine))
    chk(again["preferences"]["shortcuts"] == sc2, "B4 두 번 돌려도 그대로(idempotent)")

    # C — 실제 키 입력
    seen = []

    def rec(name):
        return lambda *a_, **k: seen.append((name, a_, k))

    mw._action_save_as = rec("save_as")
    mw._open_crop_dialog = rec("crop")
    mw._on_add_blank_page = rec("new_page")
    mw._prompt_add_bookmark = rec("bm")
    mw._open_hyperlink_dialog = rec("hl")
    mw._add_current_file_favorite = rec("fav")
    mw._action_ocr_read = rec("ocr")
    mw.show_doc_info = rec("info")
    bt._ask_new_folder = rec("new_folder")
    bt._reveal_in_explorer = rec("reveal")
    mw.activateWindow(); spin(0.1)

    def press(key, mods, target):
        seen.clear()
        focus(target)
        QTest.keyClick(target, key, mods); spin(0.15)
        return [s[0] for s in seen]

    tgt = mv.view if hasattr(mv, "view") else mv
    chk(press(Qt.Key.Key_F12, NOMOD, tgt) == ["save_as"], "C1 F12 → 다른 이름으로 저장")
    chk(press(Qt.Key.Key_X, CTRL | SHIFT, tgt) == ["crop"] and seen[0][2].get("view") is mv, "C2 Ctrl+Shift+X → 지금 쪽 크롭 창",
        str(seen))
    mv.go_to_page(2); spin(0.4)
    chk(press(Qt.Key.Key_B, CTRL, tgt) == ["bm"] and seen[0][1] == (str(a), 3), "C3 Ctrl+B → 지금 쪽(3쪽) 책갈피 추가", str(seen))
    chk(press(Qt.Key.Key_K, CTRL, tgt) == ["hl"] and seen[0][1] == (str(a), 2), "C4 Ctrl+K → 지금 쪽 하이퍼링크", str(seen))
    chk(press(Qt.Key.Key_Return, CTRL, tgt) == ["new_page"] and seen[0][1] == (2,), "C5 Ctrl+Enter → 지금 쪽 아래 새 페이지", str(seen))
    chk(press(Qt.Key.Key_D, CTRL, tgt) == ["fav"], "C6 Ctrl+D → 즐겨찾기에 추가(현재 파일)")
    chk(press(Qt.Key.Key_O, CTRL | ALT, tgt) == ["ocr"], "C7 Ctrl+Alt+O → OCR 로 읽기")
    chk(press(Qt.Key.Key_Return, ALT, tgt) == ["info"], "C8 Alt+Enter → 문서 정보")
    chk(press(Qt.Key.Key_R, ALT | SHIFT, tgt) == ["reveal"] and seen[0][1] == (str(a),), "C9 Alt+Shift+R → 파일 탐색기 열기", str(seen))
    tw = bt.tree
    node = bt._file_node_for_path(str(a))
    tw.setCurrentItem(node); node.setSelected(True)
    QApplication.clipboard().setText("")
    press(Qt.Key.Key_C, CTRL | SHIFT, tw)
    chk(QApplication.clipboard().text() == str(a), "C10 Ctrl+Shift+C(책갈피창) → 고른 파일 경로 복사", QApplication.clipboard().text())
    chk(press(Qt.Key.Key_N, CTRL | SHIFT, tw) == ["new_folder"], "C11 Ctrl+Shift+N → 새 폴더 만들기")

    # D — 키캡
    from viewer.widgets import keycaps as kc
    chk(kc.split_keys("Ctrl++") == ["Ctrl", "+"] and kc.split_keys("Ctrl+Shift+S") == ["Ctrl", "Shift", "S"]
        and kc.split_keys("") == [], "D1 키 나누기('+' 키 자체 포함)")
    f = QFont("Malgun Gothic"); f.setPointSize(9)
    big, small, uniform = kc._fonts(f)
    chk(uniform or small.pixelSize() >= kc.KEYCAP_MIN_PX, "D2 작은 글자는 최소 KEYCAP_MIN_PX", str(small.pixelSize()))
    w_caps = kc.keycap_size("Ctrl+Shift+S", f).width()
    w_text = QFontMetricsF(f).horizontalAdvance("Ctrl+Shift+S")
    chk(0 < w_caps <= w_text + 12, "D3 키캡 줄 폭이 글자 'Ctrl+Shift+S' 폭과 비슷하거나 좁다", "%s / %s" % (w_caps, w_text))
    chk(isinstance(app.style(), kc.KeycapMenuStyle), "D4 앱 스타일이 키캡 메뉴 스타일(Fusion 을 감쌈)", type(app.style()).__name__)
    from PyQt6.QtWidgets import QMenu
    m = QMenu(mw)
    act = m.addAction(mw._kt("다른 이름으로 저장", "save_as"))
    chk(act.text().endswith("\tF12"), "D5 메뉴 항목 글은 글자 그대로(낭독기·복사는 글자)", act.text())
    pm = kc.keycap_pixmap("Ctrl+Shift+S", f, mw.palette().color(mw.palette().ColorRole.WindowText))
    chk(not pm.isNull() and pm.width() > 0, "D6 키캡 그림을 그린다")
    chk("data:image/png;base64," in kc.keycap_html("Ctrl+S", f, mw.palette().color(mw.palette().ColorRole.WindowText)),
        "D7 툴팁용 키캡 그림(서식 글)")

    # E — 단축키 창
    from viewer.widgets.shortcuts_dialog import ShortcutsDialog
    dlg = ShortcutsDialog(mw._sc_defs, {}, mw)
    dlg._edits["add_bookmark"].clear()
    res = dlg.result_shortcuts()
    chk(res.get("add_bookmark") == "" and res.get("save_as") == "F12", "E1 지운 키는 빈 값으로 남는다", str(res.get("add_bookmark")))
    cap = dlg._caps.get("save_as")
    chk(cap is not None and cap.keys() == "F12" and cap.accessibleName() == "F12", "E2 키캡 미리 보기 칸(낭독기에는 글자)")
    dlg._edits["save_as"].setKeySequence(QKeySequence("Ctrl+F12")); spin(0.05)
    chk(cap.keys() == QKeySequence("Ctrl+F12").toString(QKeySequence.SequenceFormat.NativeText), "E3 키를 바꾸면 키캡도 따라온다", cap.keys())
    dlg.close()

    # M — Alt+1·Alt+2 = PDF·사진 모드로(261107-18, 입력 SOT §3.2.3 · 사진 보기 SOT 4.1)
    def mtgt():
        v = mw.main_view
        return v.view if hasattr(v, "view") else v

    def press_mode(key):
        focus(mtgt())
        QTest.keyClick(mtgt(), key, ALT); spin(0.6)
        return mw._photo_mode

    pic = mw._photo_prefs()
    pic["view_kind"] = "mixed"; mw._photo_apply_view_kind(); spin(0.2)
    chk(not mw._photo_mode, "M0 혼용 · PDF 모드에서 시작")
    calls = []
    _orig_set = mw._set_photo_mode
    mw._set_photo_mode = lambda on, *a_, **k: (calls.append(bool(on)), _orig_set(on, *a_, **k))
    chk(press_mode(Qt.Key.Key_2) is True, "M1 Alt+2 → 사진 모드")
    chk(press_mode(Qt.Key.Key_2) is True, "M2 Alt+2 다시 → 그대로 사진 모드(토글이 아니다)")
    chk(press_mode(Qt.Key.Key_1) is False, "M3 Alt+1 → PDF 모드")
    chk(press_mode(Qt.Key.Key_1) is False, "M4 Alt+1 다시 → 그대로 PDF 모드")
    chk(calls and all(c in (True, False) for c in calls), "M5 단추와 같은 함수(_set_photo_mode)", str(calls))
    pic["view_kind"] = "pdf"; mw._photo_apply_view_kind(); spin(0.2)
    calls.clear()
    chk(press_mode(Qt.Key.Key_2) is False and not calls, "M6 PDF 전용이면 Alt+2 는 아무 일도 하지 않는다", str(calls))
    pic["view_kind"] = "mixed"; mw._photo_apply_view_kind(); spin(0.2)
    mw._set_photo_mode = _orig_set
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtWidgets import QToolTip
    b = mw._photo_btn
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(4, 4), b.mapToGlobal(QPoint(4, 4)))
    QApplication.sendEvent(b, ev); spin(0.1)
    tip = QToolTip.text()
    chk("data:image/png;base64," in tip and b.toolTip() in tip, "M7 토글 단추 툴팁 끝에 누르면 될 모드의 키캡", tip[:80])
    chk(mw._sc_key("mode_photo") == QKeySequence("Alt+2").toString(QKeySequence.SequenceFormat.NativeText),
        "M8 사진 모드 키 = Alt+2")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m_ in fails:
    print(" -", m_)
sys.stdout.flush()
os._exit(1 if fails else 0)
