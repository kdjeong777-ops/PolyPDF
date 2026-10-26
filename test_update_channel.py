# -*- coding: utf-8 -*-
"""260628-6: 업데이트 채널 규칙 회귀 테스트 (§14.5 U9).

검증 대상
  ① 1.0 이전에는 저장값과 무관하게 항상 beta 채널(메뉴는 체크+비활성)
  ② 기본값은 stable — 1.0 이후 '설정을 만진 적 없는' 사용자가 베타에 고착되지 않는다
  ③ 사용자가 메뉴로 고르면 update_channel_explicit=True 가 찍히고 저장 페이로드에 살아남는다
  ④ SemVer: 프리릴리즈 < 같은 X.Y.Z 정식, 정식 뒤 같은 X.Y.Z 베타는 더 낮다(운영 규칙 근거)

★ 이 테스트는 settings.json 의 공유 설정을 건드리므로 §14.7 규칙대로
  **시작 시 스냅샷 → 끝에 원복** 한다. ②는 '키가 없는 깨끗한 프로필' 에서만
  의미가 있으므로, MainWindow 생성 **전에** 해당 키를 지운 상태로 검사한다.
"""
import os, sys, io, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)


from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
# 261025-7: 사용자 실제 설정 폴더(색인·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_update_channel_%d" % os.getpid())
from viewer import settings_store, updater

KEYS = ("update_channel", "update_channel_explicit")
SPATH = settings_store.settings_path("settings.json")
_orig_raw = io.open(SPATH, encoding="utf-8").read() if SPATH.exists() else None


def restore():
    """공유 설정 원복 — 다른 테스트를 오염시키지 않는다(§14.7)."""
    try:
        if _orig_raw is None:
            if SPATH.exists():
                SPATH.unlink()
        else:
            io.open(SPATH, "w", encoding="utf-8", newline="\n").write(_orig_raw)
    except Exception:
        pass


# ── 깨끗한 프로필 만들기: 두 키만 제거 ────────────────────────────────────
try:
    _d = json.loads(_orig_raw) if _orig_raw else {}
    for _k in KEYS:
        _d.get("preferences", {}).pop(_k, None)
        _d.pop(_k, None)
    io.open(SPATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(_d, ensure_ascii=False, indent=2))
except Exception as e:                                   # noqa: BLE001
    print("  (준비 실패, 계속 진행):", e)

