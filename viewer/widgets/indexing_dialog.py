# -*- coding: utf-8 -*-
"""폴더 인덱싱 진행 창 (260902-6, 사용자 요청 — 검색 SOT §4.4 · 디자인 §2.7).

폴더를 처음 열면 인덱싱(본문 추출·FTS 적재)이 백그라운드로 돌아 잠시 버벅인다. 종전엔
상태바 진행률만 있어, 처음 쓰는 사람은 프로그램이 이상한 줄 알았다(사용자 보고).

- 비모달·도구 창(메인 위에 떠 있되 작업을 막지 않음). 파일 진행률 + 현재 파일명.
- 안내 문구: 인덱싱 중엔 느려질 수 있으니 끝난 뒤 작업을 권함.
- [아래로 숨기기] → 창만 닫히고 상태바 메시지·진행률은 그대로.
- 끝나면 저절로 사라진다. 다시 띄우려면 다음 인덱싱 때 자동으로 뜬다.
- 짧게 끝나는 인덱싱(단일 파일·소량)엔 깜빡이지 않도록 SHOW_DELAY_MS 뒤에 아직 진행 중일
  때만 보인다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QLabel, QProgressBar, QPushButton,
                             QVBoxLayout, QHBoxLayout)


class IndexingDialog(QDialog):
    SHOW_DELAY_MS = 700          # 이 시간 안에 끝나면 아예 안 띄운다(깜빡임 방지)

    def __init__(self, parent=None, folder_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("PolyPDF — 폴더 인덱싱")
        # 도구 창: 메인 위에 머물되 모달 아님. 닫기(✕)는 '아래로 숨기기'와 같다.
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.CustomizeWindowHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setModal(False)
        self.setMinimumWidth(420)
        self._hidden_by_user = False
        self._finished = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(8)
        self.lbl_title = QLabel("<b>폴더를 인덱싱하는 중입니다</b>"
                                + (f" — {folder_name}" if folder_name else ""))
        self.lbl_title.setWordWrap(True)
        lay.addWidget(self.lbl_title)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)                       # 총량을 알기 전엔 '바쁨' 표시
        self.bar.setTextVisible(True)
        lay.addWidget(self.bar)
        self.lbl_file = QLabel("준비 중...")
        self.lbl_file.setStyleSheet("color:#666;")
        self.lbl_file.setWordWrap(True)
        lay.addWidget(self.lbl_file)
        self.lbl_hint = QLabel(
            "인덱싱은 PDF 본문을 읽어 검색·태그를 준비하는 작업입니다. "
            "<b>진행 중에는 화면 전환이나 검색이 느려질 수 있으니, 끝난 뒤에 작업하시길 권합니다.</b> "
            "이 창을 숨겨도 인덱싱은 계속되며 진행 상황은 왼쪽 아래 상태바에 표시됩니다.")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#444; margin-top:4px;")
        lay.addWidget(self.lbl_hint)

        row = QHBoxLayout(); row.addStretch(1)
        self.btn_hide = QPushButton("아래로 숨기기")
        self.btn_hide.setToolTip("창을 닫고 상태바 메시지로만 진행 상황을 봅니다(인덱싱은 계속)")
        # 디자인 §2.7: Enter 가 버튼을 누르지 않게
        self.btn_hide.setAutoDefault(False); self.btn_hide.setDefault(False)
        self.btn_hide.clicked.connect(self.hide_to_status)
        row.addWidget(self.btn_hide)
        lay.addLayout(row)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_if_running)

    # ── 표시 제어 ─────────────────────────────────────────────────────
    def start(self):
        """지연 표시 예약 — SHOW_DELAY_MS 안에 끝나면 띄우지 않는다."""
        self._finished = False
        self._hidden_by_user = False
        self._show_timer.start(self.SHOW_DELAY_MS)

    def _show_if_running(self):
        if self._finished or self._hidden_by_user:
            return
        self.show()
        self.raise_()

    def hide_to_status(self):
        """[아래로 숨기기] — 창만 닫고 상태바에 맡긴다."""
        self._hidden_by_user = True
        self._show_timer.stop()
        self.hide()

    def closeEvent(self, ev):                      # 창의 ✕ 도 '숨기기'와 동일
        self.hide_to_status()
        ev.ignore()

    # ── 진행 갱신 ─────────────────────────────────────────────────────
    def on_progress(self, done: int, total: int, name: str):
        if total > 0:
            if self.bar.maximum() != total:
                self.bar.setRange(0, total)
            self.bar.setValue(int(done))
            self.bar.setFormat(f"{done} / {total} 파일")
        self.lbl_file.setText(str(name) if name else "...")

    def on_finished(self):
        """끝나면 저절로 사라진다(사용자가 숨겼어도 상태 정리)."""
        self._finished = True
        self._show_timer.stop()
        self.hide()
        self.deleteLater()
