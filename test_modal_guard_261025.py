# -*- coding: utf-8 -*-
"""261025-13(마스터 §14.7.2 의 6): 오프스크린 모달 자동 닫기 `modal_guard` — 장치가 없으면 멈추고, 있으면 닫고 적는다.

261025 오래 켜 두기 시험이 책갈피창 '트리 ↔ 단일' 안내 창(`BookmarkTree._toggle_tree_view` 의 QMessageBox.information)에서
77분 멈췄다. 같은 창을 실제로 띄워 본다(자식 프로세스 — 멈춰도 이 검사는 끝난다).

A. 장치 없이: 그 안내 창에서 멈춘다(시간 초과) — 장치가 막는 것이 실제로 있음을 보인다(수정 전 상태)
B. 장치를 켜면: 안내 창·`QDialog.exec`·`QMessageBox(...).exec` 가 곧바로 돌아오고 셋 다 기록된다
C. 감시 타이머: `open()` + 이벤트 루프로 띄운 모달(정적 함수·exec 를 비켜 간 것)도 닫고 기록한다
D. 질문의 답은 안전한 쪽(`No`), 파일 창은 빈 값
"""
import json, os, subprocess, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if len(sys.argv) > 1 and sys.argv[1] in ("child-guard", "child-noguard"):
    import faulthandler
    faulthandler.dump_traceback_later(60, exit=True)
    from PyQt6.QtCore import QStandardPaths, QEventLoop, QTimer
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog
    app = QApplication(sys.argv[:1])
    g = None
    if sys.argv[1] == "child-guard":
        import modal_guard
        g = modal_guard.install(label=lambda: "검사", watch_ms=300, echo=False)
    from viewer.widgets.bookmark_tree import BookmarkTree
    bt = BookmarkTree()
    bt._mode = "single"                       # 파일 모드 — 오래 켜 두기 시험이 멈춘 그 상태
    bt._toggle_tree_view()                    # 장치 없으면 여기서 영원히 멈춘다
    res = {"toggled": True}
    res["dialog_exec"] = QDialog().exec()
    res["msgbox_exec"] = QMessageBox(QMessageBox.Icon.Warning, "제목", "본문").exec()
    res["question"] = int(QMessageBox.question(None, "질문", "지울까요?").value)
    res["file"] = QFileDialog.getOpenFileName(None, "열기")[0]
    d = QDialog(); d.setWindowTitle("open 모달"); d.setModal(True); d.open()
    loop = QEventLoop(); d.finished.connect(loop.quit)
    QTimer.singleShot(8000, loop.quit)        # 감시 타이머가 못 닫으면 8초 뒤 그냥 빠진다(실패로 보인다)
    loop.exec()
    res["open_closed"] = not d.isVisible()
    res["seen"] = [list(x) for x in (g.seen if g else [])]
    print("RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    os._exit(0)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def run(mode, timeout):
    return subprocess.run([sys.executable, os.path.abspath(__file__), mode], capture_output=True, timeout=timeout,
                          cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))


try:
    run("child-noguard", 15)
    hung = False
except subprocess.TimeoutExpired:
    hung = True
chk(hung, "A 장치 없이는 '트리 ↔ 단일' 안내 창에서 멈춘다(15초 시간 초과)")

r = run("child-guard", 60)
out = r.stdout.decode("utf-8", "replace")
line = next((l for l in out.splitlines() if l.startswith("RESULT ")), "")
res = json.loads(line[7:]) if line else {}
kinds = [k for _l, k, _t in res.get("seen", [])]
chk(r.returncode == 0 and res.get("toggled"), "B 장치를 켜면 안내 창에서 멈추지 않는다", out[-300:] + r.stderr.decode("utf-8", "replace")[-300:])
chk("information" in kinds and any("단일/트리" in t for _l, _k, t in res.get("seen", [])), "B 안내 창을 글과 함께 기록한다", str(res.get("seen")))
chk(res.get("dialog_exec") == 0 and res.get("msgbox_exec") == 0 and "exec:QDialog" in kinds and "exec:QMessageBox" in kinds,
    "B exec() 창은 취소(0)로 돌아오고 기록된다", str((res.get("dialog_exec"), res.get("msgbox_exec"), kinds)))
chk(res.get("open_closed") and any(k.startswith("watchdog:") for k in kinds), "C 감시 타이머가 open() 모달을 닫고 기록한다", str(kinds))
chk(res.get("question") == 0x00010000 and res.get("file") == "", "D 질문은 No, 파일 창은 빈 값", str((res.get("question"), res.get("file"))))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
