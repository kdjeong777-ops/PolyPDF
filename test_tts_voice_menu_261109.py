# -*- coding: utf-8 -*-
"""261108-33: 성우 — ▾ 메뉴가 엔진에 맞게·환경설정과 값 하나·Windows 성우 쓰지 않음·자연 음성 이름·미리 듣기 (영상·음성 SOT §1.10).

사용자 보고·지시: "성우 설정이 기존에서 변화가 없었어 … 본문 읽은데서는 성우설정의 변경이 없었고, 환경설정에는 자연어엔진
선택시 성우1 등으로 되어 있었어", "기존 기계음 성우를 환경설정에서 적용해제(삭제)할 수 있도록해", "자연음 성우가 성우1, 2 등으로
되어 있는데, 성우명을 붙일 수 있게해", "환경설정에서 성우들이 샘플텍스트를 읽어서 들어보는 기능을 추가해".

원인(재현): ▾ 메뉴 '성우' 는 처음 열 때 SAPI 목록을 한 번 채우고 끝이었다 — 자연 음성을 쓰는 동안에도 Windows 성우만 보였고,
자연 음성 목소리는 환경설정에만 있었다.

  A. 자연 음성이면 ▾ '성우' = 목소리 1~10(사용자 이름), 고르면 설정 sid — 환경설정 '목소리' 도 같은 값
  B. SAPI 면 ▾ '성우' = 숨기지 않은 Windows 성우, 숨긴 성우는 언어별 기본 음성으로도 쓰지 않는다(다 숨기면 하나로 물러섬)
  C. 이름을 바꾸면 메뉴·환경설정 고르기에 반영
  D. 미리 듣기 — 그 목소리·지금 음질로 엔진을 부른다, 다시 누르면 멈춘다, 다른 성우를 누르면 앞 것을 멈춘다, 합성은 배경
  E. 설정 값이 허용목록을 거쳐 남는다
수정 전 코드로 A·B·C·D 가 실패한다. 소리는 내지 않는다(가짜 재생기·가짜 SAPI).
"""
import os, sys, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QThread, Qt
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_tts_voice_menu_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from viewer.app import MainWindow
from viewer.study import tts_engine, neural_tts
from viewer.study import tts as tts_mod


class _Tok:
    def __init__(self, name, lang):
        self.name, self.lang = name, lang

    def GetAttribute(self, k):
        return self.name if k == "Name" else self.lang


class FakeSapi(tts_mod.TTS):
    """진짜 TTS 의 목록·숨김·고르기 길을 그대로 쓰고, 소리만 적는다."""
    def __init__(self):
        super().__init__()
        self._ok = True
        self._voice = object()
        self._by_name = {"Microsoft Heami Desktop": _Tok("Microsoft Heami Desktop", "412"),
                         "Microsoft Zira Desktop": _Tok("Microsoft Zira Desktop", "409"),
                         "Microsoft David Desktop": _Tok("Microsoft David Desktop", "409")}
        pk = getattr(tts_mod, "pick_tokens", None)     # 수정 전 코드에도 돌아가게(그때는 숨김이 없다)
        self._tok = pk(self._by_name, ()) if pk else {"kor": self._by_name["Microsoft Heami Desktop"],
                                                      "eng": self._by_name["Microsoft Zira Desktop"]}
        self.said = []

    def _ensure(self):
        pass

    def speak(self, text, lang="eng", *, queue=False):
        tok = self._select(lang)
        self.said.append((tok.name if tok else None, text))
        self._busy = True
        return True

    def is_speaking(self):
        return bool(getattr(self, "_busy", False))

    def stop(self):
        self._busy = False


class FakePlayer:
    def __init__(self):
        self.fed = []

    def feed(self, pcm):
        self.fed.append(pcm)

    def busy(self):
        return True                       # 재생 중인 것으로 — 멈춤을 보려고

    def stop(self):
        self.fed.append("STOP")

    def played_s(self):
        return 0.0

    def written_s(self):
        return 0.0


