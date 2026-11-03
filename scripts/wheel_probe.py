# -*- coding: utf-8 -*-
"""휠·터치패드 실측 창 (261103-7, 입력 장치 SOT §2.2 규칙 10).

지금 코드의 본문 보기(쪽 맞춤·가벼운 넘김 켬)를 띄우고, 들어오는 휠 이벤트와 넘김을 한 줄씩 기록한다.
창 위에서 두 손가락 쓸기 등을 해 본 뒤 창을 닫으면 끝. 실제 설정 폴더는 쓰지 않는다(시험 모드).

    python scripts/wheel_probe.py [기록 파일]        # 기본: ./wheel_probe_<시각>.log

기록 줄: `처리ms ts=이벤트시각 dy= dx= px= ph=위상 … | smooth need sum edge page 앞->뒤`, 넘김은 `>>> pageStep ±1`.
검사(`test_wheel_touchpad_261103.py` 의 F)에 넣을 때는 이벤트 시각 간격과 dy 를 '간격:값' 으로 떼어 쓴다.
"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    from viewer import perf_mode
    from viewer.widgets import main_view as M
    from test_fixtures import text_pdf

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath("wheel_probe_%s.log" % time.strftime("%H%M%S"))
    f = open(path, "w", encoding="utf-8", buffering=1)
    t0 = time.perf_counter()

    def now():
        return (time.perf_counter() - t0) * 1000.0

    ph = {Qt.ScrollPhase.NoScrollPhase: "none", Qt.ScrollPhase.ScrollBegin: "begin",
          Qt.ScrollPhase.ScrollUpdate: "update", Qt.ScrollPhase.ScrollEnd: "end",
          Qt.ScrollPhase.ScrollMomentum: "momentum"}
    orig = M._PdfGraphicsView.wheelEvent
    mv = None

    def wrapped(self, ev):
        t = now()
        a, p = ev.angleDelta(), ev.pixelDelta()
        pg0 = mv.current_page()
        orig(self, ev)
        f.write("%9.1f ts=%d dy=%d dx=%d px=%d,%d ph=%s inv=%d mods=%d | smooth=%d need=%d sum=%d edge=%d page %d->%d\n" % (
            t, ev.timestamp(), a.y(), a.x(), p.x(), p.y(), ph.get(ev.phase(), "?"), int(ev.inverted()),
            int(ev.modifiers().value), int(self._stream_smooth), int(self._need_new_gesture), self._edge_sum,
            self._edge_dir, pg0, mv.current_page()))

    M._PdfGraphicsView.wheelEvent = wrapped
    perf_mode.set_pref("on")
    mv = M.MainView()
    mv.resize(1000, 900)
    mv.setWindowTitle("휠·터치패드 실측 — 쓸기를 해 본 뒤 창을 닫으세요")
    mv.show()
    mv.load_document(text_pdf(), 0)
    mv.choose_fit(M.MainView.FIT_PAGE)
    mv.view.pageStep.connect(lambda d: f.write("%9.1f >>> pageStep %+d\n" % (now(), d)))
    app.exec()
    f.close()
    print(path)


if __name__ == "__main__":
    main()
