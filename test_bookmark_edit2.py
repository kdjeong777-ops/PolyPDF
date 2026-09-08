# -*- coding: utf-8 -*-
"""260908-1: 책갈피창 편집 7건 + 본문 회전 + OCR 안내 (마스터 SOT §4.7).

사용자 요청(260908):
  ① 책갈피 추가 시 **레벨 선택**. 기본값 = 윗 책갈피와 같은 레벨
  ② 레벨 조정 뒤 **조정한 책갈피**가 선택돼 있어야 한다(본화면이 상부로 튀지 않게)
  ③ 고른 책갈피 **아래**에 추가
  ④ 추가 뒤 **그 하나만** 선택
  ⑤ 우클릭에 모두 펼치기/모두 접기
  ⑥ 우클릭에 선택 책갈피 **페이지순 정렬**(하위 포함, 레벨은 윗 책갈피에 맞춤)
  ⑦ 저장은 **원본 파일**에(못 하면 알린다)
  ⑧ 본문 우클릭에 좌/우 90° 회전
  ⑨ OCR 학습 데이터가 없으면 **사람이 읽을 안내**
"""
import os, sys, inspect, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
import test_fixtures as _fx
from viewer.widgets.bookmark_tree import BookmarkTree

root = Path(tempfile.mkdtemp(prefix="polypdf_bm2_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)


def flat(node, depth=0, out=None):
    out = [] if out is None else out
    for i in range(node.childCount()):
        c = node.child(i)
        out.append((depth, c.text(0).split("  (p.")[0], c.data(0, 0x0101)))
        flat(c, depth + 1, out)
    return out


try:
    bt = BookmarkTree()
    bt.resize(360, 700)
    bt.show()
    bt.load_folder(root)
    app.processEvents()
    fn = next(iter(bt._iter_file_nodes()))
    fn.setExpanded(True)
    app.processEvents()
    bt._edit_mode = True
    chk(fn.childCount() > 0, "파일 노드에 책갈피가 있다", f"{fn.childCount()}개")

    def rows():
        out = []

        def walk(node, d=0):
            for i in range(node.childCount()):
                c = node.child(i)
                out.append((d, c.text(0)[:20], c.data(0, bt.DATA_PAGE)))
                walk(c, d + 1)
        walk(fn)
        return out

    # ── ② 레벨 조정 뒤 조정한 책갈피가 선택된다 ─────────────────────────
    second = fn.child(1)
    name2 = second.text(0)[:12]
    bt.tree.clearSelection(); second.setSelected(True); bt.tree.setCurrentItem(second)
    signals = {"n": 0}
    bt.tree.currentItemChanged.connect(lambda *a: signals.__setitem__("n", signals["n"] + 1))
    bt._op_indent()
    app.processEvents()
    cur = bt.tree.currentItem()
    chk(cur is second, "② 들여쓰기 뒤 조정한 책갈피가 현재 항목이다",
        cur.text(0)[:12] if cur else "없음")
    chk(signals["n"] == 0,
        "② 조정 중에 이동 신호가 새지 않는다(본화면이 상부로 안 튄다)",
        f"{signals['n']}회")
    bt._op_outdent()
    app.processEvents()
    chk(bt.tree.currentItem() is second, "② 내어쓰기 뒤에도 그대로")

    # ── ①③④ 추가: 레벨·자리·선택 ───────────────────────────────────────
    anchor = fn.child(2)
    bt.tree.clearSelection(); anchor.setSelected(True)
    base, top = bt.suggest_add_level(str(pdf))
    chk(base >= 1 and top == base + 1,
        "① 기본 레벨 = 윗 책갈피와 같은 단계, 한 단계 아래까지 고를 수 있다",
        f"기본 {base} / 최대 {top}")
    n0 = len(rows())
    bt.add_bookmark(str(pdf), 7, "형제로 넣기", level=1)
    app.processEvents()
    made = bt.tree.selectedItems()
    chk(len(made) == 1 and made[0].text(0).startswith("형제로 넣기"),
        "④ 넣은 하나만 선택된다", f"{len(made)}개 선택")
    sib = made[0]
    chk(sib.parent() is anchor.parent(),
        "① 레벨 1 = 고른 것과 같은 단계(형제)")
    chk((sib.parent() or fn).indexOfChild(sib)
        == (anchor.parent() or fn).indexOfChild(anchor) + 1,
        "③ 고른 책갈피 **바로 아래**에 들어간다")

    bt.tree.clearSelection(); anchor.setSelected(True)
    bt.add_bookmark(str(pdf), 8, "하위로 넣기", level=2)
    app.processEvents()
    sub = bt.tree.selectedItems()[0]
    chk(sub.parent() is anchor, "① 레벨 2 = 고른 것의 하위")
    chk(len(bt.tree.selectedItems()) == 1, "④ 두 번째 추가도 하나만 선택")
    chk(len(rows()) == n0 + 2, "③ 두 개가 실제로 들어갔다")

    # ── ⑤ 모두 펼치기 / 접기 ────────────────────────────────────────────
    bt._op_expand_all(False)
    kids = [fn.child(i) for i in range(fn.childCount())]
    chk(all(not k.isExpanded() for k in kids if k.childCount()),
        "⑤ 모두 접기 — 하위가 있는 책갈피가 다 접힌다")
    chk(fn.isExpanded(), "⑤ 파일 노드는 접지 않는다(목록에서 사라지지 않게)")
    bt._op_expand_all(True)
    chk(all(k.isExpanded() for k in kids if k.childCount()),
        "⑤ 모두 펼치기 — 다 펼쳐진다")

    # ── ⑥ 페이지순 정렬 ─────────────────────────────────────────────────
    #   서로 다른 페이지의 책갈피 셋을 뒤죽박죽 만든 뒤 정렬
    from PyQt6.QtWidgets import QTreeWidgetItem
    holder = QTreeWidgetItem(["정렬대상"])
    holder.setData(0, bt.DATA_FILE, str(pdf))
    holder.setData(0, bt.DATA_PAGE, 20)
    fn.addChild(holder)
    for title, pg in (("나중쪽", 25), ("앞쪽", 21), ("중간쪽", 23)):
        c = QTreeWidgetItem([f"{title}  (p.{pg})"])
        c.setData(0, bt.DATA_FILE, str(pdf))
        c.setData(0, bt.DATA_PAGE, pg - 1)
        holder.addChild(c)
    bt.tree.clearSelection(); holder.setSelected(True)
    bt._op_sort_by_page()
    app.processEvents()
    # 이 검사가 넣은 넷만 본다(원본 책갈피와 섞이지 않게 제목으로 고른다)
    want = ("정렬대상", "나중쪽", "앞쪽", "중간쪽")
    after = [(d, t, p) for d, t, p in rows() if t.split("  (p.")[0] in want]
    pages = [p for _d, _t, p in after]
    chk(len(after) == 4 and pages == sorted(pages),
        "⑥ 페이지 오름차순으로 늘어선다", str([(t.split('  (p.')[0], p) for _d, t, p in after]))
    depths = {d for d, _t, _p in after}
    chk(len(depths) == 1, "⑥ 레벨이 윗 책갈피와 같게(한 줄로) 맞춰진다", str(depths))

    # ── ⑦⑧⑨ 배선 확인 ──────────────────────────────────────────────────
    from viewer.app import MainWindow
    fin = inspect.getsource(MainWindow._finalize_save)
    chk("for _i in range(" in fin and "sleep" in fin,
        "⑦ 원본 덮어쓰기를 여러 번 다시 시도한다(핸들이 늦게 풀려도)")
    chk("QMessageBox.warning" in fin,
        "⑦ 끝내 못 덮어쓰면 다른 이름으로 저장했음을 알린다")
    menu_src = inspect.getsource(MainWindow._on_viewer_context_menu)
    chk("왼쪽 90° 회전" in menu_src and "오른쪽 90° 회전" in menu_src,
        "⑧ 본문 우클릭에 좌/우 90° 회전이 있다")
    chk("_rotate_pages" in menu_src, "⑧ 썸네일과 같은 회전 경로를 쓴다")
    from viewer.study import ocr as _ocr
    chk(callable(getattr(_ocr, "missing_language", None)),
        "⑨ OCR 학습 데이터 안내 진입점이 있다")
    src_ocr = inspect.getsource(_ocr.ensure_tesseract)
    chk("kor.traineddata" in src_ocr,
        "⑨ tessdata 후보 중 **한국어가 든 쪽**을 고른다(옛 설치본 대비)")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
