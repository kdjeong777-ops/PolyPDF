# -*- coding: utf-8 -*-
"""261008-12: 즐겨찾기 메뉴 — 폴더와 파일을 별도 그룹으로, 즐겨찾기 폴더 밑에 즐겨찾기 파일.

사용자 요청: "즐겨찾기 메뉴에 즐겨찾기한 폴더와 파일을 별도의 그룹으로 구분해.
즐겨찾기 폴더 그룹 밑에 즐겨찾기 파일 그룹을 구성해"

A. 등록 순서가 섞여 있어도 '즐겨찾기 폴더' → '즐겨찾기 파일' → '즐겨찾기 검색어' 순 · 그룹 안은 등록 순서
B. 그룹 제목은 눌리지 않는다 · 항목이 없는 그룹은 제목도 없다 · kind 없는 옛 항목은 폴더로
C. 파일 그룹 항목을 누르면 그 파일이 열린다 · 없는 대상은 '(없음)' 으로 꺼진다
"""
import os, sys, faulthandler, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from pathlib import Path
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_fav_"))
try:
    import test_fixtures as _fx
    from viewer.app import MainWindow
    d1 = root / "폴더1"; d2 = root / "폴더2"; d1.mkdir(); d2.mkdir()
    f1 = d1 / "파일1.pdf"; f2 = d2 / "파일2.pdf"
    shutil.copy(_fx.text_pdf(), f1); shutil.copy(_fx.text_pdf(), f2)

    mw = MainWindow()
    mw._law_favorites = []; mw._kcsc_favorites = []
    for k in ("_kipo_favorites",):
        if hasattr(mw, k):
            setattr(mw, k, [])
    mw._favorites = [                                   # 일부러 섞어서 등록
        {"kind": "file", "name": "파일1", "file": str(f1), "folder": str(d1)},
        {"kind": "folder", "name": "폴더1", "folder": str(d1)},
        {"kind": "search", "name": "검색", "folder": str(d1), "query": "가"},
        {"kind": "file", "name": "파일2", "file": str(f2), "folder": str(d2)},
        {"name": "옛폴더", "folder": str(d2)},             # kind 없음 → 폴더
        {"kind": "file", "name": "없는파일", "file": str(root / "x.pdf")},
    ]
    mw._refresh_favorites_menu()
    acts = mw.menu_favorites.actions()
    texts = [a.text() for a in acts if not a.isSeparator()]
    i0 = texts.index("즐겨찾기 관리...") + 1
    got = texts[i0:i0 + 10]
    want = ["즐겨찾기 폴더", "📁 폴더1", "📁 옛폴더",
            "즐겨찾기 파일", "📄 파일1", "📄 파일2", "📄 없는파일  (없음)",
            "즐겨찾기 검색어", "🔍 검색"]
    chk(got[:len(want)] == want, "A 폴더 → 파일 → 검색어 그룹, 그룹 안은 등록 순서", str(got))
    by = {a.text(): a for a in acts}
    chk(all(not by[t].isEnabled() for t in ("즐겨찾기 폴더", "즐겨찾기 파일", "즐겨찾기 검색어")),
        "B 그룹 제목은 눌리지 않는다")
    seps = [i for i, a in enumerate(acts) if a.isSeparator()]
    hdr_idx = [i for i, a in enumerate(acts) if a.text() in ("즐겨찾기 폴더", "즐겨찾기 파일", "즐겨찾기 검색어")]
    chk(all(h - 1 in seps for h in hdr_idx), "B 그룹마다 구분선으로 나뉜다")
    chk(not by["📄 없는파일  (없음)"].isEnabled(), "C 없는 대상은 '(없음)' 으로 꺼진다")

    mw._favorites = [{"kind": "file", "name": "파일2", "file": str(f2), "folder": str(d2)}]
    mw._refresh_favorites_menu()
    texts = [a.text() for a in mw.menu_favorites.actions()]
    chk("즐겨찾기 폴더" not in texts and "즐겨찾기 파일" in texts, "B 항목이 없는 그룹은 제목도 없다", str(texts))
    [a for a in mw.menu_favorites.actions() if a.text() == "📄 파일2"][0].trigger()
    app.processEvents()
    cur = mw.main_view.current_file()
    chk(cur and Path(str(cur)).name == "파일2.pdf", "C 파일 그룹 항목을 누르면 그 파일이 열린다", str(cur))
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
