# -*- coding: utf-8 -*-
"""오프스크린 모달 창 자동 닫기 + 기록 — 메인 창을 띄우는 검사·도구의 공통 장치 (261025-13, 마스터 §14.7.2 의 6).

오프스크린에는 누를 사람이 없어 모달 창(`QMessageBox.information(...)`·`dlg.exec()`)이 뜨면 **영원히 멈춘다**.
검사·도구마다 따로 막아 왔고(ui_check·soak_test·검사 60여 개), 새 도구가 그것을 빠뜨려 261025 오래 켜 두기 시험이
'트리 ↔ 단일' 안내 창에서 77분 멈췄다. 이제 한 곳에서 막는다:

    import modal_guard
    guard = modal_guard.install(label=lambda: cur_op["name"])   # QApplication 을 만든 뒤, 창을 만들기 전에
    ...
    guard.seen      # [(라벨, 종류, 글)] — 무엇이 떴는지 결과에 남긴다(모달이 뜬 것 자체가 단서다)

- 정적 확인 창(`information`·`warning`·`critical`·`question`·`about`): 받아 적고 **안전한 답**(질문은 `No`, 나머지는 `Ok`).
- `QDialog.exec`·`QMessageBox.exec`: 받아 적고 `Rejected`(0) — 호출한 쪽은 '취소' 길로 빠진다. `dialogs=False` 면 그대로 둔다
  (창을 띄워 안을 검사하는 검사용 — 그때도 감시 타이머가 남은 모달을 닫는다).
- 파일·입력 창(`QFileDialog.get*`·`QInputDialog.get*`): 빈 값(취소).
- **감시 타이머**: 위를 비켜 뜬 모달(`open()`+이벤트 루프 등)이 `watch_ms` 넘게 떠 있으면 기록하고 닫는다 — 마지막 안전망.
검사가 특정 답이 필요하면 install 뒤에 그 함수만 다시 바꿔 끼운다(예: `QMessageBox.question = … Yes`).
"""
from __future__ import annotations


class Guard:
    def __init__(self, label):
        self.seen: list = []
        self._label = label or (lambda: "")
        self._timer = None

    def note(self, kind: str, text: str) -> None:
        try:
            lab = str(self._label() or "")
        except Exception:
            lab = ""
        self.seen.append((lab, kind, (text or "")[:160]))
        if self.echo:
            print("!! 모달 %s — %s: %s" % (kind, lab, (text or "")[:80]), flush=True)

    def report(self) -> str:
        return "\n".join("%s | %s | %s" % r for r in self.seen) or "(모달 없음)"

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()


def _text_of(args) -> str:
    return " / ".join(str(x) for x in args[1:3] if isinstance(x, str))


def install(*, label=None, dialogs: bool = True, file_dialogs: bool = True, watch_ms: int = 1500,
            echo: bool = True) -> Guard:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

    g = Guard(label)
    g.echo = echo
    SB = QMessageBox.StandardButton

    def _static(kind):
        def f(*args, **kw):
            g.note(kind, _text_of(args))
            return SB.No if kind == "question" else SB.Ok
        return staticmethod(f)

    for k in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, k, _static(k))
    QMessageBox.about = staticmethod(lambda *a, **k: g.note("about", _text_of(a)))
    if dialogs:
        def _exec(self, *a, **k):
            txt = self.text() if isinstance(self, QMessageBox) else self.windowTitle()
            g.note("exec:" + type(self).__name__, txt)
            return 0
        QDialog.exec = _exec
        QMessageBox.exec = _exec
    if file_dialogs:
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (g.note("file", "save"), ("", ""))[1])
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (g.note("file", "open"), ("", ""))[1])
        QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (g.note("file", "open-many"), ([], ""))[1])
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (g.note("file", "dir"), "")[1])
        QInputDialog.getText = staticmethod(lambda *a, **k: (g.note("input", _text_of(a)), ("", False))[1])
        QInputDialog.getInt = staticmethod(lambda *a, **k: (g.note("input", _text_of(a)), (0, False))[1])
        QInputDialog.getItem = staticmethod(lambda *a, **k: (g.note("input", _text_of(a)), ("", False))[1])

    if watch_ms and QApplication.instance() is not None:
        state = {"w": None, "n": 0}

        def _watch():
            w = QApplication.activeModalWidget()
            if w is None:
                state["w"], state["n"] = None, 0
                return
            if w is not state["w"]:
                state["w"], state["n"] = w, 0
                return
            state["n"] += 1                              # 두 번 연달아 같은 모달 = watch_ms 넘게 떠 있음
            g.note("watchdog:" + type(w).__name__, w.windowTitle())
            try:
                if isinstance(w, QDialog):
                    w.reject()
                else:
                    w.close()
            except RuntimeError:
                pass
            state["w"], state["n"] = None, 0
        t = QTimer()
        t.setInterval(max(100, int(watch_ms)))
        t.timeout.connect(_watch)
        t.start()
        g._timer = t
    return g
