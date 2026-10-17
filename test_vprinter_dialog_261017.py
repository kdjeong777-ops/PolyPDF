# -*- coding: utf-8 -*-
"""261017-19: 가상 프린터 창·안내 결함 셋(가상 프린터 SOT §4.2·§4.6·§7, SOT 점검).

A. 창의 배경 일(상태 읽기·UAC 대기)은 **앱의 목록**에 둔다 — 창 목록이면 대기 중 [닫기] 뒤 창과 함께 지워져 도는 스레드가 사라졌다
B. 휴대용 판은 [설치] 를 끄고 까닭을 보인다 — 예약 작업을 만들 수 없어 '설치됨' 인데 인쇄가 열리지 않았다
C. Ghostscript 가 없을 때 '수리' 가 아니라 '다시 설치' 를 권한다 — 앱 폴더 안이라 수리(설치 도구)로 되살아나지 않는다
"""
import os, sys, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer.widgets import vprinter_dialog as vd

# A — 배경 일은 넘겨받은 목록에
vd.read_state = lambda: {"support": "ok"}               # 스풀러를 보지 않는다
host_keep = []
dlg = vd.VPrinterDialog(None, {}, keep=host_keep)
chk(dlg._keep is host_keep, "A1 창이 앱의 목록을 쓴다(창 목록이 아니다)")
chk(len(host_keep) > 0, "A2 상태 읽기 스레드가 앱의 목록에 들어 있다", str(host_keep))
for _ in range(50):
    app.processEvents()

# B — 휴대용 판
from viewer import settings_store
_old = settings_store.PORTABLE
settings_store.PORTABLE = True
try:
    dlg._show_state({"support": "ok", "monitor": False, "dll": False, "port": False, "driver": False, "printer": False})
    chk(not dlg.btn_install.isEnabled() and "휴대용" in dlg.lbl_state.text(), "B 휴대용 판은 [설치] 를 끄고 까닭을 보인다", dlg.lbl_state.text())
finally:
    settings_store.PORTABLE = _old
dlg._show_state({"support": "ok", "monitor": False, "dll": False, "port": False, "driver": False, "printer": False})
chk(dlg.btn_install.isEnabled(), "B2 설치판에서는 [설치] 가 켜진다")
dlg.deleteLater()

# C — Ghostscript 없음 안내
src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer", "vprinter_recv.py"), encoding="utf-8").read()
chk("'수리' 하세요" not in src and src.count("PolyPDF 를 다시 설치하세요") == 2, "C Ghostscript 가 없으면 '다시 설치' 를 권한다(수리 아님)")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
