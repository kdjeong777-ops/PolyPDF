# -*- coding: utf-8 -*-
"""261113-2(릴리스 SOT §14.5 U25): 여러 창을 띄운 채 한 창에서 '업데이트하고 종료' — 다른 창은 업데이트 창 없이 함께 닫힌다.

사용자 보고
  "프로그램이 여러개 띄워져 있을 경우 프로그램을 종료시 첫번째 프로그램이 업그레이드한다고 하고 종료한다고 하여
   그렇게 처리한다고 할 때, 다른 프로그램이 종료가 안되. … 업그레이드 한다는 창이 떠있고, 이를 취소하며, 수동으로 종료하여야 해."

다른 창은 **진짜 다른 프로세스**(실제 MainWindow·실제 instance_link 소켓)로 띄운다. 오프스크린이라 Win32 창이 없으므로
`updater.other_windows`·`request_close` 만 바꿔 끼운다 — 닫기 요청은 그 프로세스가 `mw.close()`(실제 closeEvent)로 받는다.
실제 설치본 실행·다운로드는 하지 않는다(`updater.apply_setup`·`apply_update` 가짜).

A. 업데이트하는 창의 실제 closeEvent('업그레이드 후 종료') → 다른 창은 **업데이트 창을 띄우지 않고** 닫힌다, 저장 확인은 평소대로 거친다
B. 업데이트하는 창은 '강제로 닫을까' 를 묻지 않고 설치본을 **한 번** 실행한다
C. 받는 쪽 — `update_quit` 을 받은 뒤 120초 안의 닫기만 건너뛴다(지나면 다시 묻는다), 알림 전에는 묻는다
D. zip 길(휴대용)도 도우미를 띄우기 **전에** 다른 창에 알린다
"""
import os, sys, json, time, subprocess, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["POLYPDF_PROFILE"] = "test"
faulthandler.dump_traceback_later(300, exit=True)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
app.setApplicationName("PolyPDF-test-updmulti")     # 두 프로세스가 같은 등록 폴더를 보게
import modal_guard
modal_guard.install(label=lambda: "여러 창 업데이트", echo=False)   # 마스터 §14.7.2 의 6 — 아래 개별 바꿔 끼우기가 우선

FAKE_INFO = {"version": "99.0.0", "tag": "v99.0.0", "asset_url": "https://github.com/x/y/z.zip",
             "setup_url": "https://github.com/x/y/s.exe", "html_url": ""}


def spin(n=10, ms=30):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


# ─────────────────────────── 다른 창(피어) 프로세스 ───────────────────────────
if len(sys.argv) >= 3 and sys.argv[1] == "--peer":
    state = Path(sys.argv[2])
    st = {"ready": False, "update_dialog": 0, "confirm_edit": 0, "close_result": None}
    from viewer.widgets import update_dialog as ud

    def fake_exec(self):                       # 사용자가 본 그 창 — 보고처럼 '취소' 를 누른다
        st["update_dialog"] += 1
        self.choice = "cancel"
        return 0
    ud.UpdateDialog.exec = fake_exec
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1000, 700); mw.show(); app.processEvents()
    mw._pending_update = dict(FAKE_INFO)       # 이 창도 시작 때 새 버전을 알았다
    real_confirm = mw._confirm_close_edit

    def confirm_edit():
        st["confirm_edit"] += 1                # 저장 확인 길을 거쳤나(편집 없음 → 평소대로 True)
        return real_confirm()
    mw._confirm_close_edit = confirm_edit

    def dump():
        st["ready"] = mw._instance_link is not None
        state.write_text(json.dumps(st), encoding="utf-8")

    def poll():
        dump()
        close_req = state.parent / "CLOSE"
        if close_req.exists():                 # = WM_CLOSE(updater.request_close 의 대역)
            close_req.unlink(missing_ok=True)
            st["close_result"] = bool(mw.close())
            dump()
            if st["close_result"]:
                os._exit(0)
        if (state.parent / "STOP").exists():
            os._exit(0)
    t = QTimer(); t.timeout.connect(poll); t.start(100)
    QTimer.singleShot(150_000, lambda: os._exit(0))
    app.exec()
    os._exit(0)

