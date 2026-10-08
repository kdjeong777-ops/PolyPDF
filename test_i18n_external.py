"""다국어 SOT §3.4 — 외부 언어팩 (Phase 8, 261008-29)

외부 팩 = 설정 폴더의 `locale\\<코드>\\`(`pack.json` + `LC_MESSAGES\\polypdf.mo`). 기본 꺼짐 — 설정 화면의
'외부 언어팩 사용' 을 켜고 다시 시작하면 읽는다(사용자 결정). **잘못된 팩이 앱을 깨지 않는다**(완료 조건).

A. 꺼져 있으면 외부 폴더의 팩은 목록에도 번역에도 쓰이지 않는다(설정 키가 없으면 꺼짐)
B. 켜면 외부 팩이 언어 목록에 더해지고 번역된다
C. 같은 코드면 외부가 내장을 덮는다 — 단, 외부가 잘못됐으면 내장을 쓴다
D. 잘못된 팩(깨진 JSON·코드≠폴더·RTL·fallback 형식·.mo 없음·깨진 .mo)은 무시되고 예외가 나지 않는다
E. 번역의 자리표시가 원문과 다르면 원문을 쓴다(쓰는 곳의 .format() 이 KeyError 로 깨지지 않게) — 단수·복수·문맥
F. 고른 언어의 팩이 없으면 물러나고(fallback_from), 설정 값은 바꾸지 않으며, 실제 창이 상태줄에 한 번 알린다
G. 설정 창의 체크박스·결과·허용목록(_apply_prefs)·개인 항목(PERSONAL_PREF_KEYS)
H. 깨진 외부 팩을 고른 채 실제 MainWindow 가 뜬다
"""
import os, sys, json, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_i18n_ext_%d" % os.getpid())
from viewer import i18n, settings_store
SET = Path(settings_store.settings_dir())
EXT = i18n.external_dir()
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pack(code, entries, meta=None, mo=True, raw_meta=None, plural=None):
    """외부 팩 하나를 만든다. entries = {원문: 번역} 또는 {(문맥, 원문): 번역}."""
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo
    d = EXT / code
    (d / "LC_MESSAGES").mkdir(parents=True, exist_ok=True)
    m = {"code": code, "name": code.upper() + " ext", "fallback": [], "direction": "ltr", "status": "partial"}
    m.update(meta or {})
    (d / "pack.json").write_text(raw_meta if raw_meta is not None else json.dumps(m), encoding="utf-8")
    if mo is True:
        cat = Catalog(locale="en")
        for k, v in entries.items():
            if isinstance(k, tuple):
                cat.add(k[1], v, context=k[0])
            else:
                cat.add(k, v)
        for (s, p) in (plural or {}).items():
            cat.add((s, s), p)
        with open(d / "LC_MESSAGES" / "polypdf.mo", "wb") as f:
            write_mo(f, cat)
    elif mo == "garbage":
        (d / "LC_MESSAGES" / "polypdf.mo").write_bytes(b"\x00not a mo file\xff" * 10)


def codes():
    return [c for c, _n, _s in i18n.available_languages()]


