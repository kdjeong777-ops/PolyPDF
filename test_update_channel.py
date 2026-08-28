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

    # ---------- ① 1.0 이전 강제 beta ----------
    cur = updater.current_version()
    pre10 = int((cur.lstrip("vV").split(".")[0]) or "0") == 0
    check("현재 빌드는 1.0 이전(major 0)", pre10, cur)
    check("1.0 이전: 베타 메뉴 체크됨", mw._act_update_beta.isChecked())
    check("1.0 이전: 베타 메뉴 비활성(선택 불가)", not mw._act_update_beta.isEnabled())

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
finally:
    restore()

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2 (§14.7): sys.exit 는 Qt teardown 에서 0xC0000409 로 죽어 종료코드가 무의미해진다.
sys.stdout.flush()
os._exit(0 if ok else 1)