# ─────────────────────────── 검사 본체 ───────────────────────────
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_updmulti_"))
peer = None
try:
    state = root / "peer.json"
    peer = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--peer", str(state)],
                            cwd=os.path.dirname(os.path.abspath(__file__)))

    def peer_state():
        try:
            return json.loads(state.read_text(encoding="utf-8"))
        except Exception:
            return {}
    for _ in range(600):
        time.sleep(0.1)
        if peer_state().get("ready"):
            break
    chk(peer_state().get("ready"), "준비 — 다른 창(다른 프로세스)이 떴고 창 간 통신을 열었다", str(peer_state()))

    asked = []
    QMessageBox.warning = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""),
                                                        QMessageBox.StandardButton.No)[1])
    QMessageBox.information = staticmethod(lambda *a, **k: asked.append(a[2] if len(a) > 2 else ""))
    from viewer import updater
    from viewer.widgets import update_dialog as ud
    launched = []
    updater.other_windows = lambda exe="": ({peer.pid: [0]} if peer.poll() is None else {})
    updater.request_close = lambda wins: (root / "CLOSE").write_text("1") if wins else None
    updater.apply_setup = lambda path, sha, lang="": (launched.append(path), True)[1]

    def main_exec(self):                       # 업데이트하는 창의 사용자 — '업그레이드 후 종료'
        self.choice = "update"
        return 0
    ud.UpdateDialog.exec = main_exec

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1000, 700); mw.show(); spin(5)
    setup = root / "PolyPDF-update-setup.exe"
    setup.write_bytes(b"fake")
    mw._pending_update = dict(FAKE_INFO)
    mw._pending_zip = str(setup)
    mw._update_kind_cache = (FAKE_INFO["version"], "setup")
    mw._ensure_update_zip = lambda info: True  # 받기는 U13 검사 몫 — 이미 받아 두었다
    mw._OTHER_WIN_WAIT_S = 12.0

    # ── A·B. 실제 closeEvent ──
    t0 = time.monotonic()
    closed = mw.close()
    dt = time.monotonic() - t0
    for _ in range(50):
        if peer.poll() is not None:
            break
        time.sleep(0.1)
    ps = peer_state()
    chk(ps.get("update_dialog") == 0, "A 다른 창은 업데이트 창을 **띄우지 않는다**", str(ps))
    chk(ps.get("confirm_edit", 0) >= 1, "A 다른 창도 저장 확인 길은 평소대로 거친다", str(ps))
    chk(ps.get("close_result") is True and peer.poll() is not None, "A 다른 창이 함께 닫힌다(프로세스 끝)", str(ps))
    chk(closed and launched == [str(setup)], "B 이 창은 닫히고 설치본을 한 번 실행한다", str(launched))
    chk(not asked, "B '남은 창을 강제로 닫을까' 를 묻지 않는다", str(asked))
    chk(dt < 10.0, "B 다른 창을 기다리는 시간이 짧다(60초 기다림까지 가지 않음)", "%.1fs" % dt)

    # ── C. 받는 쪽 판단 ──
    mw2 = MainWindow(); mw2.show(); spin(3)
    chk(not mw2._peer_updating(), "C 알림 전에는 업데이트 창을 건너뛰지 않는다")
    res = mw2._on_instance_request("update_quit", None)
    chk(res.get("ok") and mw2._peer_updating(), "C update_quit 을 받으면 이 창의 닫기는 업데이트 창을 건너뛴다", str(res))
    mw2._peer_update_at = time.monotonic() - mw2._PEER_UPDATE_HOLD_S - 1
    chk(not mw2._peer_updating(), "C 120초가 지나면(업데이트 취소 등) 다시 평소대로 묻는다")

    # ── D. zip 길도 도우미보다 먼저 알린다 ──
    order = []

    class FakeLink:
        def broadcast(self, msg, timeout=0):
            order.append(("broadcast", msg.get("op"), timeout))
            return 0

        def close(self):
            pass
    real_link = mw2._instance_link
    mw2._instance_link = FakeLink()
    updater.apply_update = lambda **k: (order.append(("apply_update",)), True)[1]
    updater.fetch_expected_sha256 = lambda info: ""
    updater.fetch_manifest = lambda info: ""
    mw2._pending_update = dict(FAKE_INFO)
    mw2._pending_zip = None
    mw2._update_kind_cache = (FAKE_INFO["version"], "zip")
    ok = mw2._begin_upgrade()
    chk(ok and [o[0] for o in order] == ["broadcast", "apply_update"] and order[0][1] == "update_quit",
        "D zip 길 — 도우미를 띄우기 전에 다른 창에 update_quit 을 알린다", str(order))
    chk(order and order[0][2] <= 1000, "D 창마다 응답 기다림은 1초 안(응답성 SOT)", str(order))
    mw2._instance_link = real_link
    mw2._updating = True
    mw2.close()
finally:
    try:
        (root / "STOP").write_text("1")
    except Exception:
        pass
    if peer is not None:
        try:
            peer.wait(10)
        except Exception:
            peer.kill()
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
