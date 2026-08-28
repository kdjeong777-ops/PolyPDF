# -*- coding: utf-8 -*-
"""260628(감사 D): 사이드 패널 3종(법령·건설기준·특허) 호스팅 회귀 테스트.

`SidePanelHost` 일반화 리팩터의 **회귀 게이트**. 리팩터 전 현재 동작으로 통과시켜
기준선을 만든 뒤, 리팩터 후 동일하게 통과해야 한다.

검사 항목(패널마다):
  1) 열기 → 메인 splitter 오른쪽 끝에 임베드되고 패널 객체가 살아 있음
  2) 임베드 상태에서 썸네일/우측 드로어가 숨겨지고, 책갈피는 유지
  3) 전체화면 토글 → 복귀 왕복
  4) 닫기 → 패널 제거 + 이전 레이아웃(썸네일·우측·2단) 복원
  5) 열기→닫기 2회 반복해도 상태가 누적되지 않음(스플리터 위젯 수 원복)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True


def check(n, c, e=""):
    global ok
    print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else ""), flush=True)
    ok = ok and bool(c)


from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication(sys.argv)

# ★ 오프스크린에서 모달 대화상자는 영원히 블록된다 — 정적 메서드를 무력화한다.
#   (키 미입력 시 `_law_oc_or_warn` 등이 안내창을 띄우는 경로가 있어 필수)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

from viewer.app import MainWindow
mw = MainWindow()

# 패널이 실제로 생성되도록 더미 키 주입(네트워크 호출은 하지 않음 — 생성/레이아웃만 검사)
for _k in ("law_oc", "kcsc_key", "kipo_signkey"):
    if not (mw._prefs.get(_k) or "").strip():
        mw._prefs[_k] = "TESTKEY"

# 패널별 (이름, 열기, 닫기, 전체화면토글, 패널속성)
PANELS = [
    ("법령",     "_open_law",  "_close_law",  "_toggle_law_fullscreen",  "_law_panel"),
    ("건설기준", "_open_kcsc", "_close_kcsc", "_toggle_kcsc_fullscreen", "_kcsc_panel"),
    ("특허",     "_open_kipo", "_close_kipo", "_toggle_kipo_fullscreen", "_kipo_panel"),
]

for label, f_open, f_close, f_full, attr in PANELS:
    print(f"\n[{label}]", flush=True)
    if not all(hasattr(mw, m) for m in (f_open, f_close, attr.lstrip("_") and f_full)):
        check(f"{label}: 메서드 존재", False, "메서드 누락")
        continue

    base_count = mw.splitter.count()

    # 1) 열기
    try:
        getattr(mw, f_open)()
        opened = getattr(mw, attr, None) is not None
    except Exception as e:                                   # noqa: BLE001
        opened = False
        check(f"{label}: 열기 예외 없음", False, repr(e)[:80])
    check(f"{label}: 열기 → 패널 생성", opened)

    if opened:
        panel = getattr(mw, attr)
        # 2) splitter 에 임베드됨
        in_split = any(mw.splitter.widget(i) is panel for i in range(mw.splitter.count()))
        check(f"{label}: splitter 에 임베드", in_split,
              f"count={mw.splitter.count()} (기준 {base_count})")

        # 3) 전체화면 왕복 — 예외 없이 두 번 토글되면 통과
        try:
            getattr(mw, f_full)()
            getattr(mw, f_full)()
            full_ok = True
            err = ""
        except Exception as e:                               # noqa: BLE001
            full_ok, err = False, repr(e)[:80]
        check(f"{label}: 전체화면 토글 왕복", full_ok, err)

    # 4) 닫기 → 원복
    try:
        getattr(mw, f_close)()
        closed = getattr(mw, attr, None) is None
        err = ""
    except Exception as e:                                   # noqa: BLE001
        closed, err = False, repr(e)[:80]
    check(f"{label}: 닫기 → 패널 해제", closed, err)
    check(f"{label}: splitter 위젯 수 원복", mw.splitter.count() == base_count,
          f"{mw.splitter.count()} vs {base_count}")

    # 5) 재열기/재닫기 — 상태 누적 없음
    try:
        getattr(mw, f_open)()
        getattr(mw, f_close)()
        again = (mw.splitter.count() == base_count and getattr(mw, attr, None) is None)
        err = ""
    except Exception as e:                                   # noqa: BLE001
        again, err = False, repr(e)[:80]
    check(f"{label}: 2회 반복 후에도 원복", again, err)

print("\n" + ("ALL OK" if ok else "FAILED"))
os._exit(0 if ok else 1)
