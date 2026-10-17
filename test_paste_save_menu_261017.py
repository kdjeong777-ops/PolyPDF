# -*- coding: utf-8 -*-
"""261017-1: 붙여넣은 쪽 꾸밈이 저장 뒤에도 남고 다시 열기는 한 번 · 본문 Del · 메뉴 단축키 칸 · 보기 메뉴 · 캡처 모드 · 읽기 단추 폭
(마스터 §4.7.9·§4.7.20 · 입력 SOT §3 · 디자인 SOT §2.9.2·§2.10).

A. 붙여넣은 쪽(저장 전)에 그린 꾸밈과 옮겨진 자체 쪽의 꾸밈이 [저장] 뒤 **새 쪽 번호**에 그대로 있다(사용자 보고 '저장하면 사라짐')
B. 그 저장에서 본문을 다시 여는 것은 **한 번**(사용자 보고 '2번 깜박임' — 종전엔 사본 저장이 한 번 더 열었다)
C. 편집모드·고른 개체 없음에서 본문 Del → 지금 쪽이 쪽 편집으로 지워진다. 보기 모드에서는 아무 일 없음
D. 메뉴 오른쪽 단축키 칸: 본문 우클릭 '인쇄…' Ctrl+P·'삭제' Del·'발표보기' F5, 보기 메뉴 2단·발표, 썸네일 '복사' Ctrl+C
E. 보기 메뉴에 '옵션 메뉴' 항목이 없고 단축키(Shift+F10)는 그대로 창에 있다
F. 캡처 모드를 고르면 그 창을 곧바로 캡처한다
G. 읽기 모드 풀다운 폭은 고정이 아니다(글자에 맞춤)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QEvent
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtGui import QKeyEvent

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pastesave261017_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


seen, pick = [], {"t": None}


def fake_exec(self, *a, **k):
    seen.append([x.text() for x in self.actions() if not x.isSeparator()])
    return next((x for x in self.actions() if pick["t"] and x.text().split("\t")[0].startswith(pick["t"])), None)


def TB(text):
    return {"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": text, "size_pt": 12}


root = Path(tempfile.mkdtemp(prefix="pastesave261017_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(3):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    mv, pt = mw.main_view, mw.page_thumbs

    # A·B — 자체 2쪽(1)에 꾸밈, b.pdf 1쪽을 1쪽 아래에 붙이고 그 쪽에 꾸밈 → 저장
    mv.go_to_page(1); spin(0.3)
    mv._page_strokes = [TB("OWN2")]; mv._save_page_strokes()
    mw._on_copy_pages([(str(b), 0)])
    mw._on_paste_pages(0); spin(0.5)                      # 1쪽(행 0) 아래 = 새 2쪽 자리
    v = pt.list.item(1).data(Qt.ItemDataRole.UserRole)
    mv.go_to_page(pt.STAGED_BASE + int(v[2])); spin(0.4)
    mv._page_strokes = [TB("PASTED")]; mv._save_page_strokes(); mw._edit_dirty = True
    opens = []
    _orig_open = mw._open_saved_file
    mw._open_saved_file = lambda *a_, **k: (opens.append(a_), _orig_open(*a_, **k))[1]
    mw._save_current_file(); spin(4.0)
    st = mw._ensure_page_meta_store()
    texts = {pg: [s.get("text") for s in st.get_drawings(str(a), pg)] for pg in range(4)}
    chk(fitz.open(str(a)).page_count == 4, "A0 저장 — a.pdf 4쪽")
    chk(texts.get(1) == ["PASTED"], "A1 붙여넣은 쪽의 꾸밈이 저장 뒤 새 2쪽에 남는다(사용자 보고)", str(texts))
    chk(texts.get(2) == ["OWN2"], "A2 옮겨진 자체 쪽(옛 2쪽 → 새 3쪽)의 꾸밈도 따라간다", str(texts))
    chk(not any(int(p) >= pt.STAGED_BASE for p in st.pages_with_drawings(str(a))), "A3 합성 번호 키가 남지 않는다")
    chk(len(opens) == 1, "B 저장 한 번에 본문 다시 열기는 한 번(사용자 보고 '2번 깜박임')", str(len(opens)))
    mw._open_saved_file = _orig_open

    # C — 본문 Del
    mw._on_bookmark_activated(str(b), 0); spin(1.0)
    mv, pt = mw.main_view, mw.page_thumbs
    mv.go_to_page(1); spin(0.3)
    mv._multi_clear(); mv._stroke_selected = -1; mv._img_selected = -1
    n0 = len(pt.current_page_plan())
    mv.view.setFocus()
    QApplication.sendEvent(mv.view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)); spin(0.4)
    plan = pt.current_page_plan()
    chk(len(plan) == n0 - 1 and ("own", 1) not in plan, "C1 편집모드·고른 개체 없음 → Del 이 지금 쪽(2쪽)을 지운다", str(plan))
    bt.btn_edit.setChecked(False); spin(0.4)
    mv, pt = mw.main_view, mw.page_thumbs
    n1 = len(pt.current_page_plan())
    QApplication.sendEvent(mv.view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)); spin(0.3)
    chk(len(pt.current_page_plan()) == n1, "C2 보기 모드에서는 Del 이 쪽을 지우지 않는다")
    bt.btn_edit.setChecked(True); spin(0.4)
    mv, pt = mw.main_view, mw.page_thumbs

    # D — 단축키 칸
    QMenu.exec = fake_exec
    pr = mv._page_view_rect()
    g = mv.view.viewport().mapToGlobal(mv._norm_to_view(0.7, 0.8, pr))
    mw._on_viewer_context_menu(g); spin(0.1)
    L = seen[-1]
    chk(any(t.startswith("인쇄…") and t.endswith("\tCtrl+P") for t in L)
        and any(t.startswith("삭제") and t.endswith("\tDel") for t in L)
        and any(t.startswith("발표보기") and t.endswith("\tF5") for t in L)
        and any(t.startswith("2단 보기") and t.endswith("\tCtrl+Shift+2") for t in L),
        "D1 본문 우클릭 — 인쇄 Ctrl+P · 삭제 Del · 발표 F5 · 2단 Ctrl+Shift+2 가 오른쪽 칸에", str(L))
    chk(not any(t.startswith("붙여넣기") and "\t" in t for t in L), "D2 본문 '붙여넣기'(쪽)는 Ctrl+V 와 하는 일이 달라 키를 보이지 않는다")
    pt.list.clearSelection(); pt.list.item(0).setSelected(True)
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(0)).center()); spin(0.1)
    chk(any(t.startswith("복사") and t.endswith("\tCtrl+C") for t in seen[-1]), "D3 썸네일 '복사' Ctrl+C", str(seen[-1]))
    QMenu.exec = _orig_exec
    va = mw._view_acts
    chk(va["split"].text().endswith("\tCtrl+Shift+2") and va["present"].text().endswith("\tF5"),
        "D4 보기 메뉴 2단·발표보기 오른쪽 칸", str((va["split"].text(), va["present"].text())))
    mw._prefs.setdefault("shortcuts", {})["present"] = "F6"; mw._apply_shortcuts(mw._prefs["shortcuts"])
    chk(va["present"].text().endswith("\tF6"), "D5 단축키 설정을 바꾸면 표시도 따라간다", va["present"].text())
    mw._prefs["shortcuts"].pop("present", None); mw._apply_shortcuts(mw._prefs["shortcuts"])

    # E — 보기 메뉴
    m_view = next(x.menu() for x in mw.menuBar().actions() if x.text().startswith("보기"))
    chk(not any("옵션 메뉴" in x.text() for x in m_view.actions()), "E1 보기 메뉴에 '옵션 메뉴' 항목이 없다")
    chk(mw._sc_act_option_menu in mw.actions() and mw._sc_act_option_menu.shortcut().toString() == "Shift+F10",
        "E2 Shift+F10 은 창에 걸려 그대로 동작")

    # F — 캡처 모드
    caps = []
    mw._do_capture = lambda view, *a_, **k: caps.append(view)
    mw._set_cap_mode("full", capture_pane=0); spin(0.3)
    chk(caps and caps[-1] is mw._mv[0], "F 캡처 모드를 고르면 그 창을 곧바로 캡처")

    # G — 읽기 모드 풀다운 폭
    rb = mw.btn_read_menu
    chk(rb.minimumWidth() != rb.maximumWidth() or rb.width() != 78, "G 읽기 모드 풀다운 폭은 고정 78 이 아니다",
        str((rb.minimumWidth(), rb.maximumWidth(), rb.width())))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
