# -*- coding: utf-8 -*-
"""261008-6: 책갈피 '모두 펼치기' — 보이는 파일들의 책갈피를 펼치는 **상태**, 멈추지 않게 (마스터 §4.7.3, 응답성 SOT §4.4).

사용자 보고: "책갈피 모두 펼치기를 했더니 창에 아무런 변화가 없다가 크래쉬됐어."
(이벤트 로그 AppHangB1 — 예외가 아니라 메인 스레드 정지. 재현: 읽지 않은 파일은 아무 변화 없음, 책갈피 4,500개 15.6초.)
사용자 지시: "모두 펼치기/접기는 파일 내부의 책갈피를 펼치거나 접는 것. 시간이 많이 걸리면 현재 보고 있는 창의 리스트만
적용하고, 리스트가 업데이트되면 다시 적용. 모두 펼치기 모드에서는 책갈피 창에 보이는 파일들이 모두 책갈피가 펼쳐져 보이도록."

A. 모두 펼치기 → 보이는 파일들(아직 읽지 않은 것 포함)의 책갈피가 모두 펼쳐진다 · 보이지 않는 파일은 읽지 않는다
B. 스크롤해서 새로 보이는 파일도 펼친다 · 목록을 다시 읽어도(↻) 다시 펼친다
C. 모두 접기 → 상태가 꺼지고 읽어 둔 파일의 책갈피가 접힌다 · 그 뒤 스크롤해도 펼치지 않는다
D. 상태 중 사용자가 직접 접은 파일은 다시 펼치지 않는다
E. 멈추지 않는다 — 책갈피 4,500개 파일도 한 틱이 1초 안(종전 15.6초), 틱 사이에 이벤트가 돈다(하트비트)
F. 우클릭 메뉴의 '책갈피 모두 펼치기' 가 상태를 체크로 보여 준다
"""
import os, sys, time, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer, QElapsedTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=600):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(10)


def make(p, n_top, pages=40):
    d = fitz.open()
    for _ in range(pages):
        d.new_page()
    toc = []
    for i in range(n_top):
        toc += [[1, f"장{i}", 1 + i % pages], [2, f"절{i}", 1 + i % pages], [3, f"항{i}", 1 + i % pages]]
    if toc:
        d.set_toc(toc)
    d.save(p); d.close()
    return len(toc)


