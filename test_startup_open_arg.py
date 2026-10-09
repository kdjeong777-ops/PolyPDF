# -*- coding: utf-8 -*-
"""261009-14: PDF 를 인자로 열면 지난 세션을 복원하지 않는다 — 응답성 SOT §4.2 · §12.

설치본 시험: 탐색기 '연결 프로그램' 처럼 PDF 하나를 인자로 주었더니, 앱이 **지난 세션의 폴더(다운로드)를 먼저**
메인 스레드에서 훑느라 4.4초 선 뒤에야 요청한 파일을 열었다. 복원(`_restore_session_deferred`)이 창을 만들 때
줄을 서서 `main.py` 의 인자 열기보다 먼저 돌았기 때문에 '이미 연 것이 있으면 덮지 않는다' 가드가 작동하지 않았다.

A. main.py 와 같은 차례(창 생성 → 인자 표시 → 이벤트 루프)면 지난 폴더를 열지 않는다
B. 인자가 없으면 종전대로 지난 폴더를 연다(관계없는 동작은 그대로)
C. main.py 가 창을 만든 뒤·이벤트 루프 전에 표시를 단다
"""
import os, sys, ast, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_startup_arg_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_sarg_"))
try:
    from viewer.app import MainWindow

    def run(has_args: bool):
        mw = MainWindow(); mw._skip_save_on_close = True
        opened = []
        mw.open_folder = lambda p, *a, **k: opened.append(str(p))
        mw._prefs["startup_mode"] = "last"
        mw._session_data = {"last_open": {"kind": "folder", "path": str(tmp)}}
        if has_args:
            mw._startup_has_args = True            # main.py 가 하는 것
        t0 = time.time()
        while time.time() - t0 < 0.5:
            app.processEvents(); time.sleep(0.01)
        mw.close()
        return opened

    chk(run(True) == [], "A PDF 인자가 있으면 지난 폴더를 복원하지 않는다")
    chk(run(False) == [str(tmp)], "B 인자가 없으면 종전대로 지난 폴더를 연다")

    # ── C ──
    src = (Path(HERE) / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = {"mw": None, "mark": None, "exec": None}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "MainWindow":
            lines["mw"] = node.lineno
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "_startup_has_args" for t in node.targets):
            lines["mark"] = node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "exec":
            lines["exec"] = node.lineno
    chk(None not in lines.values() and lines["mw"] < lines["mark"] < lines["exec"],
        "C main.py 가 창을 만든 뒤·이벤트 루프 전에 인자 표시를 단다", str(lines))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