class FakeSynth:
    calls = []

    def __init__(self):
        self.sample_rate = 44100

    def load(self):
        FakeSynth.calls.append(("load", None, None, QThread.currentThread() is app.thread()))

    def unload(self):
        pass

    def generate(self, text, lang="ko", sid=0, steps=4, speed=1.0):
        FakeSynth.calls.append(("gen", sid, steps, QThread.currentThread() is app.thread()))
        return b"\x01\x00" * 4410


mw = MainWindow(); mw.resize(1400, 900); mw.show(); QTest.qWait(300)
fs = FakeSapi()
mw._tts = fs                                  # _study_get_tts 가 이것을 돌려준다(숨김 적용 길 그대로)
nr = neural_tts.NeuralReader(mw, synth_factory=FakeSynth, player_factory=FakePlayer)
nr.available = lambda: True
mw._neural_reader = nr
tts_engine._ready = True
mw._prefs["tts_voice"] = {"engine": "neural", "sid": 0, "quality": "fast",
                          "names": ["민지", "", "", "", "", "", "", "", "", ""]}


def voice_menu():
    menu = mw.btn_read.menu()
    menu.aboutToShow.emit()
    for a in menu.actions():
        if a.menu() is not None and a.text() == "성우":
            return a.menu()
    return None


print("=== A. 자연 음성이면 ▾ '성우' = 목소리 1~10 ===")
vm = voice_menu()
labels = [a.text() for a in vm.actions()] if vm is not None else []
chk(labels[:3] == ["민지", "목소리 2", "목소리 3"] and len(labels) == 10, "A 목록 = 자연 음성 목소리(이름 반영)", str(labels[:4]))
if vm is not None and len(vm.actions()) > 3:
    vm.actions()[3].trigger()
chk(tts_engine.cfg_of(mw)["sid"] == 3 and nr.sid == 3, "A 메뉴에서 고르면 설정 sid·읽개 목소리가 바뀐다",
    "sid=%s reader=%s" % (tts_engine.cfg_of(mw)["sid"], nr.sid))
from viewer.widgets.settings_dialog import SettingsDialog
d = SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="voice")
chk(d.cmb_tts_voice.currentData() == 3 and d.cmb_tts_voice.currentText() == "목소리 4",
    "A 환경설정 '목소리' 도 같은 값", d.cmb_tts_voice.currentText())

print()
print("=== C. 이름을 바꾸면 반영 ===")
d.tbl_tts_names.cellWidget(3, 0).setText("수아")
chk(d.cmb_tts_voice.currentText() == "수아", "C 환경설정 '목소리' 고르기에 곧바로", d.cmb_tts_voice.currentText())
rp = d.result_prefs()["tts_voice"]
chk(rp["names"][3] == "수아" and rp["names"][0] == "민지", "C 결과에 이름", str(rp["names"][:4]))

