"""다국어 SOT §7·§9 — 한국 전용 기능 숨김 (Phase 4, 261008-25)

한국어가 아니면 법령·고시·건설기준(KCSC)·특허(KIPO)·영어단어 학습(단어장)·영→한 번역과 사전 관리를
숨긴다(사용자 결정). 실제 `MainWindow` 를 영어(en)와 한국어(ko)로 띄워 확인한다.

A. en: 툴바 단추(법령·KCSC·KIPO·번역·단어장 보기·단어장 생성)가 숨겨진다
B. en: 보기 메뉴(단어장·법령·KCSC·KIPO)·도구 메뉴의 한국 전용 항목(단어장 생성·동시 생성·사전 구역 전체·법령·KCSC·KIPO·번역)이
   **숨김이고 비활성** — 비활성으로만 두지 않는다(§7)
C. en: **API 키를 모두 넣고 게이팅을 다시 불러도** 계속 숨김(§11.12 게이팅과 한 함수 — 서로 되돌리지 않는다)
D. en: 우측 창의 단어장 탭이 숨겨진다
E. en: 처리기를 직접 불러도(단축키·우클릭·자동 후속 작업의 길) 아무 창도 뜨지 않는다
F. en: 즐겨찾기 메뉴에 법령·KCSC·KIPO 구역이 없다(자료는 그대로 남는다)
G. en: 설정 창의 한국 사전·API 키 묶음과 번역 묶음, 병합 창의 '단어장 자동 생성' 이 숨겨진다
H. en: 메뉴 막대가 영어다 · 스캔 문서 OCR 제안은 단어장 없이 OCR 만 묻는다
I. ko: 키가 있으면 모두 보이고 켜진다(종전과 같다)
"""
import os, sys, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QGroupBox, QCheckBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_i18n_switch_%d" % os.getpid())   # 빈 설정 폴더
from viewer import i18n, settings_store
SETDIR = settings_store.settings_dir()
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


# 창이 뜨면 기록만 하고 막지 않는다(검사가 멈추지 않게)
popups = []
for _n in ("warning", "information", "question", "critical"):
    setattr(QMessageBox, _n, staticmethod(
        lambda *a, _n=_n, **k: (popups.append((_n, a[1] if len(a) > 1 else "")), QMessageBox.StandardButton.No)[1]))
QDialog.exec = lambda self, *a, **k: (popups.append(("exec", type(self).__name__)), 0)[1]

KEYS = {"law_oc": "x", "kcsc_key": "x", "kipo_signkey": "x", "translate_auth": "login",
        "anthropic_api_key": "x"}


def _vis(btn_name, mw):
    b = getattr(mw, btn_name, None)
    a = getattr(b, "_tb_action", None)
    return bool(b is not None and a is not None and a.isVisible())


def build(lang):
    i18n.install(app, lang)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw._law_favorites = [{"name": "건축법", "kind_label": "법률"}]
    mw._kcsc_favorites = [{"name": "KDS 14", "category": "설계기준"}]
    mw._kipo_favorites = [{"name": "특허 1"}]
    return mw