root = tempfile.mkdtemp(prefix="polypdf_expand_")
try:
    from viewer.widgets.bookmark_tree import BookmarkTree
    for i in range(60):                                   # 파일 60개: 대부분 작은 책갈피, 몇 개는 없음
        make(os.path.join(root, f"f{i:02d}.pdf"), 0 if i % 7 == 3 else 3)
    big_n = make(os.path.join(root, "a_큰목차.pdf"), 1500, pages=200)   # 이름 순 맨 위
    bt = BookmarkTree(); bt.resize(320, 600); bt.show(); app.processEvents()
    bt.set_tree_view(False)
    bt.load_folder(root); spin(800)
    files = list(bt._iter_file_nodes())
    chk(len(files) == 61, "준비 — 파일 61개", str(len(files)))
    loaded_before = sum(1 for n in files if n.data(0, bt.DATA_TOC_LOADED))
    chk(loaded_before == 0, "준비 — 아직 아무 파일도 책갈피를 읽지 않았다", str(loaded_before))

    def subtree_open(n):
        st = [n.child(k) for k in range(n.childCount())]
        while st:
            c = st.pop()
            if c.childCount() and not c.isExpanded():
                return False
            st.extend(c.child(k) for k in range(c.childCount()))
        return n.isExpanded() or n.childCount() == 0

    # E 준비 — 하트비트로 가장 긴 멈춤을 잰다
    beat = QElapsedTimer(); beat.start(); worst = [0]

    def tick():
        worst[0] = max(worst[0], beat.restart())
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(tick); hb.start()

    # ── A ──
    bt.tree.scrollToTop(); spin(100)
    worst[0] = 0; beat.restart()
    bt._op_expand_all(True); spin(1500)
    big = files[0] if files[0].text(0).startswith("a_") else next(n for n in files if n.text(0).startswith("a_"))
    chk(big.data(0, bt.DATA_TOC_LOADED) and subtree_open(big),
        "A 보이는(맨 위) 파일 — 읽지 않았던 큰 목차도 읽어 모두 펼친다(종전: 아무 변화 없음)")
    n_loaded = sum(1 for n in files if n.data(0, bt.DATA_TOC_LOADED))
    chk(n_loaded < len(files) - 10, "A 보이지 않는 파일은 읽지 않는다(목록 전체를 한꺼번에 열지 않는다)",
        f"읽은 파일 {n_loaded}/{len(files)}")
    chk(worst[0] < 1000, "E 큰 목차(4,500개)를 펼쳐도 가장 긴 멈춤이 1초 안(종전 15.6초 — '응답 없음')", f"{worst[0]}ms")
    print(f"  실측: 가장 긴 멈춤 {worst[0]}ms (책갈피 {big_n}개 파일 포함)")

    # ── B 스크롤 ──
    sb = bt.tree.verticalScrollBar()
    for _ in range(40):                                   # 큰 목차를 지나 아래 파일들이 보일 때까지
        sb.setValue(sb.maximum()); spin(150)
        vis = bt._visible_file_items()
        if vis and all(v is not big for v in vis):
            break
    vis = bt._visible_file_items()
    chk(vis and all(v.data(0, bt.DATA_ALL_EXPANDED) for v in vis)
        and all(subtree_open(v) for v in vis if v.childCount()),
        "B 스크롤해서 새로 보이는 파일들도 펼친다", f"{[v.text(0) for v in vis if not subtree_open(v)][:3]}")

    # ── D 사용자가 접은 파일 ──
    user_closed = next((v for v in vis if v.childCount()), None)
    if user_closed is not None:
        user_closed.setExpanded(False); spin(300)
        chk(not user_closed.isExpanded(), "D 상태 중 사용자가 접은 파일은 다시 펼치지 않는다")

    # ── B 목록 다시 읽기 ──
    bt.refresh(); spin(1200)
    bt.tree.scrollToTop(); spin(800)
    vis = bt._visible_file_items()
    chk(bt.is_expand_all_mode() and vis and all(subtree_open(v) for v in vis if v.childCount()),
        "B 목록을 다시 읽어도(↻) 보이는 파일을 다시 펼친다")

    # ── F 메뉴 체크 ──
    seen = {}

    def fake_exec(menu, *a, **k):
        for x in menu.actions():
            if x.text() == "책갈피 모두 펼치기":
                seen["checked"] = x.isCheckable() and x.isChecked()
        return None
    QMenu.exec = fake_exec
    it0 = bt._visible_file_items()[0]
    bt._on_tree_context_menu(bt.tree.visualItemRect(it0).center())
    chk(seen.get("checked") is True, "F 우클릭 메뉴가 '모두 펼치기' 상태를 체크로 보여 준다")

    # ── C 모두 접기 ──
    worst[0] = 0; beat.restart()
    bt._op_expand_all(False); spin(300)
    loaded = [n for n in bt._iter_file_nodes() if n.data(0, bt.DATA_TOC_LOADED)]
    def deep_closed(n):
        st = [n.child(k) for k in range(n.childCount())]
        while st:
            c = st.pop()
            if c.isExpanded():
                return False
            st.extend(c.child(k) for k in range(c.childCount()))
        return True
    chk(not bt.is_expand_all_mode() and loaded and all(deep_closed(n) for n in loaded),
        "C 모두 접기 → 상태가 꺼지고 읽어 둔 파일의 책갈피가 접힌다")
    chk(worst[0] < 1000, "E 모두 접기도 1초 안", f"{worst[0]}ms")
    sb.setValue(sb.maximum() // 2); spin(500)
    chk(all(deep_closed(n) for n in bt._visible_file_items()), "C 꺼진 뒤 스크롤해도 펼치지 않는다")
    hb.stop()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
