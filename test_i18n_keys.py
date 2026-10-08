# -*- coding: utf-8 -*-
"""다국어(언어팩) SOT Phase 1 — 저장값·비교를 화면 문구에서 떼어 냈다 (§5, 261008).

A. 코드에 화면 글자 비교가 없다 — `.text()`/`.currentText()` 를 한글 리터럴과 비교, `setCurrentText`/`findText` 에 한글 리터럴
B. 화면 맞춤 — 내부 키, 옛 설정값('폭 맞춤' 등)을 읽을 때 바꾼다, 저장도 키, 콤보 글자를 바꿔도 동작 그대로
C. 인쇄 창 — 색상·인쇄 면·포함을 키로 판단(글자를 영어로 바꿔도 같은 결과), 다단을 켜면 인쇄 면이 키로 걸린다
D. 보기 메뉴 — 항목을 고정 id 로 찾는다(글자를 바꿔도 API 키 게이팅이 듣는다)
E. 책갈피창·검색창 정렬 — 키로 정렬(글자를 바꿔도 같은 순서)
F. 함수 안에서 tr·trp·trn·tr_noop 이름을 import·대입하지 않는다 — 그러면 그 함수 전체에서 지역 변수가 되어
   앞쪽의 tr(...) 이 UnboundLocalError(261008 2단계에서 실제로 앱이 시작되지 않았다, 다국어 SOT §3.1)
"""
import os, sys, ast, re, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


HERE = Path(__file__).resolve().parent
HANGUL = re.compile(r"[가-힣]")


def _is_text_call(n):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("text", "currentText") and not n.args)


