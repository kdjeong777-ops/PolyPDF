# -*- coding: utf-8 -*-
"""'#' 거르기 개수 = 지금 목록 기준, 거르기 결과가 비면 알림 (검색 SOT §5.1, 261107-9 사용자 보고).

사용자 보고: "해시테그에 영수증의 갯수가 있다고 했는데, 실제 해시테그로 검색하니 리스트에 없어. 그런데, 그 상태에서
썸네일화 화면이 이전 화면이 표시되". 원인: 풀다운 개수는 태그 저장소 전체(다른 폴더·사진)를 셌고(`tag_counts`), 거르기는
지금 목록의 줄만 본다 — 다른 곳에만 있는 '#영수증 (8)' 을 고르면 목록이 비었다.
A. 풀다운 개수 — 지금 목록의 파일만 센다, 목록에 없는 태그는 늘어놓지 않는다(검색 칸에 있으면 (0) 으로 남겨 풀 수 있게)
B. 고른 개수만큼 목록에 남는다(실제 체크 상자 → 검색 칸 → _on_filter)
C. 결과가 비면 목록 자리에 알림, 다시 보이면 사라진다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QCheckBox, QWidgetAction
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_filter_count_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=500):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(10)


def pdf(p):
    d = fitz.open(); d.new_page(); d.save(p); d.close()


root = tempfile.mkdtemp(prefix="polypdf_tagcount_")
try:
    from viewer.widgets.bookmark_tree import BookmarkTree
    from viewer.tag_store import TagStore
    here, other = os.path.join(root, "docs"), os.path.join(root, "elsewhere")
    os.makedirs(here); os.makedirs(other)
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        pdf(os.path.join(here, n))
    ts = TagStore(os.path.join(root, "tags.json"))
    ts.set(os.path.join(here, "a.pdf"), ["보고서"])
    ts.set(os.path.join(here, "b.pdf"), ["보고서", "기사"])
    for i in range(8):                                   # 다른 폴더(·사진)에만 있는 #영수증 8개
        ts.set_auto_part(os.path.join(other, "IMG_%d.jpg" % i), "kind", ["영수증"])

    bt = BookmarkTree(); bt.resize(320, 600); bt.show(); app.processEvents()
    bt._tags = ts
    bt.set_tree_view(False)
    bt.load_folder(here); spin(800)
    chk(len(list(bt._iter_file_nodes())) == 3, "준비 — 목록 파일 3개")

    def menu_items():
        bt._rebuild_tag_menu()
        out = {}
        for act in bt._tag_menu.actions():
            if isinstance(act, QWidgetAction) and act.defaultWidget() is not None:
                for c in act.defaultWidget().findChildren(QCheckBox):
                    t = c.text().strip()
                    out[t.split()[0].lstrip("#")] = (int(t.rsplit("(", 1)[1].rstrip(")")), c)
        return out

    def visible():
        return sorted(os.path.basename(str(it.data(0, bt.DATA_FILE))) for it in bt._iter_file_nodes() if not it.isHidden())

    # A
    m = menu_items()
    chk({k: v[0] for k, v in m.items()} == {"보고서": 2, "기사": 1}, "A 개수는 지금 목록의 파일만 — 다른 폴더의 #영수증 은 없다",
        str({k: v[0] for k, v in m.items()}))

    # B 고른 개수만큼 남는다
    for tag in list(m):
        n, cb = menu_items()[tag]                        # 풀다운은 열 때마다 새로 만든다
        cb.setChecked(True); spin(50)
        chk(len(visible()) == n, "B #%s (%d) 를 고르면 %d개가 남는다" % (tag, n, n), str(visible()))
        cb = menu_items()[tag][1]
        cb.setChecked(False); spin(50)
    chk(bt.search_edit.text().strip() == "" and len(visible()) == 3, "B 풀면 모두 보인다", bt.search_edit.text())

    # C 빈 결과 — 손으로 친 #영수증(다른 폴더에만 있음)
    bt.search_edit.setText("#영수증"); spin(100)
    lbl = bt.__dict__.get("_no_match_lbl")
    chk(visible() == [] and lbl is not None and lbl.isVisible() and "#영수증" in lbl.text(),
        "C 결과가 비면 목록 자리에 알림(무엇으로 걸렀는지)", str(lbl.text() if lbl else None))
    m = menu_items()
    chk("영수증" in m and m["영수증"][0] == 0 and m["영수증"][1].isChecked(), "A 검색 칸의 태그는 (0) 으로 남아 풀 수 있다", str(list(m)))
    m["영수증"][1].setChecked(False); spin(50)
    chk(len(visible()) == 3 and not lbl.isVisible(), "C 다시 보이면 알림이 사라진다")
    bt.search_edit.setText("없는이름"); spin(100)
    chk(lbl.isVisible(), "C 글자 거르기도 비면 알림")
    bt.search_edit.setText(""); spin(100)
    chk(not lbl.isVisible(), "C 검색 칸을 비우면 알림 없음")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