try:
    EXT.mkdir(parents=True, exist_ok=True)
    pack("ja", {"저장": "保存(外部)"})

    # ── A ──
    i18n.install(None, "ja")                                  # 설정 파일 없음 → 꺼짐
    chk(not i18n.external_enabled() and "ja" not in codes(), "A 기본 꺼짐 — 외부 팩이 목록에 없다", str(codes()))
    chk(i18n.language() != "ja" and i18n.tr("저장") != "保存(外部)", "A 꺼져 있으면 외부 팩으로 번역하지 않는다")

    # ── B ──
    i18n.install(None, "ja", external=True)
    chk("ja" in codes() and i18n.language() == "ja" and i18n.tr("저장") == "保存(外部)", "B 켜면 외부 팩이 목록·번역에 쓰인다")
    chk(i18n.fallback_from() == "", "B 물러나지 않았다")

    # ── C ──
    pack("en", {"저장": "Save (external)"}, {"status": "complete"})
    i18n.install(None, "en", external=True)
    chk(i18n.tr("저장") == "Save (external)", "C 같은 코드면 외부가 내장을 덮는다")
    chk(i18n.tr("닫기") == "닫기", "C 외부 팩에 없는 문구는 그 팩의 사슬을 따른다(외부 en 은 fallback 없음 → 원문)")
    (EXT / "en" / "pack.json").write_text("{ broken", encoding="utf-8")
    i18n.install(None, "en", external=True)
    chk(i18n.tr("저장") == "Save" and i18n.tr("닫기") == "Close", "C 외부 en 이 잘못되면 내장 en 을 쓴다", i18n.tr("저장"))
    shutil.rmtree(EXT / "en")

    # ── D ──
    bad = {
        "xa": dict(raw_meta="{ not json"),
        "xb": dict(meta={"code": "zz"}),
        "xc": dict(meta={"direction": "rtl"}),
        "xd": dict(meta={"fallback": "en"}),
        "xe": dict(mo=False),
        "xf": dict(mo="garbage"),
    }
    for c, kw in bad.items():
        pack(c, {"저장": "BAD"}, **kw)
    try:
        i18n.install(None, "ja", external=True)
        lst = codes()
        ok = True
    except Exception as e:
        ok, lst = False, str(e)
    chk(ok and not any(c in lst for c in ("xa", "xb", "xc", "xd", "xe", "xf")), "D 형식이 틀린 팩은 목록에서 빠지고 예외가 없다", str(lst))
    for c in ("xa", "xb", "xc", "xd", "xe", "xf"):
        try:
            got = i18n.install(None, c, external=True)
            t = i18n.tr("저장")
            chk(t != "BAD" and got == "en", "D 잘못된 팩 %s 을 고르면 무시하고 en 으로 물러난다(→ %s)" % (c, got), t)
        except Exception as e:
            chk(False, "D 잘못된 팩 %s 에서 예외" % c, repr(e))

    # ── E ──
    pack("jb", {"'{name}' 을 열었습니다": "{nam} を開きました",
                "{n}쪽": "{n} ページ",
                ("메뉴", "열기"): "開く{x}"},
         plural={"파일 {n}개": ("{count} file", "{count} files")})
    i18n.install(None, "jb", external=True)
    s1 = i18n.tr("'{name}' 을 열었습니다")
    chk(s1 == "'{name}' 을 열었습니다" and s1.format(name="a"), "E 자리표시가 다르면 원문(.format 이 깨지지 않음)", s1)
    chk(i18n.tr("{n}쪽") == "{n} ページ", "E 자리표시가 같으면 번역 그대로")
    chk(i18n.trp("메뉴", "열기") == "열기", "E 문맥(trp)도 같은 가드")
    chk(i18n.trn("파일 {n}개", 2).format(n=2) == "파일 2개", "E 복수형(trn)도 같은 가드")

    # ── F ──
    SET.mkdir(parents=True, exist_ok=True)
    (SET / "settings.json").write_text(json.dumps({"preferences": {"language": "qq", "external_language_packs": True}}),
                                       encoding="utf-8")
    got = i18n.install(None, "qq")                            # 설정에서 외부 팩 켜짐을 읽는다
    chk(i18n.external_enabled(), "F 설정 키 external_language_packs 를 읽는다")
    chk(got == "en" and i18n.fallback_from() == "qq", "F 없는 팩 → en 으로 물러나고 그 코드를 기억", got)
    from viewer.app import MainWindow
    from PyQt6.QtCore import QTimer
    msgs = []
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.status.messageChanged.connect(lambda m: msgs.append(m))
    t0 = __import__("time").time()
    while __import__("time").time() - t0 < 2.5:
        app.processEvents()
    chk(any("qq" in m for m in msgs), "F 실제 창이 상태줄에 한 번 알린다", str(msgs[:3]))
    chk(mw._prefs.get("language") == "qq", "F 설정 값은 바꾸지 않는다(팩을 되돌려 넣으면 그대로)", str(mw._prefs.get("language")))

    # ── G ──
    from viewer.widgets.settings_dialog import SettingsDialog
    d = SettingsDialog(dict(mw._prefs), parent=mw, host=mw)
    chk(d.chk_ext_lang.isChecked(), "G 체크박스가 설정을 보인다")
    d.chk_ext_lang.setChecked(False)
    rp = d.result_prefs()
    chk(rp.get("external_language_packs") is False, "G 결과에 들어간다")
    mw._apply_prefs(rp)
    chk(mw._prefs.get("external_language_packs") is False, "G 허용목록(_apply_prefs)이 키를 지킨다")
    chk("external_language_packs" in settings_store.PERSONAL_PREF_KEYS, "G 개인 항목(배포 기본값에 넣지 않는다)")
    d.close(); mw.close()

    # ── H ──
    pack("xg", {"저장": "ok"}, mo="garbage")
    i18n.install(None, "xg", external=True)
    try:
        mw2 = MainWindow(); mw2._skip_save_on_close = True
        app.processEvents()
        chk(len(mw2.menuBar().actions()) > 3, "H 깨진 외부 팩을 고른 채 실제 창이 뜬다")
        mw2.close()
    except Exception as e:
        chk(False, "H 창 생성 예외", repr(e))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    i18n.install(None, "ko", external=False)
    shutil.rmtree(str(SET), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
