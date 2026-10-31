# -*- coding: utf-8 -*-
"""261008-12 → 261025-1(디자인 SOT §2.9.5, 사용자 지시·결정): `즐겨찾기` 탭.

종전 결함(사용자 보고 '즐겨찾기 폴더 드롭다운이 작동하지 않음'): 메뉴의 '눌리지 않는 제목 줄' 이 탭 세부 줄에서
꺼진 단추가 되어 목록이 펼쳐지지 않았다. 수정 전 코드로 A 가 실패한다.

A. 세부 줄 차례: 최근 폴더▾ · 등록 폴더▾ · 폴더 단추 · 최근 파일▾ | 등록 파일▾ · 파일 단추 · 등록 검색어▾ | 기타▾ | 추가 셋 · 항목 관리.
   묶음 단추는 **켜져 있고 메뉴를 갖는다**. 파일 탭에는 최근 폴더·최근 파일이 없다.
B. 드롭다운: 종류별·등록 순서·kind 없는 옛 항목은 폴더·마지막 '항목 관리...'·빈 목록은 '(등록된 항목 없음)'
C. 개별 단추: 폴더·파일 앞 5개, 글은 요약 이름(short, 없으면 가운데 줄임) — 단추를 **눌러** 파일이 열린다
D. 목록을 만들 때 있는지 보지 않는다(없는 파일 항목도 켜짐) — 누르면 알린다(응답성 SOT §5)
E. 기타: 한국어+키가 있는 구역만, 하나도 없으면 단추 숨김 · 항목 관리 창은 꺼진 종류의 탭이 없다
F. 항목 관리 창: 탭 안 순서·단추 이름 고침 → 저장 순서·요약 이름 반영
G. 파일 즐겨찾기 등록 창의 종류가 '📄 파일'(261008-12, 실제 _add_file_favorite)
"""
import os, sys, faulthandler, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from pathlib import Path
from PyQt6.QtCore import QStandardPaths, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
from PyQt6.QtCore import QCoreApplication as _QCA
_QCA.setApplicationName("polypdf_fav_groups_%d" % os.getpid())   # 마스터 §14.7.2 의 3 — 공유 시험 설정(qttest/python)에 남기지 않는다
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
    mw.resize(1920, 900); mw.show(); QTest.qWait(100)
    mw._law_favorites = [{"name": "도로법", "kind_label": "법률"}]
    mw._kcsc_favorites = [{"name": "KDS 14", "category": "설계"}]
    mw._kipo_favorites = []
    mw._favorites = [                                   # 일부러 섞어서 등록
        {"kind": "file", "name": "파일1", "file": str(f1), "folder": str(d1)},
        {"kind": "folder", "name": "폴더1", "folder": str(d1)},
        {"kind": "search", "name": "검색", "folder": str(d1), "query": "가"},
        {"kind": "file", "name": "아주긴파일이름입니다정말로긴", "file": str(f2), "folder": str(d2), "short": "짧은2"},
        {"name": "옛폴더", "folder": str(d2)},             # kind 없음 → 폴더
        {"kind": "file", "name": "없는파일", "file": str(root / "x.pdf")},
    ]
    mw._prefs.update({"law_oc": "", "kcsc_key": "", "kipo_signkey": ""})
    mw._gate_api_dependent_ui(mw._prefs)                 # 키 없음 → 기타 숨김(그리고 목록을 다시 넣는다)
    QTest.qWait(80)

    mw._ribbon.select("fav"); QTest.qWait(50)
    row = mw._ribbon.row("fav")
    btns = row.buttons()
    texts = [b.text() for b in btns]
    # 261025-5(사용자 지시): 최근 파일은 등록 파일 그룹 왼쪽, 최근 검색어는 등록 검색어 왼쪽 — 그룹마다 '최근 · 등록 · 단추'
    # 261031-12(사용자 지시): (최근 셋) | (등록 셋 + 기타) | (폴더 단추 ≤3) | (파일 단추 ≤3) | 추가·관리
    want = ["최근 폴더", "최근 파일", "최근 검색어",
            "등록 폴더", "등록 파일", "등록 검색어",
            "폴더1", "옛폴더",
            "파일1", "짧은2", "없는파일",
            "현재 폴더 추가", "현재 파일 추가", "현재 검색어 추가", "항목 관리"]
    chk(texts == want, "A 즐겨찾기 탭 세부 줄 차례(키 없음 → 기타 숨김)", str(texts))
    by = {b.text(): b for b in btns}
    for t, menu in (("등록 폴더", mw.menu_fav_folders), ("등록 파일", mw.menu_fav_files),
                    ("등록 검색어", mw.menu_fav_searches), ("최근 폴더", mw.menu_recent),
                    ("최근 검색어", mw.menu_recent_searches)):
        b = by.get(t)
        chk(b is not None and b.isEnabled() and b.defaultAction().menu() is menu,
            f"A '{t}' 은 켜진 ▾ 단추(누르면 목록이 펼쳐진다)")
    chk([len(g) for g in row.groups()] == [3, 3, 2, 3, 4], "A 그룹 바탕 다섯(최근·등록·폴더 단추·파일 단추·추가 — 기타가 숨으면 등록은 셋)",
        str([[w.text() for w in g] for g in row.groups()]))
    mw._ribbon.select("file"); QTest.qWait(50)
    ftexts = [b.text() for b in mw._ribbon.row("file").buttons()]
    mw._ribbon.select("fav"); QTest.qWait(50)
    chk("최근 폴더" not in ftexts and "최근 파일" not in ftexts, "A 파일 탭에서는 최근 폴더·최근 파일을 뺐다", str(ftexts))

    # B 드롭다운
    items = lambda m: [a.text() for a in m.actions() if not a.isSeparator()]
    chk(items(mw.menu_fav_folders) == ["📁 폴더1", "📁 옛폴더", "항목 관리..."], "B 등록 폴더 목록(옛 항목은 폴더) + 항목 관리",
        str(items(mw.menu_fav_folders)))
    chk(items(mw.menu_fav_files) == ["📄 파일1", "📄 아주긴파일이름입니다정말로긴", "📄 없는파일", "항목 관리..."],
        "B 등록 파일 목록은 등록 순서", str(items(mw.menu_fav_files)))
    chk(items(mw.menu_fav_searches) == ["🔍 검색", "항목 관리..."], "B 등록 검색어", str(items(mw.menu_fav_searches)))

    # D 있는지 보지 않는다 — 없는 파일도 켜짐, 누르면 알린다
    a_missing = [a for a in mw.menu_fav_files.actions() if a.text() == "📄 없는파일"][0]
    chk(a_missing.isEnabled(), "D 목록을 만들 때 있는지 보지 않는다(없는 파일 항목도 켜짐)")
    warned = []
    orig_warn = QMessageBox.warning
    QMessageBox.warning = lambda *a, **k: (warned.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Ok)[1]
    try:
        QTest.mouseClick(by["없는파일"], Qt.MouseButton.LeftButton); QTest.qWait(50)
    finally:
        QMessageBox.warning = orig_warn
    chk(bool(warned), "D 없는 대상 단추를 누르면 알린다", str(warned))

    # C 개별 단추 — 눌러서 열기, 요약 이름
    QTest.qWait(80)
    b2 = {b.text(): b for b in mw._ribbon.row("fav").buttons()}["짧은2"]
    QTest.mouseClick(b2, Qt.MouseButton.LeftButton); QTest.qWait(300)
    cur = mw.main_view.current_file()
    chk(cur and Path(str(cur)).name == "파일2.pdf", "C 파일 단추를 누르면 그 파일이 열린다", str(cur))
    from viewer.widgets.favorites_dialog import middle_ellipsis, short_label, SHORT_MAX, BUTTONS_MAX
    chk(short_label({"name": "아주긴파일이름입니다정말로긴"}) == middle_ellipsis("아주긴파일이름입니다정말로긴")
        and len(middle_ellipsis("아주긴파일이름입니다정말로긴")) == SHORT_MAX and "…" in middle_ellipsis("아주긴파일이름입니다정말로긴"),
        "C 요약 이름이 없으면 가운데를 줄인다", middle_ellipsis("아주긴파일이름입니다정말로긴"))
    mw._favorites = [{"kind": "folder", "name": f"D{i}", "folder": str(d1)} for i in range(7)]
    mw._refresh_favorites_menu(); QTest.qWait(80)
    dt = [b.text() for b in mw._ribbon.row("fav").buttons() if b.text().startswith("D")]
    chk(dt == [f"D{i}" for i in range(BUTTONS_MAX)], "C 폴더 단추는 목록 앞 BUTTONS_MAX(3)개", str(dt))
    chk(BUTTONS_MAX == 3, "C 단추 수는 3(261031-12 사용자 지시)")
    # 261031-12(사용자 결정 '시안 C'): 종류 아이콘 — 최근·등록 단추와 무리의 첫 단추에만
    _fb = [b for b in mw._ribbon.row("fav").buttons()]
    _ic = {b.text(): not b.icon().isNull() for b in _fb}
    chk(_ic.get("최근 폴더") and _ic.get("등록 폴더") and _ic.get("최근 파일") and _ic.get("등록 검색어")
        and _ic.get("D0") and not _ic.get("D1") and not _ic.get("현재 폴더 추가"),
        "C 아이콘은 최근·등록 단추와 폴더 무리 첫 단추에만", str(_ic))
    _iw = mw._ribbon.row("fav").iconSize().width()
    from viewer.widgets.icons import FAV_ICON_PX
    chk(_iw == FAV_ICON_PX and mw._ribbon.row("fav").toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        and mw._ribbon.row("file").toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly,
        "C 즐겨찾기 줄만 작은 아이콘 + 글자(다른 탭은 글자만)", str(_iw))
    chk(items(mw.menu_fav_files) == ["(등록된 항목 없음)", "항목 관리..."], "B 빈 목록은 '(등록된 항목 없음)'", str(items(mw.menu_fav_files)))

    # E 기타 — 법령 키만 있으면 법령 구역만
    mw._prefs.update({"law_oc": "x"})
    mw._gate_api_dependent_ui(mw._prefs); QTest.qWait(80)
    chk(mw.menu_fav_other.menuAction().isVisible(), "E 키가 있으면 기타가 보인다")
    ot = [a.text() for a in mw.menu_fav_other.actions() if not a.isSeparator() or a.text()]
    chk(ot == ["법령·고시", "⚖ 도로법  (법률)", "항목 관리..."], "E 꺼진 구역(건설기준·특허)은 뺀다", str(ot))
    seen_kinds = []
    from viewer.widgets import favorites_dialog as _fd
    orig_exec = _fd.FavoritesManagerDialog.exec
    _fd.FavoritesManagerDialog.exec = lambda self: (seen_kinds.extend(self.kinds()), 0)[1]
    try:
        mw._manage_kcsc_favorites()                      # 건설기준 창의 '즐겨찾기 관리' — 키가 없어 탭 없음
    finally:
        _fd.FavoritesManagerDialog.exec = orig_exec
    chk(seen_kinds == ["folder", "file", "search", "law"], "E 항목 관리 창은 꺼진 종류의 탭이 없다", str(seen_kinds))

    # F 항목 관리 창 — 탭 안 순서·단추 이름
    from viewer.widgets.favorites_dialog import FavoritesManagerDialog
    dlg = FavoritesManagerDialog({"folder": [{"kind": "folder", "name": "A", "folder": "a"},
                                             {"kind": "folder", "name": "B", "folder": "b"}],
                                  "file": [{"kind": "file", "name": "F", "file": "f"}], "search": []}, "file")
    chk(dlg.tabs.currentWidget() is dlg.page("file"), "F 드롭다운의 항목 관리는 그 종류의 탭으로 연다")
    pg = dlg.page("folder"); pg.list.setCurrentRow(1); pg._move(-1)
    from PyQt6.QtWidgets import QInputDialog
    orig_get = QInputDialog.getText
    QInputDialog.getText = staticmethod(lambda *a, **k: ("단추B", True))
    try:
        pg._on_short(pg.list.item(0))
    finally:
        QInputDialog.getText = orig_get
    res = dlg.result("folder")
    chk([f["name"] for f in res] == ["B", "A"] and res[0].get("short") == "단추B", "F 순서·단추 이름이 결과에", str(res))
    dlg.done(0)

    # G 파일 즐겨찾기 등록 창의 종류 표시 — 실제 _add_file_favorite 경로
    from viewer.widgets.favorites_dialog import AddFavoriteDialog
    from PyQt6.QtWidgets import QLabel
    seen = []
    orig_exec2 = AddFavoriteDialog.exec
    AddFavoriteDialog.exec = lambda self: (seen.extend(l.text() for l in self.findChildren(QLabel)), 0)[1]
    try:
        mw._add_file_favorite(str(f1))
    finally:
        AddFavoriteDialog.exec = orig_exec2
    chk("종류: 📄 파일" in seen, "G 파일 즐겨찾기 등록 창이 '📄 파일' 로 보인다", str(seen))
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
