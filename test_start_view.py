# -*- coding: utf-8 -*-
"""260628-13: 시작 보기 상태 회귀 테스트 — '1단'(패널 없음) + 쪽 맞춤.

사용자 요청: 프로그램을 켜면 검색창 없는 1단 모드에 쪽맞춤으로 보여야 한다.
마지막 세션이 2단이었거나 패널이 열려 있었더라도 시작 상태는 항상 같아야 한다.

★ 이 테스트는 저장 설정(panels_visible·fit_mode·split)에 영향을 주므로
  §14.7 대로 시작 시 스냅샷 → 끝에 원복한다.
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
from viewer import settings_store

SPATH = settings_store.settings_path("settings.json")
_orig = io.open(SPATH, encoding="utf-8").read() if SPATH.exists() else None


def restore():
    try:
        if _orig is None:
            if SPATH.exists():
                SPATH.unlink()
        else:
            io.open(SPATH, "w", encoding="utf-8", newline="\n").write(_orig)
    except Exception:
        pass


# 마지막 세션이 '2단 + 패널 열림 + 폭 맞춤' 이었던 상황을 만든다 — 그래도 시작은 1단이어야 한다.
try:
    d = json.loads(_orig) if _orig else {}
    d["fit_mode"] = "폭 맞춤"
    d["panels_visible"] = {"search_results": True, "screenshots": True}
    io.open(SPATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(d, ensure_ascii=False, indent=2))
except Exception as e:                                   # noqa: BLE001
    print("  (준비 실패, 계속 진행):", e)

try:
    from viewer.app import MainWindow
    mw = MainWindow()
    mv = mw.main_view

    check("2단 아님(1단)", mw.act_split.isChecked() is False)
    check("검색·단어장 패널 숨김", mw.act_toggle_search.isChecked() is False)
    check("스크린샷 패널 숨김", mw.act_toggle_shot.isChecked() is False)
    check("오른쪽 창 숨김", not mw._mv[1].isVisible())
    check("맞춤 = 쪽 맞춤(저장값 '폭 맞춤' 을 덮어씀)",
          mv._fit_mode == mv.FIT_PAGE, repr(mv._fit_mode))
    check("보기 콤보 표시도 동기화", mv.cmb_fit.currentText() == mv.FIT_PAGE,
          repr(mv.cmb_fit.currentText()))

    # 패널 툴바 '1단' 버튼과 같은 상태여야 한다(별도 로직 중복 금지)
    mw.act_toggle_search.setChecked(True)
    mw._vm_single()
    check("'1단' 버튼과 동일한 결과",
          mw.act_split.isChecked() is False
          and mw.act_toggle_search.isChecked() is False
          and mw.act_toggle_shot.isChecked() is False)

    # 끌 수 있어야 한다 — start_view_single=False 면 적용하지 않는다
    mw._prefs["start_view_single"] = False
    mw.act_toggle_search.setChecked(True)
    mw._apply_start_view()
    check("start_view_single=False 면 건드리지 않음",
          mw.act_toggle_search.isChecked() is True)

    check("저장 페이로드에 start_view_single 포함(누락 시 유실)",
          "start_view_single" in (mw._build_settings_payload().get("preferences", {})))
finally:
    restore()

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.stdout.flush()
os._exit(0 if ok else 1)