print()
print("=== D. 미리 듣기 ===")
FakeSynth.calls = []
d.cmb_tts_quality.setCurrentIndex(d.cmb_tts_quality.findData("high"))
b5 = d.findChild(QPushButton, "btnPreviewNeural5")
chk(b5 is not None and b5.isEnabled(), "D 자연 음성 줄마다 [들어 보기](설치돼 있으면 켜짐)")
if b5 is not None:
    QTest.mouseClick(b5, Qt.MouseButton.LeftButton)
    t0 = time.time()
    while time.time() - t0 < 3 and not any(c[0] == "gen" for c in FakeSynth.calls):
        QTest.qWait(20)
    gens = [c for c in FakeSynth.calls if c[0] == "gen"]
    chk(gens and gens[0][1] == 5 and gens[0][2] == neural_tts.STEPS["high"],
        "D 그 목소리(sid 5)·지금 음질(고음질 steps 8)로 합성", str(gens[:1]))
    chk(FakeSynth.calls and not any(c[3] for c in FakeSynth.calls), "D 싣기·합성은 배경 스레드(메인 0)", str(FakeSynth.calls[:3]))
    chk(d.tts_preview.playing == ("neural", 5) and bool(b5.property("previewPlaying")), "D 재생 중 표시(■)")
    nst = len(nr._player.fed)
    QTest.mouseClick(b5, Qt.MouseButton.LeftButton)
    chk(d.tts_preview.playing is None and "STOP" in nr._player.fed[nst:], "D 다시 누르면 멈춘다")
    chk(nr.sid == 3, "D 미리 듣기는 읽기 목소리(sid 3)를 바꾸지 않는다", str(nr.sid))
    QTest.mouseClick(b5, Qt.MouseButton.LeftButton)
    QTest.qWait(100)
    ws = [b for b in d.findChildren(QPushButton) if b.toolTip() == "들어 보기" and b.objectName() == ""]
    if ws:
        QTest.mouseClick(ws[0], Qt.MouseButton.LeftButton)
        chk(d.tts_preview.playing and d.tts_preview.playing[0] == "sapi" and "STOP" in nr._player.fed,
            "D 다른 성우(Windows)를 누르면 앞 소리를 멈추고 그 성우로", str(d.tts_preview.playing))
        chk(fs.said and fs.said[-1][0] == "Microsoft Heami Desktop" and "안녕하세요" in fs.said[-1][1]
            and "Hello" not in fs.said[-1][1], "D Windows 성우는 그 언어 줄만(Heami=한국어)", str(fs.said[-1:]))
    d.reject()
    chk(d.tts_preview.playing is None, "D 창을 닫으면 멈춘다")

print()
print("=== B. SAPI 면 숨기지 않은 Windows 성우 ===")
mw._prefs["tts_voice"] = dict(mw._prefs["tts_voice"], engine="sapi",
                              hidden_sapi=["Microsoft Zira Desktop"])
vm = voice_menu()
labels = [a.text() for a in vm.actions()] if vm is not None else []
chk("Microsoft Zira Desktop" not in labels and "Microsoft David Desktop" in labels and labels[0] == "자동(언어별)",
    "B ▾ '성우' = 숨기지 않은 Windows 성우", str(labels))
t = mw._study_get_tts()
chk(t._select("eng").name == "Microsoft David Desktop", "B 숨긴 성우(Zira)는 영어 기본 음성으로도 쓰지 않는다", t._select("eng").name)
mw._prefs["tts_voice"]["hidden_sapi"] = ["Microsoft Zira Desktop", "Microsoft David Desktop"]
t = mw._study_get_tts()
chk(t._select("eng") is not None, "B 한 언어를 다 숨기면 하나로 물러선다(소리가 안 나지 않게)")
d2 = SettingsDialog(dict(mw._prefs), parent=mw, host=mw, page="voice")
rows = [d2.tbl_tts_sapi.cellWidget(i, 0) for i in range(d2.tbl_tts_sapi.rowCount())]
chk({c.text(): c.isChecked() for c in rows} == {"Microsoft Heami Desktop": True, "Microsoft Zira Desktop": False,
                                                 "Microsoft David Desktop": False},
    "B 환경설정 표 = 쓰기 체크(숨긴 것은 꺼짐)")
rows[0].setChecked(False)
chk(sorted(d2.result_prefs()["tts_voice"]["hidden_sapi"]) ==
    ["Microsoft David Desktop", "Microsoft Heami Desktop", "Microsoft Zira Desktop"], "B 끈 성우가 결과로")
d2.reject()

print()
print("=== E. 허용목록 ===")
mw._apply_prefs(dict(mw._prefs, tts_voice={"engine": "neural", "sid": 2, "names": ["가"] + [""] * 9,
                                            "hidden_sapi": ["X"], "sample": "시험 글"}))
c = tts_engine.cfg_of(mw)
chk(c["names"][0] == "가" and c["hidden_sapi"] == ["X"] and c["sample"] == "시험 글" and c["sid"] == 2,
    "E 이름·숨김·미리 듣기 글이 남는다", str({k: c[k] for k in ("sid", "hidden_sapi", "sample")}))
ex = tts_engine.export_choice(mw)
chk(ex["voice_label"] == "목소리 3" and ex["hidden_sapi"] == ["X"], "E mp3 에 목소리 이름·숨김", str(ex))

mw.close()
print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
