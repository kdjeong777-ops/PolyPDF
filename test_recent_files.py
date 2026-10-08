# -*- coding: utf-8 -*-
"""261008-11: 파일 메뉴 '최근 폴더' 밑에 '최근 파일'.

사용자 요청: "파일메뉴의 최근 폴더 밑에 최근 파일을 추가해"

A. 파일 메뉴에서 '최근 파일' 이 '최근 폴더' 바로 밑에 있다 · 처음엔 '(최근 파일 없음)'
B. PDF 를 열면(open_pdf) 맨 위에 · 다시 열면 중복 없이 맨 위로 · 여러 개 열기(open_pdfs)도 기록
C. 메뉴 항목을 누르면 그 파일이 열린다 · 없어진 파일은 목록에서 빠진다
D. 최대 10개 · 설정에 저장되고(recent_files) 다시 읽힌다 · 개인 항목(배포 기본값에서 제외)
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


root = Path(tempfile.mkdtemp(prefix="polypdf_recent_"))
try:
    import test_fixtures as _fx
    from viewer.app import MainWindow
    from viewer import settings_store
    src = Path(_fx.text_pdf())
    pdfs = []
    for i in range(12):
        p = root / f"문서{i:02d}.pdf"
        shutil.copy(src, p)
        pdfs.append(p)

    mw = MainWindow()
    mw._recent_files = []
    mw._refresh_recent_files_menu()

    # ── A ──
    titles = []
    for m in mw.menuBar().actions():
        if m.menu() is not None and mw.menu_recent in [a.menu() for a in m.menu().actions()]:
            titles = [a.text() for a in m.menu().actions()]
    i_fold = titles.index("최근 폴더") if "최근 폴더" in titles else -1
    chk(i_fold >= 0 and titles[i_fold + 1] == "최근 파일", "A '최근 파일' 이 '최근 폴더' 바로 밑", str(titles))
    items = lambda: [a.text() for a in mw.menu_recent_files.actions()]
    chk(items() == ["(최근 파일 없음)"], "A 처음엔 '(최근 파일 없음)'", str(items()))

    # ── B ──
    mw.open_pdf(pdfs[0]); app.processEvents()
    mw.open_pdf(pdfs[1]); app.processEvents()
    chk(items() == [str(pdfs[1]), str(pdfs[0])], "B 연 순서대로 맨 위에", str(items()))
    mw.open_pdf(pdfs[0]); app.processEvents()
    chk(items() == [str(pdfs[0]), str(pdfs[1])], "B 다시 열면 중복 없이 맨 위로", str(items()))
    mw.open_pdfs([pdfs[2], pdfs[3]]); app.processEvents()
    chk(items()[:2] == [str(pdfs[2]), str(pdfs[3])] and len(items()) == 4,
        "B 여러 파일 열기도 기록(첫 파일이 맨 위)", str(items()))

    # ── C ──
    mw.menu_recent_files.actions()[3].trigger(); app.processEvents()   # 문서01
    cur = mw.main_view.current_file()
    chk(cur and Path(str(cur)).name == pdfs[1].name, "C 메뉴 항목을 누르면 그 파일이 열린다", str(cur))
    chk(items()[0] == str(pdfs[1]), "C 연 파일이 맨 위로 올라간다", str(items()))
    gone = root / "지운파일.pdf"; shutil.copy(src, gone)
    mw._touch_recent_files([gone]); gone.unlink()
    mw.menu_recent_files.actions()[0].trigger(); app.processEvents()
    chk(str(gone) not in items(), "C 없어진 파일은 누르면 목록에서 빠진다", str(items()))

    # ── D ──
    for p in pdfs:
        mw._touch_recent_files([p])
    chk(len(items()) == 10 and items()[0] == str(pdfs[-1]), "D 최대 10개, 최근 것이 맨 위", str(len(items())))
    payload = mw._build_settings_payload()
    chk(payload.get("recent_files") == mw._recent_files, "D 설정 저장 항목에 recent_files")
    chk("recent_files" in settings_store.PERSONAL_TOP_KEYS, "D 개인 항목(배포 기본값에서 제외·초기화 시 유지)")
    saved = list(mw._recent_files)
    mw._recent_files = []
    orig_load = settings_store.load
    settings_store.load = lambda *a, **k: dict(orig_load(*a, **k), recent_files=saved)
    try:
        mw._restore_settings()
    finally:
        settings_store.load = orig_load
    chk(mw._recent_files == saved and items() == saved, "D 설정에서 다시 읽어 메뉴를 채운다")
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
