# -*- coding: utf-8 -*-
"""261108-32: 환경설정 '읽기 음성' 의 [구성요소 설치] — 구성요소 창이 환경설정 **위에** 뜬다 (디자인 SOT §2.14 '모달 위 창').

사용자 보고: "환경설정에서 자연음성 구성요소 설치 버튼을 누르면 '구성요소 설치' 창이 뜨고, 바로 환경설정창이 앞으로
나와서 '구성요소 설치'창이 뒤로 숨겨지게되고 안보여."

원인: 구성요소 창의 부모가 메인 창이었다. 환경설정은 모달(`exec`)이라 메인 창에 딸린 창은 막히고, 모달인 환경설정이
다시 앞으로 왔다. 실제 이벤트로 본다 — 창을 띄워 환경설정을 열고 단추를 마우스로 누른다.

  A. 구성요소 창의 부모 = 환경설정, 보이고 활성 창이다(맨 위)
  B. 설치가 끝나면 '읽기 음성' 쪽 상태 글이 곧바로 '설치됨 ✓'
  C. 환경설정을 닫으면 구성요소 창은 메인 창으로 옮겨 달리고 계속 보인다
  D. 메뉴에서 여는 종전 길은 그대로 메인 창이 부모
수정 전 코드로 A(부모)·B 가 실패한다. 오프스크린은 창 겹침 순서를 흉내 내지 못해 '활성' 은 옛 코드에서도 참이다 —
막는 것은 '부모 = 환경설정' 줄이다(모달 위에 뜨려면 그 모달이 부모여야 한다).
"""
import os, sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QPushButton, QLabel
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer, Qt
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_tts_voice_comp_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사", dialogs=False, watch_ms=60000)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from viewer.app import MainWindow
from viewer.study import tts_engine
from viewer import update_controller as uc

# 구성요소 상태 확인은 배경에서 tesseract 등을 실행한다 — 검사는 결과만 빨리
uc.ComponentStatusWorker.run = lambda self: (self.done.emit({}), self.finished.emit())

mw = MainWindow(); mw.resize(1400, 900); mw.show(); QTest.qWait(300)
seen = {}


def inside():
    """환경설정(모달) 안에서 — 단추를 실제로 누르고 창 상태를 적는다."""
    sd = QApplication.activeModalWidget()
    seen["sd"] = sd
    btn = sd.findChild(QPushButton, "btnTtsComponents") if sd is not None else None
    if btn is None and sd is not None:             # 이름이 없던 판(수정 전)도 같은 단추를 글자로 찾아 누른다
        btn = next((b for b in sd.findChildren(QPushButton) if b.text() == "구성요소 설치"), None)
    seen["btn"] = btn is not None
    if btn is None:
        if sd is not None:
            sd.reject()
        return
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    QTest.qWait(400)
    cd = getattr(mw, "_comp_dlg", None)
    seen["cd"] = cd
    seen["parent_is_sd"] = cd is not None and cd.parent() is sd
    seen["visible"] = cd is not None and cd.isVisible()
    seen["active"] = QApplication.activeWindow() is cd
    # B — 설치가 끝났다고 알린다(모델을 실제로 받지 않는다)
    lbl = sd.findChild(QLabel, "lblTtsNeuralState")
    seen["lbl_before"] = lbl.text() if lbl else ""
    tts_engine._ready = None
    orig = tts_engine.neural_ready
    tts_engine.neural_ready = lambda: True
    try:
        mw._comp_done("voice", True, "", False)
        QTest.qWait(50)
        seen["lbl_after"] = lbl.text() if lbl else ""
    finally:
        tts_engine.neural_ready = orig
    sd.reject()


tts_engine._ready = False
QTimer.singleShot(500, inside)
mw.open_settings(page="voice")
QTest.qWait(300)

chk(seen.get("btn"), "준비 — 환경설정 '읽기 음성' 에 [구성요소 설치] 단추")
chk(seen.get("parent_is_sd"), "A 구성요소 창의 부모 = 환경설정(모달 위 창)",
    "parent=%s" % (type(seen["cd"].parent()).__name__ if seen.get("cd") is not None else None))
chk(seen.get("visible") and seen.get("active"), "A 구성요소 창이 보이고 활성(맨 위)",
    "visible=%s active=%s" % (seen.get("visible"), seen.get("active")))
chk("미설치" in seen.get("lbl_before", "") and "설치됨" in seen.get("lbl_after", ""),
    "B 설치가 끝나면 상태 글이 곧바로 '설치됨 ✓'", "%r → %r" % (seen.get("lbl_before"), seen.get("lbl_after")))
cd = getattr(mw, "_comp_dlg", None)
alive = True
try:
    par = cd.parent() if cd is not None else None
    vis = cd.isVisible() if cd is not None else False
except RuntimeError:
    alive, par, vis = False, None, False
chk(alive and par is mw and vis, "C 환경설정을 닫으면 구성요소 창은 메인 창으로 옮겨 달리고 계속 보인다",
    "alive=%s parent=%s visible=%s" % (alive, type(par).__name__ if par is not None else None, vis))
if alive and cd is not None:
    cd.close()
mw._comp_dlg = None
mw._open_components_installer(False)             # 메뉴 QAction.triggered(bool) 길
QTest.qWait(200)
cd2 = getattr(mw, "_comp_dlg", None)
chk(cd2 is not None and cd2.parent() is mw and cd2.isVisible(), "D 메뉴에서 열면 종전처럼 메인 창이 부모")
if cd2 is not None:
    # E(261108-32 덧붙임, 사용자 보고 '중단된 채 100%'): 받는 중 창을 다시 열면 지금 단계 — 막대·단계 글·'중단',
    #   끝나면(일꾼 없음) 디스크 판정으로 '다운로드'/'재설치' 와 막대 숨김
    class _W:
        key = "voice"
        jid = "components:voice"

        def request_cancel(self):
            pass
    mw._comp_worker = _W()
    mw._comp_last = (40, "압축 푸는 중… 40%")
    mw._comp_status({"ffmpeg": True, "tess": True, "voice": False})
    st, b = cd2._rows["voice"]
    chk(b.text() == "중단" and cd2._bar.isVisible() and cd2._bar.format() == "압축 푸는 중… 40%",
        "E 받는 중 다시 열면 '중단'·막대·단계 글", "%s %s %r" % (b.text(), cd2._bar.isVisible(), cd2._bar.format()))
    mw._comp_worker = None
    mw._comp_status({"ffmpeg": True, "tess": True, "voice": False})
    chk(b.text() == "다운로드" and not cd2._bar.isVisible(), "E 일이 없으면 디스크 판정대로 '다운로드'·막대 숨김", b.text())
    mw._comp_status({"ffmpeg": True, "tess": True, "voice": True})
    chk(b.text() == "재설치" and "설치됨" in st.text(), "E 설치돼 있으면 '설치됨 ✓ [재설치]'", b.text())
    cd2.close()
chk(not [s for s in guard.seen if s[1] != "exec"], "뜬 확인 창 없음", guard.report())
mw.close()
print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
