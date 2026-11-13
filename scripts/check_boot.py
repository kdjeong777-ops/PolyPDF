# -*- coding: utf-8 -*-
"""전체 검사의 시작 스크립트 — `release_test.py checks` 가 검사 하나를 이것으로 감싸 돌린다 (261113-7, 릴리스 SOT §4.1, 검사 작성 SOT §14.7).

    python -I scripts/check_boot.py test_x.py

검사 파일은 고치지 않는다. 하는 일 둘:
1. **판정 뒤 종료 멈춤 막기** — `os._exit` 를 `TerminateProcess` 로 바꾼다. `os._exit` 의 `ExitProcess` 는 DLL detach 에서
   가끔 교착해(배경 스레드·QtMultimedia 등) 'ALL PASS' 를 찍고도 600초까지 끝나지 않았다(지난 시간 초과 27건 중 21건, 261112-23).
   `TerminateProcess` 는 detach 를 돌리지 않는다. 종료 코드는 그대로다(판정은 종료 코드).
2. **검사마다 따로 쓰는 설정 폴더** — Qt 시험 모드를 켜고 앱 이름을 `polypdf_chk_<검사>_<pid>` 로 먼저 정한다.
   이름을 정하지 않는 검사(56개)는 모두 기본 이름(`python`)의 같은 폴더를 써서, 병렬로 돌리면 설정·색인이 겹친다.
   검사가 스스로 이름·시험 모드를 정하면 그것이 이긴다(뒤에 부르므로). 폴더 지우기는 실행기가 한다(`CHK_PREFIX`).
"""
import ctypes
import os
import runpy
import sys

CHK_PREFIX = "polypdf_chk_"


def _hard_exit(code=0):
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p        # ★ 없으면 의사 핸들 (HANDLE)-1 이 잘려 조용히 실패(검사 작성 SOT §14.7)
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), int(code) & 0xFFFFFFFF)
    except Exception:
        pass
    _orig_exit(code)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")         # 검사 작성 SOT §14.7.2-21 — 한글·'—' 를 찍는 scripts
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("사용: check_boot.py <검사 파일> [인수…]")
        return 2
    test = os.path.abspath(sys.argv[1])
    sys.argv = [test] + sys.argv[2:]
    sys.path[0] = os.path.dirname(test)                     # 검사를 직접 돌린 것과 같은 sys.path[0]
    try:
        from PyQt6.QtCore import QCoreApplication, QStandardPaths
        QStandardPaths.setTestModeEnabled(True)
        QCoreApplication.setApplicationName("%s%s_%d" % (CHK_PREFIX, os.path.splitext(os.path.basename(test))[0], os.getpid()))
    except Exception:
        pass
    runpy.run_path(test, run_name="__main__")
    return 0


_orig_exit = os._exit
if sys.platform == "win32":
    os._exit = _hard_exit

if __name__ == "__main__":
    sys.exit(main())
