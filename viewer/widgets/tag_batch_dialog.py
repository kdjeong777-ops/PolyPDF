"""신규 태그 후보 검토 다이얼로그 — SOT: `파일 태그·키워드 작업 계획서.md` §5.4-5·§8.5.

자동 부여되지 않고 적립된 신규 태그 후보(주제 축)를 **한 화면에서** 검토한다.
- 채택: 근거 파일들에 auto 로 부여 → 그 순간부터 **기존 어휘**가 되어
  다음 계산부터 자동 부여 대상(§5.4-5 — 어휘 성장의 유일한 관문).
- 무시: 전역 rejected 에 기록 — 다시 적립되지 않는다.
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from viewer.tag_store import load_candidates, save_candidates


class CandidateReviewDialog(QDialog):
    def __init__(self, store, parent=None, candidates_path=None):
        super().__init__(parent)
        self.setWindowTitle("새 태그 후보 검토")
        self.resize(560, 420)
        self._store = store
        self._cpath = candidates_path
        self._data = load_candidates(candidates_path)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "자동으로 붙이지 않고 모아 둔 새 태그 후보입니다(태그 SOT §5.4-5).\n"
            "채택하면 근거 파일에 ·자동 태그로 붙고, 이후 계산부터 기존 태그로 쓰입니다."))
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self._rows = QVBoxLayout(inner)
        area.setWidget(inner)
        v.addWidget(area, 1)
        self._render()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)

    def _render(self):
        while self._rows.count():
            it = self._rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cand = sorted(self._data.get("cand", {}).items(),
                      key=lambda kv: -kv[1].get("n", 0))
        if not cand:
            self._rows.addWidget(QLabel("(검토할 후보가 없습니다.)"))
        for tag, info in cand[:60]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            names = ", ".join(os.path.basename(p) for p in info.get("files", [])[:3])
            lab = QLabel(f"<b>#{tag}</b>  ({info.get('n', 0)}건)  "
                         f"<span style='color:#888'>{names}</span>")
            lab.setToolTip("\n".join(info.get("files", [])))
            h.addWidget(lab, 1)
            b_ok = QPushButton("채택")
            b_ok.clicked.connect(lambda _=False, t=tag: self._adopt(t))
            b_no = QPushButton("무시")
            b_no.setToolTip("전역 기록 — 다시 적립되지 않습니다")
            b_no.clicked.connect(lambda _=False, t=tag: self._dismiss(t))
            h.addWidget(b_ok)
            h.addWidget(b_no)
            self._rows.addWidget(row)
        self._rows.addStretch(1)

    def _adopt(self, tag: str):
        info = self._data["cand"].pop(tag, None)
        if info:
            with self._store.bulk():
                for p in info.get("files", []):
                    cur = self._store.get_auto(p)
                    if tag.lower() not in {t.lower() for t in cur}:
                        # 기존 auto_conf 보존 병합(추가형 부여)
                        conf = {}
                        try:
                            v = self._store._data.get(self._store._key(p))
                            if isinstance(v, dict):
                                conf = dict(v.get("auto_conf") or {})
                        except Exception:
                            pass
                        conf[tag] = 0.75
                        self._store.set_auto(p, cur + [tag], conf=conf)
        save_candidates(self._data, self._cpath)
        self._render()

    def _dismiss(self, tag: str):
        self._data["cand"].pop(tag, None)
        if tag not in self._data["rejected"]:
            self._data["rejected"].append(tag)
        save_candidates(self._data, self._cpath)
        self._render()
