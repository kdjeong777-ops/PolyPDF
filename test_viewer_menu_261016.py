# -*- coding: utf-8 -*-
"""261016-2: 본문 우클릭 메뉴 차례 · 붙여넣기는 마지막에 복사한 것 · 썸네일 끼운 쪽 메뉴·Ctrl+V·인쇄 창 · 2단 저장 (마스터 §4.7.7·§4.7.20).

A. 편집 모드 1단 본문 우클릭 — 그룹·차례(사용자 지시)
B. 편집 모드가 아니면 같은 차례에서 편집 항목만 빠진다(사용자 결정)
C. 본문 '복사'(개체 안 고름) = 지금 쪽 → '붙여넣기' 는 지금 쪽 아래 끼운 쪽, 붙인 쪽으로 간다
D. '클립보드 붙여넣기' — 쪽이면 그림 개체, 글이면 글쓰기 박스
E. 썸네일 — 끼운 쪽을 눌러도 메뉴가 뜨고, 쪽 번호로 일하는 항목은 끈 채로 '(저장 후)', 복사·삭제·저장은 된다
F. 썸네일 Ctrl+V — 클립보드 그림이 더 나중이면 그림을 새 쪽, 쪽 복사가 더 나중이면 쪽
G. 썸네일 '인쇄…' — 인쇄 창, 하나면 '현재 페이지', 둘 이상이면 '선택한 썸네일 페이지'
H. 2단 메뉴 — '1단 보기'·'옆 창에 열기' / 1창에서 저장해도 2창은 그 파일·쪽 그대로(사용자 보고) / 2창에서 '1단 보기' 는 2창 내용
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
from PyQt6.QtGui import QImage, QColor, QKeyEvent

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_vmenu261016_%d" % os.getpid())

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


def _text(x):
    from PyQt6.QtWidgets import QWidgetAction, QToolButton
    if isinstance(x, QWidgetAction) and x.defaultWidget() is not None:     # 분할 항목(▼ 모양 고르기)
        return x.defaultWidget().findChildren(QToolButton)[0].text()
    return x.text()


def fake_exec(self, *a, **k):
    seen.append([("-", True) if x.isSeparator() else (_text(x), x.isEnabled()) for x in self.actions()])
    return next((x for x in self.actions() if pick["t"] and x.text().startswith(pick["t"])), None)


def labels(m):
    out = []
    for t, _e in m:
        if t == "-" and (not out or out[-1] == "-"):
            continue
        out.append(t)
    while out and out[-1] == "-":
        out.pop()
    return out


root = Path(tempfile.mkdtemp(prefix="vmenu261016_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(4):
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
    mv.go_to_page(1); spin(0.3)
    pr = mv._page_view_rect()
    g = mv.view.viewport().mapToGlobal(mv._norm_to_view(0.7, 0.8, pr))
    QMenu.exec = fake_exec

    # A — 편집 모드 1단
    mw._on_viewer_context_menu(g); spin(0.1)
    L = labels(seen[-1])
    want = ["인쇄…", "복사", "텍스트 복사", "블럭설정 후 텍스트 복사", "붙여넣기", "스크린샷 붙여넣기",
            "클립보드 붙여넣기", "사진 붙여넣기", "삭제 (p.2)", "저장", "-",
            "2단 보기", "발표보기", "-",
            "왼쪽 90° 회전 (p.2)", "오른쪽 90° 회전 (p.2)", "여기에 서명…", "-",
            "숨김 (p.2)", "숨김 해제 (p.2)", "-",
            "책갈피 추가 (p.2)", "하이퍼링크 등록… (p.2)", "-",
            "도형 입력 설정…", "글쓰기 입력 설정…"]
    chk(L == want, "A 편집 모드 1단 — 그룹·차례(사용자 지시)", str(L))
    en = dict(seen[-1])
    chk(en.get("숨김 (p.2)") is True and en.get("숨김 해제 (p.2)") is False, "A2 숨김·해제 둘 다 보이고 지금 상태에 맞는 쪽만 켜짐")

    # B — 보기 모드
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt.btn_edit.setChecked(False); spin(0.3)
    mw._on_viewer_context_menu(g); spin(0.1)
    L = labels(seen[-1])
    chk(L == ["인쇄…", "복사", "텍스트 복사", "블럭설정 후 텍스트 복사", "-", "2단 보기", "발표보기", "-",
              "왼쪽 90° 회전 (p.2)", "오른쪽 90° 회전 (p.2)", "여기에 서명…"],
        "B 보기 모드 — 같은 차례에서 편집 항목만 빠진다", str(L))
    bt.btn_edit.setChecked(True); spin(0.3)
    mv, pt = mw.main_view, mw.page_thumbs
    mv.go_to_page(1); spin(0.3)

    # C — 복사(지금 쪽) → 붙여넣기(지금 쪽 아래, 그 쪽으로)
    pick["t"] = "복사"
    mw._on_viewer_context_menu(g); spin(0.1)
    chk(mw._thumb_clip and mw._thumb_clip["items"] == [(str(a), 1)] and mw._clipboard_kind() == "pages",
        "C1 '복사'(개체 안 고름) = 지금 쪽, 마지막 복사는 '쪽'", str(mw._thumb_clip))
    pick["t"] = "붙여넣기"
    mw._on_viewer_context_menu(g); spin(0.5)
    plan = pt.current_page_plan()
    chk(plan[:3] == [("own", 0), ("own", 1), ("ext", str(a), 1)], "C2 '붙여넣기' — 지금 쪽(2쪽) 아래 끼운 쪽", str(plan))
    chk(pt.is_staged_page(mv.current_page()), "C3 붙인 쪽으로 간다", str(mv.current_page()))
    sel_rows = sorted(pt.list.row(it) for it in pt.list.selectedItems())
    chk(sel_rows == [2], "C4 붙인 마지막 쪽 하나만 골라져 있다(261016-3, 앞뒤 썸네일 안 골라짐)", str(sel_rows))
    # 지금 쪽이 붙여넣은 쪽 — 이상한 번호 없이 '붙여넣은 쪽', 누르면 저장 뒤에 하라고 알린다
    msgs = []
    QMessageBox.information = staticmethod(lambda *a_, **k: msgs.append(a_[2] if len(a_) > 2 else ""))
    seen.clear(); pick["t"] = "왼쪽 90°"
    mw._on_viewer_context_menu(g); spin(0.2)
    L = labels(seen[-1])
    chk(not any("100000" in t for t in L) and "왼쪽 90° 회전 (붙여넣은 쪽)  (저장 후)" in L,
        "C5 붙여넣은 쪽 — 합성 번호 대신 '(붙여넣은 쪽)'", str([t for t in L if "회전" in t or "숨김" in t]))
    chk(msgs and "저장" in msgs[-1], "C6 누르면 '저장한 뒤 다시' 를 알린다(아무 일 없이 끝나지 않는다)", str(msgs))
    pick["t"] = None
    mv.go_to_page(0); spin(0.3)

    # D — 클립보드 붙여넣기: 쪽 → 그림 / 글 → 글쓰기 박스
    n_img = len(mv._img_objects)
    mw._on_copy_pages([(str(b), 0)])
    chk(mw._paste_clipboard_on_page() and len(mv._img_objects) == n_img + 1, "D1 마지막 복사가 쪽이면 그 쪽을 그림으로")
    QApplication.clipboard().setText("붙인 글\n두째 줄")
    n_st = len(mv._page_strokes)
    chk(mw._clipboard_kind() == "text" and mw._paste_clipboard_on_page() and len(mv._page_strokes) == n_st + 1
        and mv._page_strokes[-1].get("text_box") and mv._page_strokes[-1]["text"] == "붙인 글\n두째 줄",
        "D2 글이면 글쓰기 박스로")
    mw._save_meta_from_button(); spin(0.3)

    # E — 썸네일: 끼운 쪽 우클릭
    r_st = next(i for i in range(pt.list.count()) if isinstance(pt.list.item(i).data(Qt.ItemDataRole.UserRole), tuple))
    pt.list.clearSelection(); pt.list.item(r_st).setSelected(True)
    seen.clear(); pick["t"] = None
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(r_st)).center()); spin(0.1)
    m = dict(seen[-1]) if seen else {}
    chk(bool(seen), "E1 끼운 쪽에서도 메뉴가 뜬다(종전 예외로 안 떴다)")
    chk(m.get("복사 (1쪽)") is True and m.get("삭제 (1쪽)") is True and m.get("저장") is True,
        "E2 복사·삭제·저장은 된다", str(list(m)[:10]))
    off = [t for t in m if t.endswith("(저장 후)")]
    chk(len(off) >= 6 and all(m[t] for t in off) and any(t.startswith("왼쪽 90°") for t in off),
        "E3 쪽 번호로 일하는 항목은 '(저장 후)' — 켜 두고(261016-3)", str(off))
    msgs.clear(); pick["t"] = "왼쪽 90°"
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(r_st)).center()); spin(0.3)
    chk(msgs and "저장" in msgs[-1], "E3b 누르면 '저장한 뒤 다시' 를 알린다", str(msgs))
    pick["t"] = None
    pick["t"] = "복사"
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(r_st)).center()); spin(0.1)
    chk(mw._thumb_clip["items"] == [(str(a), 1)], "E4 끼운 쪽 복사 = 그 원본 파일·쪽", str(mw._thumb_clip))
    pick["t"] = None

    # F — 썸네일 Ctrl+V: 마지막 복사
    def ctrl_v():
        pt.list.setFocus()
        QApplication.sendEvent(pt.list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier))
        spin(2.0)
    pt.list.clearSelection(); pt.list.item(0).setSelected(True)
    n0 = pt.list.count()
    img = QImage(120, 80, QImage.Format.Format_RGB32); img.fill(QColor("red"))
    QApplication.clipboard().setImage(img)
    ctrl_v()
    v1 = pt.list.item(1).data(Qt.ItemDataRole.UserRole)
    chk(pt.list.count() == n0 + 1 and isinstance(v1, tuple) and str(v1[0]) != str(a),
        "F1 클립보드 그림이 더 나중이면 그림을 새 쪽으로(고른 썸네일 아래)", str(v1))
    mw._on_copy_pages([(str(b), 3)])
    pt.list.clearSelection(); pt.list.item(0).setSelected(True)
    ctrl_v()
    v1 = pt.list.item(1).data(Qt.ItemDataRole.UserRole)
    chk(pt.list.count() == n0 + 2 and tuple(v1[:2]) == (str(b), 3), "F2 쪽 복사가 더 나중이면 쪽", str(v1))

    # G — 썸네일 '인쇄…' → 인쇄 창 범위 기본값
    import viewer.widgets.print_dialog as pdm
    got = {}
    _orig_pexec = pdm.PrintScopeDialog.exec
    pdm.PrintScopeDialog.exec = lambda self: (got.setdefault("cur", self.rb_cur.isChecked()),
                                              got.setdefault("thumb", self.rb_thumb.isChecked()), 0)[2]
    pt.list.clearSelection(); pt.list.item(0).setSelected(True)
    pick["t"] = "인쇄"
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(0)).center()); spin(0.2)
    chk(got.get("cur") is True, "G1 하나면 인쇄 창이 '현재 페이지' 로", str(got))
    got.clear()
    own_rows = [i for i in range(pt.list.count()) if isinstance(pt.list.item(i).data(Qt.ItemDataRole.UserRole), int)]
    for r_ in own_rows[:2]:
        pt.list.item(r_).setSelected(True)
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(own_rows[0])).center()); spin(0.2)
    chk(got.get("thumb") is True, "G2 둘 이상이면 '선택한 썸네일 페이지' 로", str(got))
    pdm.PrintScopeDialog.exec = _orig_pexec
    pick["t"] = None

    # 쪽 편집을 저장해 둔다(H 의 저장 시험을 깨끗하게)
    mw._save_current_file(); spin(3.0)

    # H — 2단
    mw._view_as_split(); spin(1.0)
    from viewer.history import HistoryItem
    mw._set_active_pane(1); spin(0.3)
    mw._load_main(HistoryItem(str(b), 2, "", "bookmark")); spin(1.2)      # 2창 → b.pdf 3쪽
    chk(Path(str(mw._mv[1].current_file())).name == "b.pdf" and mw._mv[1].current_page() == 2, "H0 2창 = b.pdf 3쪽")
    seen.clear()
    mw._on_viewer_context_menu(g); spin(0.1)
    L = labels(seen[-1])
    chk("1단 보기" in L and "옆 창에 열기" in L and "2단 보기" not in L, "H1 2단 메뉴 — '1단 보기'·'옆 창에 열기'", str(L))
    mw._set_active_pane(0); spin(0.5)
    mv0 = mw._mv[0]
    mv0.go_to_page(0); spin(0.3)
    mv0._page_strokes.append({"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "SAVE1", "size_pt": 12})
    mv0._save_page_strokes(); mw._edit_dirty = True
    mw._save_current_file(); spin(4.0)
    chk(mw._mv[0].current_file() and Path(str(mw._mv[0].current_file())).name == "a.pdf", "H2 1창은 저장한 a.pdf 를 다시 연다",
        str(mw._mv[0].current_file()))
    chk(mw._mv[1].current_file() is not None and Path(str(mw._mv[1].current_file())).name == "b.pdf"
        and mw._mv[1].current_page() == 2 and mw._mv[1]._doc is not None,
        "H3 ★ 1창에서 저장해도 2창은 b.pdf 3쪽 그대로(사용자 보고)",
        str((mw._mv[1].current_file(), mw._mv[1].current_page())))
    # H3b — 261016-5(§4.7.8): 다른 PolyPDF 창이 b.pdf 를 저장하느라 이 창에 '놓기'·'다시 열기' 를 보낼 때도 1창은 그대로
    mw._set_active_pane(0); spin(0.3)
    r1 = mw._on_instance_request("release", str(b)); spin(0.3)
    r2 = mw._on_instance_request("reload", str(b)); spin(2.0)
    chk(r1.get("ok") and r2.get("ok") and Path(str(mw._mv[0].current_file())).name == "a.pdf"
        and mw._mv[0]._doc is not None and Path(str(mw._mv[1].current_file())).name == "b.pdf"
        and mw._active_pane == 0,
        "H3b 다른 창이 저장(놓기·다시 열기)해도 1창 a.pdf 그대로·활성 창 그대로",
        str((mw._mv[0].current_file(), mw._mv[1].current_file(), mw._active_pane)))
    mw._set_active_pane(1); spin(0.5)
    mw._view_single_keep(1); spin(1.0)
    chk(not mw._split_on and Path(str(mw._mv[0].current_file())).name == "b.pdf",
        "H4 2창에서 '1단 보기' — 2창 내용(b.pdf)이 1단에", str(mw._mv[0].current_file()))
    QMenu.exec = _orig_exec          # 창은 닫지 않는다(닫기 확인), os._exit 로 끝낸다
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