def _has_hangul_lit(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return bool(HANGUL.search(n.value))
    if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
        return any(_has_hangul_lit(e) for e in n.elts)
    return False


try:
    # ── A ──
    bad = []
    for p in sorted((HERE / "viewer").rglob("*.py")):
        if "__pycache__" in p.parts or "_vendor" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        rel = p.relative_to(HERE).as_posix()
        for n in ast.walk(tree):
            if isinstance(n, ast.Compare):
                sides = [n.left] + list(n.comparators)
                if any(_is_text_call(x) for x in sides) and any(_has_hangul_lit(x) for x in sides):
                    bad.append("%s:%d 비교" % (rel, n.lineno))
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("setCurrentText", "findText") and n.args and _has_hangul_lit(n.args[0])):
                bad.append("%s:%d %s" % (rel, n.lineno, n.func.attr))
    chk(not bad, "A 화면 글자를 한글 리터럴과 비교·검색하는 곳이 없다", str(bad[:10]))

    # ── F ──
    NAMES = {"tr", "trp", "trn", "tr_noop"}
    shadow = []
    for p in sorted((HERE / "viewer").rglob("*.py")):
        if "__pycache__" in p.parts or "_vendor" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        rel = p.relative_to(HERE).as_posix()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            for n in ast.walk(fn):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    if any((a.asname or a.name) in NAMES for a in n.names):
                        shadow.append("%s:%d import" % (rel, n.lineno))
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in NAMES:
                    shadow.append("%s:%d assign" % (rel, n.lineno))
                elif isinstance(n, ast.arg) and n.arg in NAMES:
                    shadow.append("%s:%d arg" % (rel, n.lineno))
    chk(not shadow, "F 함수 안에서 tr 류 이름을 import·대입·인자로 쓰지 않는다(UnboundLocalError)", str(sorted(set(shadow))[:10]))

    from viewer.widgets.main_view import MainView as MV
    # ── B ──
    chk(MV.FIT_ORDER == ("page", "two", "width", "none"), "B 맞춤 모드는 내부 키")
    chk([MV.normalize_fit(x) for x in ("쪽 맞춤", "2장 맞춤", "폭 맞춤", "수동 맞춤", "수동", "width", "", "엉뚱")]
        == ["page", "two", "width", "none", "none", "width", "page", "page"], "B 옛 화면 문구 값을 키로 바꾼다")
    from viewer.app import MainWindow
    from viewer import settings_store
    sp = settings_store.settings_path(); sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"schema_version": settings_store.CURRENT_SCHEMA, "fit_mode": "폭 맞춤",
                              "preferences": {"start_view_single": False, "language": "ko"}},
                             ensure_ascii=False), encoding="utf-8")
    mw = MainWindow(); mw._skip_save_on_close = True
    mv = mw.main_view
    chk(mv._fit_mode == "width" and mv.cmb_fit.currentData() == "width",
        "B 옛 설정 '폭 맞춤' 으로 시작해도 폭 맞춤(콤보도)", repr((mv._fit_mode, mv.cmb_fit.currentData())))
    chk(mw._build_settings_payload().get("fit_mode") == "width", "B 저장은 내부 키")
    for i in range(mv.cmb_fit.count()):
        mv.cmb_fit.setItemText(i, "X%d" % i)                 # 다른 언어 글자라 해도
    mv.cmb_fit.setCurrentIndex(mv.cmb_fit.findData("two"))
    chk(mv._fit_mode == "two", "B 콤보 글자를 바꿔도 고르면 그 모드가 된다", mv._fit_mode)
    sp.unlink()

    # ── C ──
    from viewer.widgets.print_dialog import PrintScopeDialog
    from PyQt6.QtPrintSupport import QPrinter
    pd = PrintScopeDialog(3, 0, 0, 0, None)
    for cmb in (pd.cmb_color, pd.cmb_duplex, pd.cmb_include):
        for i in range(cmb.count()):
            cmb.setItemText(i, "EN%d" % i)
    pd.cmb_color.setCurrentIndex(pd.cmb_color.findData("gray"))
    chk(pd.color_mode() == QPrinter.ColorMode.GrayScale, "C 흑백은 키로(글자를 바꿔도)")
    pd.cmb_color.setCurrentIndex(pd.cmb_color.findData("color"))
    chk(pd.color_mode() == QPrinter.ColorMode.Color, "C 컬러")
    pd.cmb_duplex.setCurrentIndex(pd.cmb_duplex.findData("short"))
    chk(pd.duplex_mode() == QPrinter.DuplexMode.DuplexShortSide, "C 인쇄 면은 키로")
    pd.cmb_include.setCurrentIndex(pd.cmb_include.findData("doc"))
    chk(pd.include_decorations() is False, "C '문서만' 은 키로")
    chk([pd.cmb_duplex.itemData(i) for i in range(pd.cmb_duplex.count())] == ["none", "long", "short"],
        "C 인쇄 면 키가 다단 설정과 같다(none·long·short)")
    pd.done(0)

    # ── D ──
    chk(set(["law", "kcsc", "kipo", "single", "present"]) <= set(mw._view_acts),
        "D 보기 메뉴 항목을 고정 id 로 갖는다", str(sorted(mw._view_acts)))
    for a in mw._view_acts.values():
        a.setText("EN")                                       # 다른 언어 글자
    mw._prefs.update({"law_oc": "", "kcsc_key": "", "kipo_signkey": ""})
    mw._gate_api_dependent_ui(mw._prefs)
    chk(not mw._view_acts["law"].isEnabled() and not mw._view_acts["kcsc"].isEnabled()
        and not mw._view_acts["kipo"].isEnabled(), "D 글자가 바뀌어도 키가 없으면 꺼진다(게이팅이 id 로 찾는다)")
    mw._prefs["law_oc"] = "x"
    mw._gate_api_dependent_ui(mw._prefs)
    chk(mw._view_acts["law"].isEnabled(), "D 키를 넣으면 켜진다")

    # ── E ──
    bt = mw.bookmark_tree
    chk([bt._sort_combo.itemData(i) for i in range(bt._sort_combo.count())] == ["book", "name", "mtime", "size"]
        and bt._sort_combo.currentData() == "mtime", "E 책갈피창 정렬은 키(기본 수정일 순)")
    bt.set_sort_mode("name")
    chk(bt._sort_combo.currentData() == "name", "E set_sort_mode")
    from viewer.widgets.search_panel import SearchResults as _SRP
    sp_ = _SRP()
    keys = [sp_.sort_combo.itemData(i) for i in range(sp_.sort_combo.count())]
    chk(keys == ["book", "name", "count"], "E 검색창 정렬은 키", str(keys))
    sp_.sort_combo.setItemText(2, "By count")
    sp_.sort_combo.setCurrentIndex(2)
    g = {"b.pdf": [type("R", (), {"match_count": 1})()], "a.pdf": [type("R", (), {"match_count": 5})()]}
    chk([k for k, _v in sp_._sorted_groups(g)] == ["a.pdf", "b.pdf"], "E 글자를 바꿔도 '횟수 순' 으로 정렬")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
