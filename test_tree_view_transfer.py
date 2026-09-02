# -*- coding: utf-8 -*-
"""260901-2: 책갈피 트리 — 단일/트리 보기, 폴더 그룹 행, 파일 복사/이동.

검사 대상(사용자 요청):
  ① '다중/단일' 토글 폐지 → 선택은 항상 다중 가능
  ② 같은 자리에 '단일/트리' 보기 전환 버튼
  ③ 트리 보기: 폴더 행(옅은 노랑 배경·굵게·폴더 아이콘) 아래 한 단계 들여쓴 파일
  ④ 우클릭 '파일 복사'/'파일 이동' — 선택 폴더·하위 폴더·새 폴더로
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QMenu

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

# ── 표본 폴더: 루트 2개 + sub_a 2개 + sub_a/deep 1개 + sub_b 1개 ──────────
root = Path(tempfile.mkdtemp(prefix="polypdf_tree_"))
def mkpdf(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open(); d.new_page().insert_text((40, 80), p.stem); d.save(str(p)); d.close()

for rel in ["r1.pdf", "r2.pdf", "sub_a/a1.pdf", "sub_a/a2.pdf",
            "sub_a/deep/d1.pdf", "sub_b/b1.pdf"]:
    mkpdf(root / rel)

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.bookmark_tree import BookmarkTree
bt = BookmarkTree(); bt.resize(300, 700); bt.show(); app.processEvents()
bt.load_folder(root); app.processEvents()

# ── ① 선택은 항상 다중 ────────────────────────────────────────────────
chk(not hasattr(bt, "btn_sel_mode"), "① '다중/단일' 토글 제거됨")
chk(bt.tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection,
    "① 비편집 — ExtendedSelection")
bt.set_edit_mode(True); app.processEvents()
chk(bt.tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection,
    "① 편집모드 — ExtendedSelection(항상 다중)")

# ── ② 보기 전환 버튼(같은 자리 = edit_ops 1행 첫 버튼) ─────────────────
row1 = bt.edit_ops.layout().itemAt(0).widget()
first = row1.layout().itemAt(0).widget()
chk(first is bt.btn_view_mode, "② 보기 전환 버튼이 1행 첫 자리(옛 토글 위치)")
# 260901-2(사용자 지정): **트리가 기본**
chk(bt.is_tree_view() and bt.btn_view_mode.text() == "트리", "② 기본 보기 = 트리")

# ── ③ 단일 보기로 전환 = 평탄 6개 ─────────────────────────────────────
bt._toggle_tree_view(); app.processEvents()
chk(not bt.is_tree_view() and bt.btn_view_mode.text() == "단일", "③ 단일 보기 전환·라벨")
chk(bt.tree.topLevelItemCount() == 6, "③ 단일 보기 — 6개 파일이 한 위계",
    f"count={bt.tree.topLevelItemCount()}")
chk(len(list(bt._iter_file_nodes())) == 6, "③ _iter_file_nodes 6개(단일)")

# ── ③ 트리 보기 복귀 ──────────────────────────────────────────────────
bt._toggle_tree_view(); app.processEvents()
chk(bt.is_tree_view() and bt.btn_view_mode.text() == "트리", "③ 트리 보기 전환·라벨")

tops = [bt.tree.topLevelItem(i) for i in range(bt.tree.topLevelItemCount())]
folders = [t for t in tops if bt._is_folder_node(t)]
rootfiles = [t for t in tops if bt._is_file_node(t)]
chk([f.text(0) for f in folders] == ["sub_a", "sub_b"],
    "③ 폴더 그룹이 이름 순으로 먼저", f"{[f.text(0) for f in folders]}")
chk(len(rootfiles) == 2, "③ 루트 직속 파일 2개는 폴더 뒤에", f"n={len(rootfiles)}")
chk(len(list(bt._iter_file_nodes())) == 6, "③ 트리 보기에서도 파일 노드 6개(누락 없음)")

fa = folders[0]
kids_f = [fa.child(i) for i in range(fa.childCount())]
chk(any(bt._is_folder_node(k) and k.text(0) == "deep" for k in kids_f),
    "③ 하위 폴더는 계층 그대로 중첩(sub_a > deep)")
# (파일 순서는 정렬 콤보를 따른다 — 기본 '수정일 순'이므로 이름 순을 가정하지 않는다)
files_a = sorted(k.text(0) for k in kids_f if bt._is_file_node(k))
chk(files_a == ["a1", "a2"], "③ 폴더의 파일은 그 폴더 행의 자식(한 단계 들여쓰기)", f"{files_a}")

# 폴더 행 표시(디자인 §2.5): 옅은 노랑 배경 + 어두운 글자 + 굵게 + 아이콘
chk(fa.background(0).color().name() == bt.FOLDER_ROW_BG.lower(),
    "③ 폴더 행 배경 = 옅은 노랑", f"{fa.background(0).color().name()}")
chk(fa.foreground(0).color().name() == bt.FOLDER_ROW_FG.lower(), "③ 폴더 행 글자색")
chk(fa.font(0).bold(), "③ 폴더 행 굵게")
chk(not fa.icon(0).isNull(), "③ 폴더 행 앞 폴더 아이콘")
chk(not fa.data(0, bt.DATA_FILE), "③ 폴더 행은 파일 노드가 아님(오작동 방지)")

# 파일 노드 판별 헬퍼 계약
a1 = [k for k in kids_f if bt._is_file_node(k)][0]
chk(bt._file_node_of(a1) is a1 and bt._file_node_of(fa) is None,
    "③ _file_node_of — 파일=자기 자신 / 폴더=None")
chk(sorted(Path(p).name for p in bt.all_file_paths()) ==
    ["a1.pdf", "a2.pdf", "b1.pdf", "d1.pdf", "r1.pdf", "r2.pdf"],
    "③ all_file_paths 가 트리 보기에서도 전량 반환")

# 필터: 폴더 행은 보이는 자식이 있을 때만 보인다
bt.search_edit.setText("a1"); app.processEvents()
chk(not fa.isHidden() and folders[1].isHidden(),
    "③ 필터 — 매치 없는 폴더 행 숨김 / 있는 폴더는 표시")
bt.search_edit.setText(""); app.processEvents()
chk(not folders[1].isHidden(), "③ 필터 해제 → 폴더 행 복귀")

# ── ④ 복사 / 이동 ─────────────────────────────────────────────────────
# 자동 확인용 — QMessageBox 를 우회(오프스크린에서 모달 대기 방지)
from PyQt6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

dst = root / "sub_b"

bt._transfer_files([root / "r1.pdf"], dst, False)                  # 복사
app.processEvents()
chk((dst / "r1.pdf").exists() and (root / "r1.pdf").exists(),
    "④ 복사 — 대상에 생기고 원본 유지")
chk(len(list(bt._iter_file_nodes())) == 7, "④ 복사 후 목록 7개로 갱신",
    f"n={len(list(bt._iter_file_nodes()))}")

moved = []
bt.filesRelocated.connect(lambda pairs: moved.extend(pairs))
bt._transfer_files([root / "r2.pdf"], root / "sub_a", True)        # 이동
app.processEvents()
chk((root / "sub_a" / "r2.pdf").exists() and not (root / "r2.pdf").exists(),
    "④ 이동 — 원본이 실제로 옮겨짐")
chk(any(o.endswith("r2.pdf") and n.endswith("r2.pdf") for o, n in moved),
    "④ filesRelocated 로 (old,new) 통지", f"{moved}")
chk(len(list(bt._iter_file_nodes())) == 7, "④ 이동 후 목록 개수 유지(중복 없음)")
sub_a_node = [bt.tree.topLevelItem(i) for i in range(bt.tree.topLevelItemCount())
              if bt._is_folder_node(bt.tree.topLevelItem(i))
              and bt.tree.topLevelItem(i).text(0) == "sub_a"][0]
chk(any(k.text(0) == "r2" for k in
        (sub_a_node.child(i) for i in range(sub_a_node.childCount()))),
    "④ 옮긴 파일이 대상 폴더 행 아래로 재배치")

# 같은 폴더로 이동은 무동작
before = len(list(bt._iter_file_nodes()))
bt._transfer_files([root / "sub_a" / "r2.pdf"], root / "sub_a", True)
chk(len(list(bt._iter_file_nodes())) == before, "④ 같은 폴더로 이동은 무동작")

# 새 폴더 만들기
from PyQt6.QtWidgets import QInputDialog
QInputDialog.getText = staticmethod(lambda *a, **k: ("새자료", True))
nd = bt._ask_new_folder()
chk(nd is not None and nd.exists() and nd.name == "새자료", "④ 새 폴더 만들기")

# 우클릭 메뉴 구성 — 편집모드에서 '파일 복사/이동' 서브메뉴가 붙는다
# (복사/이동이 목록을 다시 그리므로 노드는 그때그때 다시 찾는다 — 옛 참조는 무효)
menu = QMenu()
node = next(iter(bt._iter_file_nodes()))
bt.tree.setCurrentItem(node); node.setSelected(True)
bt._add_transfer_submenu(menu, "파일 복사 (1개)", [node], False)
sub = [ac.menu() for ac in menu.actions() if ac.menu()][0]
labels = [ac.text() for ac in sub.actions() if ac.text()]
chk(any("sub_b" in s for s in labels), "④ 서브메뉴에 하위 폴더 후보", f"{labels[:4]}")
chk("새 폴더 만들기..." in labels and "다른 폴더 선택..." in labels,
    "④ 서브메뉴에 '새 폴더 만들기'·'다른 폴더 선택'")
# 260901-4: 두 항목이 **맨 위** 두 줄
chk(labels[:2] == ["새 폴더 만들기...", "다른 폴더 선택..."],
    "④ '새 폴더 만들기'·'다른 폴더 선택'이 맨 위", f"{labels[:3]}")

# 260901-4: 기준 폴더 = 선택한 파일이 있는 세부 폴더
deep_pdf = root / "sub_a" / "deep" / "d1.pdf"
chk(bt._source_folder_of([deep_pdf]) == deep_pdf.parent,
    "④ 기준 폴더 = 선택 파일의 세부 폴더")
QInputDialog.getText = staticmethod(lambda *a, **k: ("하위신설", True))
nd2 = bt._ask_new_folder(base=bt._source_folder_of([deep_pdf]))
chk(nd2 == deep_pdf.parent / "하위신설" and nd2.is_dir(),
    "④ '새 폴더 만들기' — 그 세부 폴더 아래에 생성", f"{nd2}")
seen_start = {}
from PyQt6.QtWidgets import QFileDialog
QFileDialog.getExistingDirectory = staticmethod(
    lambda parent, title, start="", *a, **k: (seen_start.setdefault("s", start), "")[1])
bt._ask_pick_folder(False, start=bt._source_folder_of([deep_pdf]))
chk(seen_start.get("s") == str(deep_pdf.parent),
    "④ '다른 폴더 선택' — 그 세부 폴더에서 열림", f"{seen_start.get('s')}")

# ── ⑤ 폴더 이름 변경 / 삭제 (260901-3) ───────────────────────────────
QInputDialog.getText = staticmethod(lambda *a, **k: ("보고서모음", True))
target = root / "sub_b"
n_before = len(list(bt._iter_file_nodes()))
renamed = []
bt.filesRelocated.connect(lambda pairs: renamed.extend(pairs))
bt._rename_folder(target)
app.processEvents()
chk((root / "보고서모음").is_dir() and not target.exists(), "⑤ 폴더 이름 변경")
chk((root / "보고서모음" / "b1.pdf").exists(), "⑤ 안의 파일이 새 폴더로 따라옴")
chk(any("보고서모음" in n for _o, n in renamed),
    "⑤ 폴더 안 파일도 filesRelocated 로 통지(인덱스·태그 갱신)", f"{len(renamed)}건")
chk(len(list(bt._iter_file_nodes())) == n_before, "⑤ 이름 변경 후 파일 수 유지")
names = [bt.tree.topLevelItem(i).text(0) for i in range(bt.tree.topLevelItemCount())]
chk("보고서모음" in names, "⑤ 트리의 폴더 행 이름도 갱신", f"{names}")

# 비지 않은 폴더는 삭제 거부
bt._delete_folder(root / "보고서모음")
chk((root / "보고서모음").is_dir(), "⑤ 파일이 든 폴더는 삭제 거부(자료 보호)")

# 빈 폴더는 삭제
empty = root / "빈폴더"; empty.mkdir()
bt._sync_after_transfer(root)
bt._delete_folder(empty)
chk(not empty.exists(), "⑤ 빈 폴더는 삭제")

# ── ⑥ 보기 모드 설정 저장 (260901-3) ─────────────────────────────────
# set_tree_view(프로그램적)는 조용히, _toggle_tree_view(사용자)만 알린다 — 되먹임 방지
seen = []
bt.viewListModeChanged.connect(lambda on: seen.append(on))
bt.set_tree_view(False)
chk(seen == [], "⑥ 프로그램적 전환은 신호 없음(되먹임 방지)")
bt._toggle_tree_view()
chk(seen == [True], "⑥ 사용자 전환만 viewListModeChanged 발신", f"{seen}")

# ── ⑦ 260902-1: 책갈피 자식 판정·동기화·들여쓰기·뷰어 모드 버튼 ─────────
import fitz as _fz
tp = root / "sub_a" / "toc.pdf"
_d = _fz.open()
for _i in range(3): _d.new_page().insert_text((40, 80), f"p{_i}")
_d.set_toc([[1, "첫째", 1], [1, "둘째", 1], [1, "셋째", 2]]); _d.save(str(tp)); _d.close()
bt._sync_after_transfer(root); app.processEvents()
ft = [n for n in bt._iter_file_nodes() if n.text(0).startswith("toc")][0]
ft.setExpanded(True); app.processEvents()
bms = [ft.child(i) for i in range(ft.childCount())]
chk(len(bms) == 3 and not any(bt._is_file_node(b) for b in bms),
    "⑦ 책갈피 자식은 파일 노드가 아님(DATA_FILE 있어도)", f"{[b.text(0) for b in bms]}")
chk(bt._file_node_of(bms[0]) is ft, "⑦ _file_node_of(책갈피) = 소속 파일 노드")
chk(len([n for n in bt._iter_file_nodes() if n is ft]) == 1 and
    not any(n in bms for n in bt._iter_file_nodes()),
    "⑦ _iter_file_nodes 가 책갈피를 파일로 세지 않음")
# 책갈피명 수정 → 책갈피 편집 경로
_called = []
bt._edit_bookmark_node = lambda it, tgt: _called.append(("bm", it.text(0)))
bt._edit_file_node = lambda it: _called.append(("file", it.text(0)))
bt.set_edit_mode(True)
bt.tree.clearSelection(); bt.tree.setCurrentItem(bms[0]); bms[0].setSelected(True)
bt._op_edit_single()
chk(_called == [("bm", "첫째")], "⑦ '책갈피명 수정' → 책갈피 편집(파일명 수정 아님)", f"{_called}")
bt.set_edit_mode(False)
# 페이지 동기가 클릭한 파일/첫 책갈피를 유지(트리 보기)
bt.tree.clearSelection(); bt.tree.setCurrentItem(ft); bt.select_for_page(str(tp), 0)
chk(bt.tree.currentItem() is ft, "⑦ 파일 클릭 후 동기 — 파일 노드 유지")
bt.tree.setCurrentItem(bms[0]); bt.select_for_page(str(tp), 0)
chk(bt.tree.currentItem() is bms[0], "⑦ 같은 페이지 책갈피 2개 — 첫째 클릭 유지")
bt.tree.setCurrentItem(bms[1]); bt.select_for_page(str(tp), 0)
chk(bt.tree.currentItem() is bms[1], "⑦ 같은 페이지 책갈피 2개 — 둘째 클릭 유지")
# 들여쓰기·긴 이름
chk(bt.tree.indentation() == bt.TREE_INDENT == 12, "⑦ 들여쓰기 12px(디자인 §2.8)")
from PyQt6.QtCore import Qt as _Qt
chk(bt.tree.textElideMode() == _Qt.TextElideMode.ElideNone, "⑦ 긴 이름 '…' 자르지 않음(가로 스크롤)")
# 뷰어 모드 버튼: 편집 오른쪽, 편집모드에서 숨김, 라벨 동기
row = bt._edit_row
idx_edit = next(i for i in range(row.count()) if row.itemAt(i).widget() is bt.btn_edit)
chk(row.itemAt(idx_edit + 1).widget() is bt.btn_view_mode_v, "⑦ 뷰어 모드 트리/단일 버튼이 편집 바로 오른쪽")
chk(not bt.btn_view_mode_v.isHidden(), "⑦ 뷰어 모드에서 보임")
bt.set_edit_mode(True); chk(bt.btn_view_mode_v.isHidden(), "⑦ 편집모드에서는 숨김(edit_ops 버튼이 대신)")
bt.set_edit_mode(False)
bt.set_tree_view(False)
chk(bt.btn_view_mode_v.text() == "단일" == bt.btn_view_mode.text(), "⑦ 두 버튼 라벨 동기")
bt.set_tree_view(True)
# 하위 폴더 나열이 파일을 훑지 않음(폴더만·상한)
chk(all(d.is_dir() for d in bt._subfolders()) and len(bt._subfolders()) <= 200,
    "⑦ _subfolders 폴더만·상한 200")

# ── ⑧ 260902-3: 우클릭은 선택만 바꾸고 이동(네비게이션)하지 않는다 ──────
navs = []
bt.bookmarkActivated.connect(lambda f, pg: navs.append(Path(f).name))
QMenu.exec = lambda self, *a, **k: None
for mode in (True, False):
    bt.set_edit_mode(mode)
    files = list(bt._iter_file_nodes())
    bt.tree.clearSelection(); bt.tree.setCurrentItem(files[0])
    app.processEvents(); navs.clear()
    other = files[-1]
    bt._on_tree_context_menu(bt.tree.visualItemRect(other).center())
    from PyQt6.QtTest import QTest; QTest.qWait(150)   # 예약된 이동이 있다면 여기서 발화
    chk(navs == [], f"⑧ {'편집' if mode else '뷰어'}모드 우클릭 — 다른 파일로 이동하지 않음", f"{navs}")
    chk(bt.tree.currentItem() is other and other.isSelected(),
        f"⑧ {'편집' if mode else '뷰어'}모드 우클릭 — 대상 항목은 선택됨(메뉴 동작 기준)")

# ── ⑨ 260902-5: 파일 아이콘·1행 순서·우클릭 메뉴·이동 후 커서 유지 ──────
bt.set_edit_mode(True)
ft = [n for n in bt._iter_file_nodes() if n.text(0).startswith("toc")][0]
chk(not ft.icon(0).isNull(), "⑨ 파일 행 앞 문서 아이콘")
ft.setExpanded(True); app.processEvents()
bms = [ft.child(i) for i in range(ft.childCount())]
chk(all(b.icon(0).isNull() for b in bms), "⑨ 책갈피 행에는 아이콘 없음(구분)")
r1 = bt.edit_ops.layout().itemAt(0).widget().layout()
order = [r1.itemAt(i).widget() for i in range(r1.count())]
chk(order[0] is bt.btn_view_mode and order[1] is bt.btn_edit_single,
    "⑨ 1행 = [트리][책갈피명 수정][◀][▶][▲][▼]", f"{[w.text() for w in order]}")

# 우클릭 메뉴 라벨(편집모드): 파일엔 '책갈피 편집' 없음 / 책갈피엔 '책갈피 수정...'
captured = {}
QMenu.exec = lambda self, *a, **k: (captured.__setitem__("labels", [a_.text() for a_ in self.actions() if a_.text()]), None)[1]
bt._on_tree_context_menu(bt.tree.visualItemRect(ft).center())
chk("책갈피 편집" not in captured["labels"] and "책갈피 생성" in captured["labels"],
    "⑨ 파일 우클릭 — '책갈피 편집' 삭제(생성은 유지)", f"{captured['labels'][:6]}")
bt._on_tree_context_menu(bt.tree.visualItemRect(bms[0]).center())
chk("책갈피 수정..." in captured["labels"], "⑨ 책갈피 우클릭 — '책갈피 수정...' 추가", f"{captured['labels'][:4]}")

# ▲▼ 단일 이동 후 커서 유지
bt.tree.clearSelection(); bt.tree.setCurrentItem(bms[0]); bms[0].setSelected(True)
bt._op_move_down(); app.processEvents()
chk(bt.tree.currentItem() is bms[0] and bms[0].isSelected() and ft.indexOfChild(bms[0]) == 1,
    "⑨ ▼ 단일 이동 후 커서·선택이 옮긴 책갈피에 유지", f"cur={bt.tree.currentItem().text(0) if bt.tree.currentItem() else None}")
bt._op_move_up(); app.processEvents()
chk(bt.tree.currentItem() is bms[0] and ft.indexOfChild(bms[0]) == 0, "⑨ ▲ 복귀 후 커서 유지")
# ▶ 다중 들여쓰기 후 커서·선택 유지
# (Ctrl+클릭 다중 선택과 같게: 현재 항목을 먼저 잡고 나머지를 선택 — setCurrentItem 은 선택을 지운다)
bt.tree.clearSelection(); bt.tree.setCurrentItem(bms[1])
for b in (bms[1], bms[2]): b.setSelected(True)
bt._op_indent(); app.processEvents()
# 트리 순서대로 처리: 둘째→첫째 아래, 셋째→(앞 형제가 된) 첫째 아래
chk(bms[1].parent() is bms[0] and bms[2].parent() is bms[0],
    "⑨ ▶ 다중 들여쓰기 수행", f"p1={bms[1].parent().text(0)} p2={bms[2].parent().text(0)}")
chk(bt.tree.currentItem() is bms[1] and bms[1].isSelected() and bms[2].isSelected(),
    "⑨ ▶ 들여쓰기 후 커서·다중 선택 유지")
bt._op_outdent(); app.processEvents()
chk(bt.tree.currentItem() in (bms[1], bms[2]) and bms[1].isSelected() and bms[2].isSelected(),
    "⑨ ◀ 내어쓰기 후 커서·다중 선택 유지")
bt.set_edit_mode(False)

bt.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
