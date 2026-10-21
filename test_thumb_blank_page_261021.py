# -*- coding: utf-8 -*-
"""261021-3: 썸네일 우클릭 '새 페이지 넣기' — 기준 쪽 크기의 흰 쪽 (마스터 §4.7.11 '흰 쪽을 새로 넣기'·§4.7.7).

A. 메뉴 자리 — '클립보드 붙여넣기' 바로 아래, 편집모드가 아니면 끈 채로 '(편집모드 ✏ 에서)'
B. 가로 쪽(2쪽) 아래에 넣으면 그 쪽 크기(842×595)의 흰 쪽 — 글 없음, 흰색, 미저장 끼운 쪽
C. 넣은 뒤 **새 흰 쪽**만 골라지고 본문도 그 쪽(사용자 결정 — 붙여넣기와 다른 예외)
D. 끼운 쪽을 기준으로 또 넣으면 그 원본 쪽 크기
E. 새 쪽에 꾸밈을 넣고 [저장] → 원본 PDF 에 들어가고(`_finalize_save` 길) 꾸밈이 그 쪽 번호에 남는다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_blankpage261021_%d" % os.getpid())

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
    seen.append([(x.text().split("\t")[0], x.isEnabled()) for x in self.actions() if not x.isSeparator()])
    return next((x for x in self.actions() if pick["t"] and x.text().split("\t")[0].startswith(pick["t"])), None)


def menu_at(pt, row, choose=None):
    pick["t"] = choose
    pt.list.clearSelection(); pt.list.item(row).setSelected(True)
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(row)).center()); spin(0.4)
    return seen[-1]


root = Path(tempfile.mkdtemp(prefix="blankpage261021_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i, (w, h) in enumerate([(595, 842), (842, 595), (595, 842)]):
        d.new_page(width=w, height=h).insert_text((72, 300), "A P%d" % (i + 1))
    d.save(str(a)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    mv, pt = mw.main_view, mw.page_thumbs
    QMenu.exec = fake_exec

    # A — 메뉴 자리·켜짐
    if bt.is_edit_mode():
        bt.btn_edit.setChecked(False); spin(0.3)
    mv, pt = mw.main_view, mw.page_thumbs
    L = menu_at(pt, 1)
    names = [t for t, _e in L]
    ib = next((i for i, t in enumerate(names) if t.startswith("새 페이지 넣기")), -1)
    ic = next((i for i, t in enumerate(names) if t.startswith("클립보드 붙여넣기")), -1)
    chk(ib >= 0 and ib == ic + 1, "A1 '새 페이지 넣기' 는 '클립보드 붙여넣기' 바로 아래", str(names))
    chk(ib >= 0 and not L[ib][1] and "(편집모드 ✏ 에서)" in L[ib][0], "A2 편집모드가 아니면 끈 채로 까닭을 이름에", str(L[ib] if ib >= 0 else None))
    bt.btn_edit.setChecked(True); spin(0.4)
    mv, pt = mw.main_view, mw.page_thumbs
    L = menu_at(pt, 1)
    ib = next((i for i, (t, _e) in enumerate(L) if t.startswith("새 페이지 넣기")), -1)
    chk(ib >= 0 and L[ib][1] and L[ib][0] == "새 페이지 넣기 — p.2 뒤", "A3 편집모드면 켜지고 자리(p.2 뒤)를 보인다", str(L[ib] if ib >= 0 else None))

    # B·C — 가로 쪽(행 1) 아래
    menu_at(pt, 1, "새 페이지 넣기"); spin(0.4)
    chk(pt.list.count() == 4, "B1 쪽이 하나 늘었다", str(pt.list.count()))
    v = pt.list.item(2).data(Qt.ItemDataRole.UserRole) if pt.list.count() > 2 else None
    chk(isinstance(v, (tuple, list)) and len(v) >= 3, "B2 기준 아래(행 2)에 끼운 쪽(미저장)", str(v))
    if isinstance(v, (tuple, list)):
        bd = fitz.open(str(v[0])); bp = bd[int(v[1])]
        chk((round(bp.rect.width), round(bp.rect.height)) == (842, 595), "B3 기준 쪽(가로) 크기 842×595", str(bp.rect))
        chk(bp.get_text("text").strip() == "", "B4 글이 없다")
        px = bp.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        chk(px.pixel(px.width // 2, px.height // 2)[:3] == (255, 255, 255), "B5 흰색")
        bd.close()
        chk(pt.is_page_dirty(), "B6 미저장 표시")
        rows = sorted(pt.list.row(it) for it in pt.list.selectedItems())
        chk(rows == [2], "C1 새 흰 쪽만 골라진다(사용자 결정)", str(rows))
        chk(int(mv.current_page()) == pt.STAGED_BASE + int(v[2]), "C2 본문도 새 흰 쪽", str(mv.current_page()))

        # D — 끼운 쪽(행 2) 기준으로 또 — 원본 크기
        menu_at(pt, 2, "새 페이지 넣기"); spin(0.4)
        v2 = pt.list.item(3).data(Qt.ItemDataRole.UserRole)
        d2 = fitz.open(str(v2[0]))
        chk((round(d2[int(v2[1])].rect.width), round(d2[int(v2[1])].rect.height)) == (842, 595),
            "D 끼운 쪽 기준이면 그 원본 쪽 크기", str(d2[int(v2[1])].rect))
        d2.close()
        pt.list.clearSelection(); pt.list.item(3).setSelected(True); pt._delete_selected(); spin(0.3)

        # E — 새 쪽에 꾸밈 → 저장
        mv.go_to_page(pt.STAGED_BASE + int(v[2])); spin(0.4)
        mv._page_strokes = [{"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "BLANK", "size_pt": 12}]
        mv._save_page_strokes(); mw._edit_dirty = True
        mw._save_current_file(); spin(4.0)
        sd = fitz.open(str(a))
        chk(sd.page_count == 4 and (round(sd[2].rect.width), round(sd[2].rect.height)) == (842, 595),
            "E1 저장하면 원본 PDF 3번째 자리에 흰 쪽", str([p.rect for p in sd]))
        sd.close()
        st = mw._ensure_page_meta_store()
        chk([s.get("text") for s in st.get_drawings(str(a), 2)] == ["BLANK"], "E2 새 쪽의 꾸밈이 저장 뒤 그 쪽에 남는다",
            str({pg: [s.get("text") for s in st.get_drawings(str(a), pg)] for pg in range(4)}))
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
