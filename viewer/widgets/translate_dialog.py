"""PDF 번역 PoC 다이얼로그 (P0) — 텍스트 1청크를 Claude 로 번역·토큰/비용 확인.

SOT: `PDF 번역·요약 작업 계획서.md` (P0). 본격 파이프라인(추출·용어집·문서조립)은 P1~.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QTextBrowser, QMessageBox,
)

from ..study import translate_api as tapi


class _CountWorker(QThread):
    done = pyqtSignal(int, list)

    def __init__(self, key, text, model, auth="api"):
        super().__init__()
        self._key, self._text, self._model, self._auth = key, text, model, auth

    def run(self):
        n, dbg = tapi.count_tokens_debug(self._key, self._text,
                                         model=self._model, auth=self._auth)
        self.done.emit(n, dbg)


class _TransWorker(QThread):
    done = pyqtSignal(str, list)
    gloss = pyqtSignal(int)        # 용어집 개수(빌드 후)

    def __init__(self, key, text, model, auth="api"):
        super().__init__()
        self._key, self._text, self._model, self._auth = key, text, model, auth

    def run(self):
        # P2/P2b: 사전 1순위 + Claude 자동 제안 용어집(스레드 전용 DictStore)
        glossary = []
        store = None
        try:
            from ..study.dict_store import DictStore
            store = DictStore()
        except Exception:
            store = None
        try:
            from ..study import glossary_build as gb
            glossary = gb.build_glossary_with_auto(
                self._text, store, self._key, self._model, self._auth)
        except Exception:
            glossary = []
        self.gloss.emit(len(glossary))
        out, dbg = tapi.translate_text_debug(self._key, self._text, model=self._model,
                                             glossary=glossary, auth=self._auth)
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        self.done.emit(out, dbg)


class TranslatePocDialog(QDialog):
    def __init__(self, prefs: dict, parent=None, initial_text: str = "", glossary=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 번역 (베타·Claude) — PoC")
        self.resize(820, 640)
        self._prefs = prefs or {}
        self._auth = str(self._prefs.get("translate_auth", "api")).strip()
        self._key = str(self._prefs.get("anthropic_api_key", "")).strip()
        self._model = str(self._prefs.get("translate_model", tapi.DEFAULT_MODEL))
        self._glossary = list(glossary or [])
        self._workers = []

        v = QVBoxLayout(self)
        label = next((l for mid, l, *_ in tapi.MODELS if mid == self._model), self._model)
        if self._auth == "login":
            authtxt = "Claude 로그인(구독)"
            ready = True
        else:
            authtxt = "API 키"
            ready = bool(self._key)
        status = "준비됨" if ready else "<span style=color:#c00>설정 필요</span>"
        v.addWidget(QLabel(f"<b>모델:</b> {label} &nbsp;|&nbsp; "
                           f"<b>인증:</b> {authtxt} ({status}) &nbsp;|&nbsp; "
                           f"<b>용어집:</b> 사전+자동 제안(번역 시 생성)"))
        v.addWidget(QLabel("번역할 본문(현재 PDF 앞부분을 채워 두었습니다. 수정 가능):"))
        self.ed = QPlainTextEdit()
        self.ed.setPlainText(initial_text or "")
        v.addWidget(self.ed, 1)

        row = QHBoxLayout()
        self.btn_count = QPushButton("예상 토큰·비용")
        self.btn_run = QPushButton("번역 실행")
        self.btn_close = QPushButton("닫기")
        row.addWidget(self.btn_count)
        row.addWidget(self.btn_run)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        v.addLayout(row)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#555;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        v.addWidget(QLabel("번역 결과:"))
        self.out = QTextBrowser()
        v.addWidget(self.out, 1)

        self.btn_count.clicked.connect(self._count)
        self.btn_run.clicked.connect(self._run)
        self.btn_close.clicked.connect(self.reject)

        if not tapi.available():
            self.info.setText("anthropic SDK 가 설치되어 있지 않습니다(배포본에는 포함). "
                              "개발 환경이면 'pip install anthropic'.")
            self.btn_count.setEnabled(False)
            self.btn_run.setEnabled(False)
        elif self._auth == "login":
            self.info.setText("Claude 로그인(구독) 모드 — 터미널에서 'claude' 또는 'ant auth login' "
                              "으로 로그인되어 있어야 합니다. '예상 토큰·비용'으로 연결을 확인하세요.")
        elif not self._key:
            self.info.setText("설정 → '번역(Claude)' 에서 API 키를 입력하거나 인증 방식을 "
                              "'Claude 로그인(구독)'으로 바꾸세요.")

    # ----- 토큰/비용 -----
    def _count(self):
        text = self.ed.toPlainText().strip()
        if not text:
            self.info.setText("번역할 본문이 없습니다.")
            return
        self.info.setText("토큰 계산 중…")
        self.btn_count.setEnabled(False)
        w = _CountWorker(self._key, text, self._model, self._auth)
        self._workers.append(w)
        w.done.connect(self._on_count)
        w.finished.connect(lambda w=w: self._drop(w))
        w.start()

    def _on_count(self, n, dbg):
        self.btn_count.setEnabled(True)
        if n < 0:
            self.info.setText("토큰 계산 실패: " + (dbg[-1] if dbg else ""))
            return
        # 출력 토큰은 대략 입력과 비슷하다고 가정해 상한 추정
        est = tapi.estimate_cost(self._model, n, n)
        usd = f"${est:.3f}"
        self.info.setText(f"입력 토큰 ≈ {n:,} · 예상 비용(출력≈입력 가정) ≈ {usd} "
                          f"(USD, 캐싱·실제 출력량에 따라 달라짐)")

    # ----- 번역 -----
    def _run(self):
        text = self.ed.toPlainText().strip()
        if not text:
            self.info.setText("번역할 본문이 없습니다.")
            return
        if not bool(self._prefs.get("translate_consent", False)):
            r = QMessageBox.question(
                self, "외부 전송 동의",
                "번역을 위해 본문이 Anthropic(Claude) 서버로 전송됩니다.\n계속할까요?\n"
                "(설정 → '번역(Claude)' 에서 항상 동의로 둘 수 있습니다.)")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.info.setText("용어집 생성 + 번역 준비 중…")
        self.out.setPlainText("")
        self.btn_run.setEnabled(False)
        w = _TransWorker(self._key, text, self._model, self._auth)
        self._workers.append(w)
        w.gloss.connect(lambda n: self.info.setText(f"용어집 {n}개 적용 · 번역 중…"))
        w.done.connect(self._on_trans)
        w.finished.connect(lambda w=w: self._drop(w))
        w.start()

    def _on_trans(self, out, dbg):
        self.btn_run.setEnabled(True)
        if not out:
            self.info.setText("번역 실패: " + (dbg[-1] if dbg else ""))
            return
        self.info.setText("완료 · " + (" | ".join(dbg) if dbg else ""))
        self.out.setPlainText(out)

    def _drop(self, w):
        try:
            if w in self._workers:
                self._workers.remove(w)
        except Exception:
            pass
