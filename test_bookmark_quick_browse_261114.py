# -*- coding: utf-8 -*-
"""261114-5: 책갈피창 파일 옮김 — 잇단 옮김은 멈춘 파일만, 표지 먼저·나머지는 멈춘 뒤 (응답성 SOT §4.7 ⑤, 책갈피창·저장 SOT §4.7.3).

사용자 지시: "책갈피창에서 모두 접기 상태에서 이동시 전반적으로 느려. 이 경우 pdf를 모두 보는 것이 아니라 초기 페이지위주로 보는 것이므로
초기 페이지와 화면에 1차로 보이는 썸네일만 우선적으로 보여주는 걸 검토해. 나머지는 나중에 보여주는 거야. 필요시. 컴퓨터가 느려질 때
적용하는 모드도 검토하여 적용될 수 있도록해"
사용자 결정: 적용 = '모두 접기 상태 + 느린 PC(가벼운 넘김이면 모든 파일 옮김)', 연타 = '멈춘 파일만 열기', 느린 PC = '가벼운 넘김에 합치기'.

종전(실측): 40ms 연타에도 지나간 파일을 모두 열고, 열 때마다 썸네일 줄·쪽 낱말·텍스트 창·서명 확인을 그 자리에서 — 최장 정지 1.0초.

A. 모두 접기 → ↓ 5번 연타(30ms) — 연 파일은 2개 이하(첫 것·멈춘 것), 마지막에 본문 = 고른 파일
B. 멈춘 파일을 연 직후: 썸네일 붙듦·쪽 낱말 비어 있음·텍스트 창 아직 · 조금 뒤 보이는 썸네일 · 더 뒤 텍스트 창·붙듦 풂 · 쪽 낱말은 끌어 고를 때(261114-11)
C. 표지 썸네일은 본문이 그린 것을 쓴다(그 쪽을 다시 그리지 않는다)
D. 천천히(350ms) 누르면 지나가는 파일도 하나씩 연다
E. 상태가 없고 가벼운 넘김도 아니면 종전대로 — 연 직후 썸네일을 붙들지 않는다
F. 가벼운 넘김(가짜 절전)이면 펼친 목록에서 다른 파일을 눌러도 표지 먼저
G. Enter 로 연 파일은 종전대로 한 번에 다(붙들지 않는다)
H. 연타 내내 가장 긴 멈춤 < 1초(응답성 SOT)
"""
import os, sys, time, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_FAKE_POWER_SAVING", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(300, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt, QStandardPaths, QCoreApplication, QTimer, QElapsedTimer
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QStandardPaths.setTestModeEnabled(True)               # 검사 작성 SOT §14.7.2 의 3
QCoreApplication.setApplicationName("polypdf_quick_browse_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "표지 먼저", echo=False)   # §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=300):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(5)


root = Path(tempfile.mkdtemp(prefix="polypdf_quick_browse_"))
try:
    for i in range(7):
        d = fitz.open()
        for k in range(24):
            pg = d.new_page()
            pg.insert_text((60, 90), f"file{i} page{k} quick browse cover text", fontsize=14)
        d.set_toc([[1, f"f{i} 장1", 1], [1, f"f{i} 장2", 5]])
        d.save(str(root / f"f{i}.pdf")); d.close()

    from viewer.app import MainWindow
    from viewer.pdf_doc import PdfDocument
    rendered = []
    _orig_rt = PdfDocument.render_thumbnail

    def _spy_rt(self, page, *a, **k):
        rendered.append((Path(str(self.path)).stem, int(page)))
        return _orig_rt(self, page, *a, **k)
    PdfDocument.render_thumbnail = _spy_rt

    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt = mw.bookmark_tree; mv = mw.main_view; pt = mw.page_thumbs
    _held = lambda: bool(getattr(pt, "is_render_held", lambda: False)())        # 수정 전 코드에도 돌게
    _qh = lambda: bool(getattr(mw, "_quick_holds", lambda _i: False)(mw._active_pane))
    loads = []
    _orig_ld = mv.load_document

    def _spy_ld(path, *a, **k):
        loads.append((Path(str(path)).stem, time.perf_counter()))
        return _orig_ld(path, *a, **k)
    mv.load_document = _spy_ld
    texts = []
    _orig_tp = mw._reload_text_panel

    def _spy_tp(*a, **k):
        texts.append(time.perf_counter())
        return _orig_tp(*a, **k)
    mw._reload_text_panel = _spy_tp

    bt.load_folder(root); spin(800)
    try:
        bt.set_tree_view(False); bt.set_sort_mode(bt.SORT_NAME)
    except Exception:
        pass
    bt.btn_edit.setChecked(False); spin(200)
    row = {Path(n.data(0, bt.DATA_FILE)).stem: n for n in bt._iter_file_nodes()}
    chk(len(row) == 7, "준비 — 파일 7개", str(len(row)))

    def menu_action(text, it):
        got = {}
        orig = QMenu.exec

        def fake_exec(menu, *a, **k):
            for x in menu.actions():
                if x.text() == text:
                    got["a"] = x
            return None
        QMenu.exec = fake_exec
        try:
            bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        finally:
            QMenu.exec = orig
        return got.get("a")

    def cur_file():
        f = mv.current_file()
        return Path(f).stem if f else None

    def wait_file(stem, ms=4000):
        t = time.perf_counter()
        while cur_file() != stem and (time.perf_counter() - t) * 1000 < ms:
            app.processEvents(); QTest.qWait(5)
        return cur_file() == stem

    def wait_load(n0, ms=4000):
        t = time.perf_counter()
        while len(loads) <= n0 and (time.perf_counter() - t) * 1000 < ms:
            app.processEvents(); QTest.qWait(3)
        return len(loads) > n0

    def visible_rows():
        vr = pt.list.viewport().rect()
        return [i for i in range(pt.list.count()) if pt.list.visualItemRect(pt.list.item(i)).intersects(vr)]

    bt.tree.setFocus(); bt.tree.setCurrentItem(row["f0"]); wait_file("f0"); spin(900)
    menu_action("책갈피 모두 접기", row["f0"]).trigger(); spin(200)
    bt.tree.setCurrentItem(row["f0"]); spin(900)

    # ── A·H 연타 ──
    beat = QElapsedTimer(); beat.start(); worst = [0]

    def tick():
        worst[0] = max(worst[0], beat.restart())
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(tick); hb.start()
    spin(50); worst[0] = 0; beat.restart()
    n0 = len(loads)
    bt.tree.setFocus()
    for _ in range(5):
        QTest.keyClick(bt.tree, Qt.Key.Key_Down); app.processEvents(); QTest.qWait(30)
    # 멈춘 파일(f5)이 열리는 순간을 잡는다 — 그 직후 상태가 B
    t = time.perf_counter()
    while not (loads[n0:] and loads[-1][0] == "f5") and time.perf_counter() - t < 4:
        app.processEvents(); QTest.qWait(2)
    t_open = loads[-1][1] if loads else time.perf_counter()
    held = _held()
    icons0 = sum(1 for i in range(pt.list.count()) if not pt.list.item(i).icon().isNull())
    words0 = list(mv._page_words)
    texts0 = len([x for x in texts if x >= t_open])
    early_ms = (time.perf_counter() - t_open) * 1000
    opened = [s for s, _ in loads[n0:]]
    chk(cur_file() == "f5", "A 연타 뒤 본문 = 멈춘 파일 f5", str(cur_file()))
    chk(len(opened) <= 2, "A ★ 지나간 파일은 열지 않는다(연 파일 2개 이하 — 종전: 5개 모두)", str(opened))
    print(f"  (연 직후 확인까지 {early_ms:.0f}ms)")
    chk(held and icons0 == 0, "B 연 직후 — 썸네일은 그리지 않고 붙들어 둔다", f"held={held} icons={icons0}")
    chk(words0 == [] and texts0 == 0, "B 연 직후 — 쪽 낱말·텍스트 창은 아직", f"words={len(words0)} text={texts0}")
    spin(getattr(mw, 'QUICK_THUMBS_MS', 150) + 120)
    vis = visible_rows()
    vis_icons = [i for i in vis if not pt.list.item(i).icon().isNull()]
    below = [i for i in range(pt.list.count()) if i not in vis and i > max(vis or [0])]
    below_icons = [i for i in below if not pt.list.item(i).icon().isNull()]
    chk(vis and len(vis_icons) == len(vis), "B 조금 뒤 — 보이는 썸네일이 먼저 찬다", f"{len(vis_icons)}/{len(vis)}")
    chk(not below or not below_icons, "B 그때 화면 아래 썸네일은 아직(보이는 칸만 먼저)", f"아래 그린 것 {below_icons[:5]}")
    spin(getattr(mw, 'QUICK_REST_MS', 450) + 300)
    chk(not _held() and not _qh(), "B 멈춘 뒤 — 붙듦을 풀고 뒤처리 끝")
    chk(len([x for x in texts if x >= t_open]) >= 1, "B 멈춘 뒤 — 텍스트 창이 따라간다")
    mv._sel_begin(60, 90)                                 # 261114-11: 쪽 낱말은 쓸 때 — 끌어 고르기를 시작하면 읽는다
    chk(bool(mv._page_words), "B 멈춘 뒤 — 끌어 고르기를 시작하면 쪽 낱말을 읽는다")
    mv.clear_text_selection()
    chk(("f5", 0) not in rendered, "C 표지 썸네일은 본문이 그린 것을 쓴다(쪽 0 을 다시 그리지 않음)",
        str([r for r in rendered if r[0] == "f5"][:4]))
    hb.stop()
    chk(worst[0] < 1000, "H 연타·뒤처리 동안 가장 긴 멈춤 < 1초", f"{worst[0]}ms")
    print(f"  실측: 가장 긴 멈춤 {worst[0]}ms, 연 파일 {opened}")

    # ── D 천천히 ──
    spin(400)
    n0 = len(loads)
    for _ in range(2):
        QTest.keyClick(bt.tree, Qt.Key.Key_Up); spin(350)
    spin(600)
    opened = [s for s, _ in loads[n0:]]
    chk(opened == ["f4", "f3"] and cur_file() == "f3", "D 천천히 누르면 지나가는 파일도 하나씩 연다", str(opened))

    # ── G Enter ──
    QTest.keyClick(bt.tree, Qt.Key.Key_Return)
    ok = wait_load(len(loads) - 0) or True
    spin(60)
    chk(row["f3"].isExpanded() and not _held() and not _qh(),
        "G Enter 로 연 파일은 종전대로 — 펼치고 붙들지 않는다", f"exp={row['f3'].isExpanded()} held={_held()}")
    spin(800)

    # ── E 상태 없음·가벼운 넘김 아님 ──
    menu_action("책갈피 모두 펼치기", row["f0"]).trigger(); spin(900)
    n0 = len(loads)
    bt.tree.setCurrentItem(row["f6"])
    wait_load(n0)
    held_e = _held()
    chk(cur_file() == "f6" and not held_e and not _qh(),
        "E 상태 없음 — 종전대로 연 직후 썸네일을 붙들지 않는다", f"held={held_e}")
    spin(800)

    # ── F 가벼운 넘김(가짜 절전) — 펼친 목록에서 누름 ──
    from viewer import perf_mode
    os.environ["POLYPDF_FAKE_POWER_SAVING"] = "1"
    perf_mode._power.update(t=-1e9, state="")
    chk(perf_mode.is_lite(), "F 준비 — 가벼운 넘김 켜짐")
    n0 = len(loads)
    bt.tree.scrollToItem(row["f1"]); spin(100)
    r = bt.tree.visualItemRect(row["f1"])
    QTest.mouseClick(bt.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    t = time.perf_counter()
    while not (loads[n0:] and loads[-1][0] == "f1") and time.perf_counter() - t < 4:
        app.processEvents(); QTest.qWait(2)
    chk(cur_file() == "f1" and _held() and _qh(),
        "F 가벼운 넘김이면 펼친 목록에서 다른 파일을 눌러도 표지 먼저", f"{cur_file()} held={_held()}")
    spin(getattr(mw, 'QUICK_REST_MS', 450) + 400)
    chk(not _held(), "F 멈춘 뒤 썸네일을 그린다")
    os.environ.pop("POLYPDF_FAKE_POWER_SAVING", None)
    perf_mode._power.update(t=-1e9, state="")
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
