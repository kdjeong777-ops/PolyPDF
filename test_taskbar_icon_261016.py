# -*- coding: utf-8 -*-
"""261016-7: 업데이트 뒤 작업 표시줄 흰 백지 — 작업 표시줄 앱 ID(AppUserModelID)를 정한다 (마스터 §14.2).

ID 가 없으면 작업 표시줄은 창 아이콘 대신 exe 아이콘을 Windows 아이콘 캐시에서 찾고, 업데이트('제거 → 설치') 사이에 캐시가
빈 아이콘을 잡으면 흰 백지가 남았다. ID 를 정하면 창 아이콘(앱에 든 icon.png)을 쓴다.

A. `main._set_app_user_model_id()` 가 이 프로세스의 ID 를 `LocalTools.PolyPDF` 로 정한다(Windows 가 돌려주는 값으로 확인)
B. 시험 프로필(`POLYPDF_PROFILE=test`)은 다른 ID — 시험 창이 사용자 창과 한 단추로 묶이지 않는다
C. 설치 프로그램의 시작 메뉴·바탕 화면 바로가기도 같은 ID(`installer/PolyPDF.iss` [Icons])
D. 창을 만들기 전에 부른다 — `main()` 에서 `QApplication(` 보다 앞
E. 앱 아이콘 파일(resources/icon.png)이 있다 — 창 아이콘의 원천
"""
import os, sys, re, ctypes, inspect
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("POLYPDF_PROFILE", None)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def current_id():
    p = ctypes.c_wchar_p()
    hr = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(p))
    val = p.value if hr == 0 else None
    if hr == 0:
        ctypes.windll.ole32.CoTaskMemFree(p)
    return val


try:
    import main
    fn = getattr(main, "_set_app_user_model_id", None)
    chk(callable(fn), "0 main._set_app_user_model_id 가 있다")
    if callable(fn):
        got = fn()
        chk(got == "LocalTools.PolyPDF" and current_id() == "LocalTools.PolyPDF",
            "A 작업 표시줄 앱 ID = LocalTools.PolyPDF", str((got, current_id())))
        os.environ["POLYPDF_PROFILE"] = "test"
        got = fn()
        chk(got == "LocalTools.PolyPDF.test" and current_id() == "LocalTools.PolyPDF.test",
            "B 시험 프로필은 다른 ID", str((got, current_id())))
        os.environ.pop("POLYPDF_PROFILE", None)
    iss = open(os.path.join(HERE, "installer", "PolyPDF.iss"), encoding="utf-8").read()
    icons = iss[iss.index("\n[Icons]"):iss.index("\n[Registry]")]      # 줄 머리의 섹션(주석 속 '[Icons]' 글자가 아니라)
    app_lines = [ln for ln in icons.splitlines() if "{#MyAppExe}" in ln and not ln.lstrip().startswith(";")]
    chk(app_lines and all('AppUserModelID: "%s"' % getattr(main, "APP_USER_MODEL_ID", "?") in ln for ln in app_lines),
        "C 앱 바로가기(시작 메뉴·바탕 화면)에 같은 ID", str(app_lines))
    src = inspect.getsource(main.main)
    i_set, i_app = src.find("_set_app_user_model_id()"), src.find("QApplication(sys.argv)")
    chk(0 <= i_set < i_app, "D 창을 만들기 전에(QApplication 앞) 정한다")
    chk(os.path.exists(os.path.join(HERE, "resources", "icon.png")), "E 창 아이콘 원천 resources/icon.png 가 있다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
