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

bt.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
