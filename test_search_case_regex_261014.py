# -*- coding: utf-8 -*-
"""261014-18: 검색 대소문자 구분·정규식 토글 (검색창 SOT §4.1, 개선 로드맵 P2-7).

실제 처리기(검색칸 Enter·토글)로:
A. 둘 다 끄면 종전과 같다(대소문자 무시 부분일치)
B. Aa — 결과 목록·쪽마다 개수·본문 강조가 대소문자를 가린다, 토글을 바꾸면 다시 검색한다
C. .* — 정규식으로 결과·조각 글·본문 강조, F3 로 그 매치들을 돈다
D. 틀린 정규식은 검색하지 않고 검색칸을 붉게
E. 검색어 즐겨찾기가 토글 값을 되살린다
F. 오른쪽 창 내용 찾기(content_find)도 같은 규칙
G. 스크린샷 강조 그림은 규칙이 다르면 다른 파일(같은 글자 다른 규칙이 섞이지 않게)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=30):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


def wait_until(cond, timeout_ms=20000):
    t = 0
    while t < timeout_ms:
        if cond():
            return True
        spin(1, 50); t += 50
    return cond()


root = Path(tempfile.mkdtemp(prefix="polypdf_srch_test_"))
try:
    for name in ("A", "B"):
        d = fitz.open()
        for k in range(2):
            d.new_page().insert_text((72, 100), f"Asphalt asphalt ASPHALT mix {name}{k} 2024-10 and 1999-01", fontsize=11)
        d.save(str(root / f"{name}.pdf")); d.close()

    QMessageBox.information = staticmethod(lambda *x, **k: None)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    mw.open_folder(root)
    wait_until(lambda: not getattr(mw, "_index_worker", None) and not getattr(mw, "_indexing", False), 30000)
    spin(20)
    mw._load_main(HistoryItem(str(root / "A.pdf"), 0, "", "bookmark")); spin(10)
    sb, mv = mw.search_bar, mw.main_view

    def search(q):
        mw._last_results = None
        sb.edit.setText(q)
        sb._emit_search()
        wait_until(lambda: mw._last_results is not None, 20000)
        spin(5)
        return mw._last_results or []

    # ── A. 둘 다 끔 ───────────────────────────────────────────────
    sb.set_mode(False, False)
    res = search("asphalt")
    chk(len(res) == 4 and all(r.match_count == 3 for r in res), "A 끔 — 종전과 같다(대소문자 무시, 쪽마다 3)",
        str([(r.file_name, r.page_index, r.match_count) for r in res]))
    chk(len(mv._matches) == 2 and sum(len(h.rects) for h in mv._matches) == 6, "A 본문 매치 — 두 쪽 × 3")

    # ── B. Aa ────────────────────────────────────────────────────
    mw._last_results = None
    sb.btn_case.setChecked(True)                     # 토글 → 다시 검색
    wait_until(lambda: mw._last_results is not None, 20000); spin(5)
    res = mw._last_results or []
    chk(len(res) == 4 and all(r.match_count == 1 for r in res), "B Aa — 결과·개수가 대소문자를 가린다(토글로 다시 검색)",
        str([(r.file_name, r.match_count) for r in res]))
    chk(sum(len(h.rects) for h in mv._matches) == 2, "B Aa — 본문 강조도 쪽마다 1",
        str([len(h.rects) for h in mv._matches]))
    res = search("ASPHALT")
    chk(len(res) == 4 and all(r.match_count == 1 for r in res) and "<ASPHALT>" in res[0].snippet,
        "B Aa — 대문자 질의는 대문자만, 조각 글 표시", res[0].snippet if res else "")

    # ── C. .* ────────────────────────────────────────────────────
    sb.set_mode(False, True)
    res = search(r"\d{4}-\d{2}")
    chk(len(res) == 4 and all(r.match_count == 2 for r in res) and "<2024-10>" in res[0].snippet,
        "C 정규식 — 결과·개수·조각 글", str([(r.match_count, r.snippet) for r in res[:2]]))
    chk(sum(len(h.rects) for h in mv._matches) == 4, "C 정규식 — 본문 강조(두 쪽 × 2)", str([len(h.rects) for h in mv._matches]))
    before = mv._current_match
    mv.go_next_match(); spin(3)
    chk(mv._current_match == (before + 1) % 4, "C F3 이 정규식 매치를 돈다", f"{before} → {mv._current_match}")
    res = search(r"mix [AB]0")                       # 힌트 조각('mix ')으로 후보를 추린 뒤 거른다
    chk(len(res) == 2 and {r.page_index for r in res} == {0}, "C 정규식 — 글자 조각 힌트가 있어도 결과가 맞다",
        str([(r.file_name, r.page_index) for r in res]))

    # ── D. 틀린 정규식 ─────────────────────────────────────────────
    mw._last_results = "untouched"
    sb.edit.setText("(abc"); sb._emit_search(); spin(5)
    chk(mw._last_results == "untouched" and "d33" in sb.edit.styleSheet(), "D 틀린 정규식은 검색하지 않고 검색칸을 붉게")
    sb.set_mode(False, False)
    search("asphalt")
    chk(sb.edit.styleSheet() == "", "D 고치면 붉은 표시가 사라진다")

    # ── E. 즐겨찾기 ───────────────────────────────────────────────
    from viewer.widgets import favorites_dialog as fd
    fd.AddFavoriteDialog.exec = lambda dlg: fd.AddFavoriteDialog.DialogCode.Accepted
    fd.AddFavoriteDialog.name = lambda dlg: "fav-regex"
    sb.set_mode(True, True)
    sb.edit.setText(r"\d{4}")
    mw._add_current_search_favorite()
    fav = next((f for f in mw._favorites if f.get("name") == "fav-regex"), None)
    chk(fav is not None and fav.get("case") is True and fav.get("regex") is True, "E 즐겨찾기에 토글 값을 남긴다", str(fav))
    sb.set_mode(False, False)
    if fav:
        mw._last_results = None
        mw._open_favorite(fav)
        wait_until(lambda: mw._last_results is not None, 20000); spin(5)
    chk(sb.btn_case.isChecked() and sb.btn_regex.isChecked(), "E 즐겨찾기를 열면 토글을 되살린다")

    # ── F. 오른쪽 창 내용 찾기 ────────────────────────────────────
    from PyQt6.QtWidgets import QTextBrowser
    from viewer.widgets import content_find as cf
    tb = QTextBrowser(); tb.setPlainText("Abc abc ABC\nnext line 2024-10")
    cf.set_mode(None); st = {}
    plain = cf.search(tb, "abc", False, st)[1]
    cf.set_mode((True, False)); st = {}
    cased = cf.search(tb, "abc", False, st)[1]
    cf.set_mode((False, True)); st = {}
    rx = cf.search(tb, r"\d{4}-\d{2}", False, st)
    cf.set_mode(None)
    chk(plain == 3 and cased == 1 and rx[1] == 1, "F 오른쪽 창 내용 찾기도 같은 규칙", f"{plain} {cased} {rx}")

    # ── G. 스크린샷 강조 그림 ──────────────────────────────────────
    from viewer import screenshot as ss
    p1 = ss.render_page_png(str(root / "A.pdf"), 0, "asphalt", folder=root)
    p2 = ss.render_page_png(str(root / "A.pdf"), 0, "asphalt", folder=root, mode=(True, False))
    chk(p1 != p2 and p1.exists() and p2.exists(), "G 규칙이 다르면 다른 강조 그림", f"{p1.name} {p2.name}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