BTNS = ("_btn_law", "_btn_kcsc", "_btn_kipo", "_btn_tr", "_btn_vm_study", "_btn_build_study")
try:
    # ── en ──
    mw = build("en")
    chk(not i18n.korea_only_visible(), "전제: en 에서는 한국 전용 아님")
    shown = [b for b in BTNS if _vis(b, mw)]
    chk(not shown, "A en 툴바의 한국 전용 단추가 숨겨진다", str(shown))

    def menu_state(mw):
        va = mw._view_acts
        acts = [va["study"], va["law"], va["kcsc"], va["kipo"], mw._act_law, mw._act_kcsc,
                mw._act_kipo, mw._act_tr_files] + list(mw._ko_only_acts)
        return acts, [a.text() for a in acts if a.isVisible() or a.isEnabled()]
    acts, bad = menu_state(mw)
    chk(len(acts) >= 19, "B 한국 전용 메뉴 항목을 모두 잡았다", str(len(acts)))
    chk(not bad, "B en 메뉴 항목이 숨김·비활성", str(bad))

    mw._gate_api_dependent_ui(dict(mw._prefs, **KEYS))           # 키를 넣고 설정 확인한 것과 같다
    _, bad = menu_state(mw)
    shown = [b for b in BTNS if _vis(b, mw)]
    chk(not bad and not shown, "C en 키를 넣고 게이팅을 다시 불러도 계속 숨김", str(bad + shown))

    i = mw.search_tabs.indexOf(mw.study_panel)
    chk(i >= 0 and not mw.search_tabs.isTabVisible(i), "D en 우측 단어장 탭 숨김")
    chk(mw.search_tabs.currentWidget() is not mw.study_panel, "D en 단어장 탭이 열려 있지 않다")

    popups.clear()
    for nm in ("_vm_study", "_action_build_study", "_action_build_study_and_bookmarks",
               "_action_law_search", "_action_kcsc_search", "_action_kipo_search",
               "_action_translate_files", "_action_dict_manager", "_action_import_glossary",
               "_action_export_dict", "_action_backup_dict", "_action_restore_dict",
               "_action_online_enrich", "_action_sanitize_dict", "_action_reclassify_onterm",
               "_action_save_csv_sample", "_action_translate_pdf"):
        getattr(mw, nm)()
    mw._on_create_study_requested("C:/x.pdf")
    mw._action_edit_glossary("C:/x.pdf")
    mw._action_translate_file("C:/x.pdf")
    app.processEvents()
    chk(not popups, "E en 처리기를 직접 불러도 창이 뜨지 않는다", str(popups[:5]))
    chk(mw.search_tabs.currentWidget() is not mw.study_panel, "E en _vm_study 가 단어장 탭을 열지 않는다")

    mw._refresh_favorites_menu()
    texts = [a.text() for a in mw.menu_favorites.actions()]
    leak = [t for t in texts if any(k in t for k in ("건축법", "KDS 14", "특허 1", "Law", "KCSC", "KIPO"))]
    chk(not leak, "F en 즐겨찾기 메뉴에 법령·KCSC·KIPO 구역이 없다", str(leak))
    chk(mw._law_favorites and mw._kcsc_favorites and mw._kipo_favorites, "F 즐겨찾기 자료는 지우지 않는다")

    from viewer.widgets.settings_dialog import SettingsDialog
    d = SettingsDialog(dict(mw._prefs), parent=mw, host=mw); d.show(); app.processEvents()
    grp_titles = [g.title() for g in d.findChildren(QGroupBox) if g.isVisible()]
    ko_grps = [t for t in grp_titles if t in (i18n.tr("인터넷 사전 (단어장)"), i18n.tr("번역 (Claude)"))]
    chk(not ko_grps, "G en 설정 창의 한국 사전·키·번역 묶음 숨김", str(ko_grps))
    d.close()
    from viewer.widgets.merge_dialog import MergeFilesDialog
    md = MergeFilesDialog([], parent=mw); md.show(); app.processEvents()
    chk(not md.chk_auto.isVisible(), "G en 병합 창의 '단어장 자동 생성' 숨김")
    md.chk_auto.setChecked(True)
    chk(md.auto_build() is False,
        "G en 숨긴 단어장 자동 생성은 켜져도 쓰이지 않는다")
    md.close()

    titles = [a.text() for a in mw.menuBar().actions()]
    chk("&File" in titles or "File" in [t.replace("&", "") for t in titles], "H en 메뉴 막대가 영어", str(titles))
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer", "app.py"), encoding="utf-8").read()
    i0 = src.index("def _maybe_offer_ocr")
    body = src[i0:src.index("\n    def ", i0 + 10)]
    chk("korea_only_visible()" in body and "self._action_ocr_read()" in body,
        "H en 스캔 문서 제안은 단어장 없이 OCR 만(_maybe_offer_ocr)")
    mw.close()

    # ── ko ──
    mw2 = build("ko")
    mw2._gate_api_dependent_ui(dict(mw2._prefs, **KEYS))
    hidden = [b for b in BTNS if not _vis(b, mw2)]
    chk(not hidden, "I ko 키가 있으면 한국 전용 단추가 보인다", str(hidden))
    acts, _ = menu_state(mw2)
    off = [a.text() for a in acts if not (a.isVisible() and (a.isEnabled() or a.isSeparator()))]
    chk(not off, "I ko 메뉴 항목이 보이고 켜진다", str(off))
    i = mw2.search_tabs.indexOf(mw2.study_panel)
    chk(mw2.search_tabs.isTabVisible(i), "I ko 단어장 탭이 보인다")
    mw2._refresh_favorites_menu()
    texts = [a.text() for a in mw2.menu_favorites.actions()]
    chk(any("건축법" in t for t in texts) and any("KDS 14" in t for t in texts),
        "I ko 즐겨찾기 메뉴에 법령·KCSC 구역이 보인다")
    mw2.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(SETDIR), ignore_errors=True)
    i18n.install(None, "ko")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
