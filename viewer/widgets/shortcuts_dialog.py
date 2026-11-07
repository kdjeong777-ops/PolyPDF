"""단축키 설정 다이얼로그 — 전체 단축키 표시·수정·기본값 복원 (260606-19)."""
from __future__ import annotations

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QKeySequenceEdit,
    QDialogButtonBox, QPushButton, QHBoxLayout, QScrollArea, QWidget, QCheckBox,
)
from viewer.i18n import tr
from viewer.widgets.keycaps import KeycapLabel


class ShortcutsDialog(QDialog):
    def __init__(self, defs, current: dict, parent=None, capture_global=False):
        """defs: OrderedDict id→(label, default_seq, group). current: {id: seq}.

        260611-3: 그룹별 표시 + 화면 캡처 전역 단축키 토글.
        defs 가 2-튜플(구버전)이어도 호환되게 처리.
        """
        super().__init__(parent)
        self.setWindowTitle(tr("단축키 설정"))
        self.setMinimumWidth(460)
        self._defs = defs
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr("기능별 단축키를 클릭해 새 키 조합을 입력하세요 (그룹별 정리).")))

        area = QScrollArea(); area.setWidgetResizable(True)
        inner = QWidget(); g = QGridLayout(inner)
        self._edits = {}
        # 그룹 순서 유지하며 헤더 + 항목 배치
        row = 0
        last_group = None
        for sid, meta in defs.items():
            label = meta[0]; default = meta[1]
            group = meta[2] if len(meta) > 2 else tr("기타")
            if group != last_group:
                hdr = QLabel(f"<b>― {group} ―</b>")
                g.addWidget(hdr, row, 0, 1, 3); row += 1
                last_group = group
            g.addWidget(QLabel(label), row, 0)
            ed = QKeySequenceEdit(QKeySequence(current.get(sid, default)))
            self._edits[sid] = ed
            g.addWidget(ed, row, 1)
            # 261107-4(디자인 SOT §2.9.2): 메뉴에 보일 모양 그대로 — 키캡 그림(같은 그리기)
            cap = KeycapLabel(ed.keySequence().toString(QKeySequence.SequenceFormat.NativeText))
            ed.keySequenceChanged.connect(
                lambda ks, c=cap: c.set_keys(ks.toString(QKeySequence.SequenceFormat.NativeText)))
            self._caps = getattr(self, "_caps", {})
            self._caps[sid] = cap
            g.addWidget(cap, row, 2); row += 1
        area.setWidget(inner)
        v.addWidget(area, 1)

        # 화면 캡처 전역 단축키 토글 (260611-3 / 요청6)
        self.chk_capture_global = QCheckBox(
            tr("화면 캡처를 전역 단축키로 사용 (다른 프로그램 위에서도 작동)"))
        self.chk_capture_global.setChecked(bool(capture_global))
        self.chk_capture_global.setToolTip(
            tr("켜면 활성창이 본 프로그램이 아니거나 시작점이 뷰어 밖일 때 캡처 단축키가 "
            "전역으로 작동해, 보이는 화면을 스크린샷 목록에 저장합니다."))
        v.addWidget(self.chk_capture_global)

        row2 = QHBoxLayout()
        btn_reset = QPushButton(tr("기본값으로 되돌리기"))
        btn_reset.clicked.connect(self._reset_defaults)
        row2.addWidget(btn_reset)
        row2.addStretch(1)
        v.addLayout(row2)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _reset_defaults(self):
        for sid, meta in self._defs.items():
            self._edits[sid].setKeySequence(QKeySequence(meta[1]))

    def result_shortcuts(self) -> dict:
        out = {}
        for sid, ed in self._edits.items():
            seq = ed.keySequence().toString()
            meta = self._defs.get(sid)
            if seq:
                out[sid] = seq
            elif meta and meta[1]:
                out[sid] = ""          # 261107-4: 지운 키는 빈 값으로 남긴다 — 빼면 다음 실행에 기본 키가 되살아난다
        return out

    def result_capture_global(self) -> bool:
        return self.chk_capture_global.isChecked()
