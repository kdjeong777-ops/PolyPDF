# -*- coding: utf-8 -*-
"""다국어(언어팩) SOT Phase 0 — 번역 기반·언어팩 읽기·언어 설정 (261008).

A. 한국어(기본)는 원문 그대로 · 한국 전용 기능 보임
B. 언어팩 .po → .mo(Babel) → tr/trp/trn · 대체 사슬(고른 언어 → fallback → 한국어 원문)
C. available_languages — 한국어 먼저, 팩에서, 가짜 언어·잘못된 팩·RTL 은 빠진다
D. 팩이 없으면 en → ko 로 물러남 · POLYPDF_LANG 이 설정보다 앞선다
E. initial_language — 설정 파일 있음 → ko · 설치 언어 · OS 언어(ko-KR 꼴·주 언어) · 없으면 en
F. peek_pref — 언어만 읽고 설정 파일을 건드리지 않는다
G. 내장 en 팩·Qt 기본 번역(ko 면 메시지 상자 단추가 '예')
H. 설정 창 콤보·허용목록·재시작 안내·첫 설정(실제 MainWindow) · 개인 항목(배포 기본값 제외)
"""
import os, sys, json, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


HERE = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp(prefix="polypdf_i18n_"))


def make_pack(code, meta, entries, plural="nplurals=2; plural=(n != 1);"):
    """entries: [(msgid, msgstr | [단,복], context|None)]"""
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo
    d = root / code / "LC_MESSAGES"
    d.mkdir(parents=True, exist_ok=True)
    cat = Catalog(locale=None, domain="polypdf")
    cat._num_plurals, cat._plural_expr = int(plural.split("nplurals=")[1].split(";")[0]), plural.split("plural=")[1].rstrip(";")
    for mid, mstr, ctx in entries:
        if isinstance(mstr, list):
            cat.add((mid, mid), tuple(mstr), context=ctx)
        else:
            cat.add(mid, mstr, context=ctx)
    with open(d / "polypdf.mo", "wb") as f:
        write_mo(f, cat)
    (root / code / "pack.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


try:
    from viewer import i18n

    # ── A ──
    i18n.install(None, "ko")
    chk(i18n.language() == "ko" and i18n.tr("저장") == "저장" and i18n.korea_only_visible(),
        "A 한국어는 원문 그대로, 한국 전용 기능 보임")
    chk(i18n.trn("파일 {n}개", 3) == "파일 {n}개" and i18n.trp("메뉴", "열기") == "열기", "A trn·trp 도 원문")

    # ── B·C·D — 가짜 팩 폴더 ──
    make_pack("en", {"code": "en", "name": "English", "fallback": [], "status": "complete"},
              [("저장", "Save", None), ("열기", "Open", "메뉴"), ("열기", "Expand", "트리"),
               ("파일 {n}개", ["{n} file", "{n} files"], None), ("닫기", "Close", None)])
    make_pack("ja", {"code": "ja", "name": "日本語", "fallback": ["en"], "status": "partial"},
              [("저장", "保存", None)], plural="nplurals=1; plural=0;")
    make_pack("ar", {"code": "ar", "name": "العربية", "direction": "rtl"}, [])
    make_pack("xx", {"code": "zz", "name": "Wrong"}, [])                 # 코드 ≠ 폴더
    (root / "qps_ploc").mkdir()
    i18n.pack_dir = lambda: root

    langs = i18n.available_languages()
    chk([c for c, _n, _s in langs] == ["ko", "en", "ja"], "C 한국어 먼저, 팩에서, 가짜·잘못된·RTL 팩은 빠진다", str(langs))
    chk(dict((c, n) for c, n, _s in langs)["ja"] == "日本語" and dict((c, s) for c, _n, s in langs)["ja"] == "partial",
        "C 자기 언어 이름·상태")

    i18n.install(None, "ja")
    chk(i18n.tr("저장") == "保存", "B 고른 언어 번역")
    chk(i18n.tr("닫기") == "Close", "B 없으면 fallback(en)")
    chk(i18n.tr("없는 문구") == "없는 문구", "B 어디에도 없으면 한국어 원문")
    chk(not i18n.korea_only_visible(), "B 한국어가 아니면 한국 전용 기능 숨김")
    i18n.install(None, "en")
    chk(i18n.trp("메뉴", "열기") == "Open" and i18n.trp("트리", "열기") == "Expand", "B trp 문맥별 번역")
    chk(i18n.trn("파일 {n}개", 1).format(n=1) == "1 file" and i18n.trn("파일 {n}개", 3).format(n=3) == "3 files",
        "B trn 복수형(en)")
    chk(i18n.tr("") == "" and i18n.tr(None) is None,
        "B 빈 값은 그대로(gettext 는 빈 키에 .mo 머리를 돌려준다 — tr(변수) 가 비었을 때)")

    # D
    i18n.install(None, "de")
    chk(i18n.language() == "en", "D 팩이 없는 언어면 en 으로 물러남", i18n.language())
    os.environ["POLYPDF_LANG"] = "ja"
    i18n.install(None, "en")
    chk(i18n.language() == "ja", "D POLYPDF_LANG 이 설정보다 앞선다")
    os.environ.pop("POLYPDF_LANG")

    # ── E ──
    chk(i18n.initial_language(True, ["ja-JP"], "en") == "ko", "E 설정 파일이 이미 있으면 ko(업데이트로 언어가 바뀌지 않게)")
    chk(i18n.initial_language(False, ["ko-KR"], "en") == "en", "E 설치 프로그램이 남긴 언어가 OS 언어보다 앞선다")
    chk(i18n.initial_language(False, ["ja-JP", "en-US"], "") == "ja", "E OS 언어 ko-KR 꼴 → 주 언어로 맞춤")
    chk(i18n.initial_language(False, ["ko-KR"], "") == "ko", "E OS 가 한국어면 ko")
    chk(i18n.initial_language(False, ["fr-FR"], "de") == "en", "E 맞는 팩이 없으면 en")
    chk(i18n.normalize("zh-tw") == "zh_TW" and i18n.normalize("EN") == "en", "E 코드 꼴 맞춤")

    # ── F ──
    from viewer import settings_store
    sp = settings_store.settings_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"schema_version": 1, "preferences": {"language": "en"}}), encoding="utf-8")
    before = (sp.stat().st_mtime, sp.read_bytes())
    time.sleep(0.05)
    chk(settings_store.peek_pref("language") == "en", "F peek_pref 가 언어를 읽는다")
    chk((sp.stat().st_mtime, sp.read_bytes()) == before, "F 옛 스키마여도 파일을 고치지 않는다(마이그레이션·백업 없음)")
    sp.unlink()
    chk(settings_store.peek_pref("language") is None, "F 파일이 없으면 None")

    # ── G — 내장 팩과 Qt 기본 번역 ──
    import importlib, subprocess
    subprocess.run([sys.executable, str(HERE / "scripts" / "i18n.py"), "compile"], cwd=str(HERE),
                   capture_output=True)
    importlib.reload(i18n)
    chk("en" in [c for c, _n, _s in i18n.available_languages()], "G 내장 en 팩이 목록에 있다")
    chk((HERE / "resources" / "locale" / "en" / "LC_MESSAGES" / "polypdf.mo").is_file(), "G compile 이 .mo 를 만든다")
    i18n.install(app, "ko")
    box = QMessageBox(QMessageBox.Icon.Question, "t", "t",
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    chk(box.button(QMessageBox.StandardButton.Yes).text().replace("&", "").startswith("예"),
        "G ko 면 Qt 기본 단추가 한국어('예')", box.button(QMessageBox.StandardButton.Yes).text())

    # ── H — 실제 MainWindow ──
    from viewer.app import MainWindow
    from viewer.widgets.settings_dialog import SettingsDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    chk(mw._prefs.get("language") in ("ko", "en"), "H 시작 때 설정에 언어가 정해진다", str(mw._prefs.get("language")))
    dlg = SettingsDialog(dict(mw._prefs), mw, host=mw)
    codes = [dlg.cmb_language.itemData(i) for i in range(dlg.cmb_language.count())]
    chk(codes == [c for c, _n, _s in i18n.available_languages()], "H 설정 콤보 = available_languages", str(codes))
    dlg.cmb_language.setCurrentIndex(codes.index("en"))
    newp = dlg.result_prefs()
    chk(newp.get("language") == "en", "H 설정 창이 language 를 내보낸다")
    mw._prefs["language"] = "ko"
    mw._apply_prefs(newp)
    chk(mw._prefs.get("language") == "en", "H 허용목록을 통과한다(조용히 사라지지 않음)")
    chk(mw._build_settings_payload()["preferences"].get("language") == "en", "H 저장 페이로드까지 간다")
    seen = []
    mw._offer_language_restart = lambda: seen.append(1)
    from viewer.widgets import settings_dialog as _sd
    _sd.SettingsDialog.exec = lambda self: (self.cmb_language.setCurrentIndex(
        self.cmb_language.findData("ko")), self.DialogCode.Accepted)[1]
    mw._save_settings_now = lambda: None
    mw.action_open_settings()
    chk(seen == [1] and mw._prefs.get("language") == "ko", "H 언어를 바꾸면 재시작 안내")
    seen.clear()
    mw.action_open_settings()
    chk(seen == [], "H 언어가 그대로면 안내하지 않는다")
    chk("language" in settings_store.PERSONAL_PREF_KEYS, "H 개인 항목")
    dist = settings_store.extract_distributable_defaults({"preferences": {"language": "en", "theme": "dark"}})
    chk("language" not in (dist.get("preferences") or {}), "H 배포 기본값에서 빠진다")
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