try:
    from viewer.app import MainWindow
    mw = MainWindow()

    # ---------- ① 1.0 이전 강제 beta / 1.0 이후 설정을 따름 ----------
    # 261025-8(릴리스 SOT §2.3): 첫 정식판이 1.0.0 — 판에 따라 두 갈래로 본다(버전을 올려도 이 검사가 깨지지 않게)
    cur = updater.current_version()
    pre10 = int((cur.lstrip("vV").split(".")[0]) or "0") == 0
    # 261026-5(마스터 §14.5 U14): 두 체크는 도움말 탭이 아니라 업데이트 확인 창 아래 — 그 창의 체크로 본다
    from viewer.widgets.update_dialog import UpdateDialog
    _ud = UpdateDialog(None, cur, "check", mw, options=mw._update_options())
    if pre10:
        check("1.0 이전: 베타 체크됨", _ud.chk_beta.isChecked(), cur)
        check("1.0 이전: 베타 체크 비활성(선택 불가)", not _ud.chk_beta.isEnabled())
    else:
        check("1.0 이후: 베타 체크를 고를 수 있다", _ud.chk_beta.isEnabled(), cur)
        check("1.0 이후: 깨끗한 프로필은 베타 체크 꺼짐(정식만)", not _ud.chk_beta.isChecked())
    _ud.done(0)

    # ---------- ② 깨끗한 프로필의 기본값 ----------
    check("update_channel 기본값 = stable",
          str(mw._prefs.get("update_channel", "")).lower() == "stable",
          repr(mw._prefs.get("update_channel")))
    check("update_channel_explicit 기본값 = False",
          mw._prefs.get("update_channel_explicit") is False,
          repr(mw._prefs.get("update_channel_explicit")))

    # ---------- ③ 명시 선택이 저장 페이로드에 살아남는가 ----------
    mw._on_toggle_update_channel(True)
    check("메뉴로 베타 선택 → channel=beta", mw._prefs.get("update_channel") == "beta")
    check("메뉴로 선택 → explicit=True", mw._prefs.get("update_channel_explicit") is True)
    payload = mw._build_settings_payload()
    prefs_out = payload.get("preferences", payload)
    check("저장 페이로드에 update_channel_explicit 포함(누락 시 유실)",
          prefs_out.get("update_channel_explicit") is True,
          f"payload={prefs_out.get('update_channel_explicit')!r}")
    mw._on_toggle_update_channel(False)
    check("메뉴로 정식 선택 → channel=stable", mw._prefs.get("update_channel") == "stable")

    # ---------- ④ SemVer 운영 규칙의 근거 ----------
    check("프리릴리즈 < 같은 X.Y.Z 정식", updater.is_newer("v0.45.0", "v0.45.0-beta.101"))
    check("정식 뒤 같은 X.Y.Z 베타는 더 낮다(→ 0.46.0-beta.1 로 올려야 함)",
          not updater.is_newer("v0.45.0-beta.102", "v0.45.0"))
    check("베타끼리는 번호 순", updater.is_newer("v0.45.0-beta.101", "v0.45.0-beta.79"))
    check("옛 v2.x 는 v0.45 보다 높게 정렬됨(원격에 두면 다운그레이드 유발)",
          updater.is_newer("v2.41.0", "v0.45.0-beta.101"))
    check("접미사 기준 프리릴리즈 판정",
          updater.is_prerelease_tag("v0.45.0-beta.101")
          and not updater.is_prerelease_tag("v0.45.0"))

    # ---------- ⑤ 첫 정식판 1.0.0 과 그 뒤 번호 체계(릴리스 SOT §2.3, 261025-8) ----------
    def _rel(tag, draft=False):
        return {"tag_name": tag, "draft": draft, "body": "", "html_url": "", "published_at": "2026-10-25",
                "assets": [{"name": "PolyPDF-win.zip",
                            "browser_download_url": "https://github.com/x/y/releases/download/%s/PolyPDF-win.zip" % tag}]}
    _orig_get, _orig_cur = updater._get_json, updater.current_version
    try:
        rels = [_rel("v1.0.0"), _rel("v0.45.0-beta.299"), _rel("v0.45.0-beta.298"), _rel("components")]
        updater._get_json = lambda url, timeout: rels
        updater.current_version = lambda: "0.45.0-beta.299"
        check("beta.299(베타 채널) → 1.0.0 을 새 판으로", (updater.check_latest("o/r", channel="beta") or {}).get("tag") == "v1.0.0")
        check("정식 채널도 1.0.0", (updater.check_latest("o/r", channel="stable") or {}).get("tag") == "v1.0.0")
        check("1.0.0 은 beta.299 보다 새 판", updater.is_newer("1.0.0", "0.45.0-beta.299"))
        rels[:] = [_rel("v1.1.0-beta.2"), _rel("v1.0.1"), _rel("v1.0.0"), _rel("v1.1.0-beta.3", draft=True)]
        updater.current_version = lambda: "1.0.0"
        check("1.0.0 정식 채널 → 버그 수정 정식 1.0.1(베타 1.1.0-beta.2 는 건너뜀)",
              (updater.check_latest("o/r", channel="stable") or {}).get("tag") == "v1.0.1")
        check("1.0.0 베타 채널 → 1.1.0-beta.2(초안은 건너뜀)",
              (updater.check_latest("o/r", channel="beta") or {}).get("tag") == "v1.1.0-beta.2")
        check("베타 다음 같은 번호의 정식은 더 새 판(1.1.0-beta.N → 1.1.0)", updater.is_newer("1.1.0", "1.1.0-beta.9"))
        # 261026-3(릴리스 SOT §2.3): 끝자리 = 버그 수정·작은 UI — 그 베타는 1.0.0 보다 새 판이고 1.0.1 정식보다 낮다
        check("수정 베타 1.0.1-beta.1 은 1.0.0 보다 새 판, 1.0.1 보다 낮다",
              updater.is_newer("1.0.1-beta.1", "1.0.0") and updater.is_newer("1.0.1", "1.0.1-beta.1"))
        check("기능 묶음 1.1.0 은 수정 1.0.9 보다 새 판", updater.is_newer("1.1.0", "1.0.9"))
    finally:
        updater._get_json, updater.current_version = _orig_get, _orig_cur
finally:
    restore()

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2 (§14.7): sys.exit 는 Qt teardown 에서 0xC0000409 로 죽어 종료코드가 무의미해진다.
sys.stdout.flush()
os._exit(0 if ok else 1)
