"""파일 해시태그 편집 다이얼로그 — SOT: `파일 태그·키워드 작업 계획서.md` §8.1.

260829 P3 재설계(자동 부여 이후 '붙이는 곳'→'고치는 곳'):
- 입력줄은 **수동 태그 전용**(기존 `set()` 계약 유지).
- 자동 태그는 **칩 행**으로 분리 — ✕(거절→rejected 영구) / 📌(고정→manual 승격).
  ★ 확인 버튼은 승격하지 않는다(§8.1) — 아무 조작 없이 확인하면 auto 신분 유지.
  (P2 직후 잠복 결함 수정: 기존엔 get() 합집합을 입력줄에 넣어 확인만 눌러도
   자동 태그 전부가 manual 로 저장 = 무단 승격이었다.)
- 제안 구획(§5.6 suggest): 기존 태그 칩(클릭=입력줄 추가) / 신규 후보 칩(점선 —
  클릭=수동 채택). 제안은 세션 캐시가 있을 때만(suggest_provider).
- 칩 툴팁 = 근거(§1-⑥ — 자동 부여에서는 필수).

다이얼로그는 순수 UI — store 를 만지지 않고 결과만 반환한다(테스트 용이):
`tags()`(수동 입력줄), `rejected_tags()`, `promoted_tags()`.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

_CHIP_BLUE = ("QPushButton{color:#1456c4;border:1px solid #cfe0ff;"
              "border-radius:9px;padding:1px 8px;background:#f3f8ff;}"
              "QPushButton:hover{background:#e3efff;}")
_CHIP_NEW = ("QPushButton{color:#7a5b00;border:1px dashed #d9b64a;"
             "border-radius:9px;padding:1px 8px;background:#fffaf0;}"
             "QPushButton:hover{background:#fdf3d7;}")
_CHIP_AUTO = ("QPushButton{color:#666;border:1px solid #ddd;"
              "border-radius:9px;padding:1px 6px;background:#f7f7f7;}"
              "QPushButton:checked{background:#fdecec;color:#b00;"
              "text-decoration:line-through;}")
_PIN = ("QPushButton{border:1px solid #ddd;border-radius:9px;padding:1px 5px;"
        "background:#f7f7f7;}"
        "QPushButton:checked{background:#e8f4e8;border-color:#7ab97a;}")


class TagEditDialog(QDialog):
    def __init__(self, file_name: str, manual_tags, existing_tags, parent=None,
                 auto_tags=None, auto_conf=None, suggestions=None):
        """manual_tags=입력줄 초기값(수동만!), auto_tags=[태그…], auto_conf={태그:점수},
        suggestions=[{tag, score, kind}] | None(세션 캐시 없음 — 구획 숨김)."""
        super().__init__(parent)
        self.setWindowTitle("해시태그 편집")
        self.resize(500, 360)
        self._auto = list(auto_tags or [])
        self._rej_btns = {}
        self._pin_btns = {}
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{file_name}</b> 의 해시태그"))

        v.addWidget(QLabel("수동 태그(공백/쉼표 구분, # 생략 가능):"))
        self.ed = QLineEdit(" ".join(manual_tags or []))
        self.ed.setPlaceholderText("예: 지침 도로 2024")
        v.addWidget(self.ed)

        # ── 자동 태그 칩 행(§8.3 구분 · §8.5 거절/승격) ────────────────────
        if self._auto:
            v.addWidget(QLabel("자동 부여된 태그 — ✕ 지우면 다시 붙지 않고, "
                               "📌 고정하면 수동 태그가 됩니다:"))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            conf = auto_conf or {}
            for t in self._auto:
                chip = QPushButton("·#" + t)
                chip.setCheckable(True)               # 체크 = 거절(✕)
                chip.setStyleSheet(_CHIP_AUTO)
                sc = conf.get(t)
                chip.setToolTip(f"자동 부여{f' (신뢰도 {sc:.2f})' if sc else ''}"
                                " — 클릭하면 거절(다시 붙지 않음)")
                pin = QPushButton("📌")
                pin.setCheckable(True)
                pin.setStyleSheet(_PIN)
                pin.setToolTip(f"#{t} 를 수동 태그로 고정 — 이후 재계산이 건드리지 않음")

                def _excl(_=False, a=chip, b=pin):    # 거절과 고정은 상호 배타
                    if a.isChecked():
                        b.setChecked(False)

                def _excl2(_=False, a=pin, b=chip):
                    if a.isChecked():
                        b.setChecked(False)

                chip.clicked.connect(_excl)
                pin.clicked.connect(_excl2)
                self._rej_btns[t] = chip
                self._pin_btns[t] = pin
                h.addWidget(chip)
                h.addWidget(pin)
            h.addStretch(1)
            v.addWidget(row)

        # ── 제안 구획(§5.6 — 세션 캐시 있을 때만) ─────────────────────────
        sugg = [s for s in (suggestions or [])
                if s.get("tag") and s["tag"].lower() not in
                {x.lower() for x in (list(manual_tags or []) + self._auto)}]
        if sugg:
            ex = [s for s in sugg if s.get("kind") == "existing"][:6]
            nw = [s for s in sugg if s.get("kind") == "new"][:4]
            if ex:
                v.addWidget(QLabel("제안 — 기존 태그(클릭하면 추가):"))
                v.addWidget(self._chip_row(ex, _CHIP_BLUE, "기존 태그 제안"))
            if nw:
                v.addWidget(QLabel("제안 — 새 태그 후보(클릭 = 수동 채택):"))
                v.addWidget(self._chip_row(nw, _CHIP_NEW, "새 태그 후보(§5.4-5 — 자동으로는 붙지 않음)"))

        v.addWidget(QLabel("기존 태그(클릭하면 추가):"))
        wrap = QWidget()
        self._flow = QHBoxLayout(wrap)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setSpacing(4)
        shown = [t for t in (existing_tags or [])][:40]
        for t in shown:
            b = QPushButton("#" + t)
            b.setFlat(True)
            b.setStyleSheet(_CHIP_BLUE)
            b.clicked.connect(lambda _=False, tag=t: self._add_tag(tag))
            self._flow.addWidget(b)
        self._flow.addStretch(1)
        v.addWidget(wrap)
        if not shown:
            v.addWidget(QLabel("(아직 등록된 태그가 없습니다 — 위에 입력해 만드세요.)"))
        v.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _chip_row(self, items, style, why_prefix) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for s in items:
            b = QPushButton("#" + s["tag"])
            b.setStyleSheet(style)
            sc = s.get("score")
            b.setToolTip(f"{why_prefix}{f' — 점수 {sc:.2f}' if sc else ''}"
                         + (f" · {s['why']}" if s.get("why") else ""))
            b.clicked.connect(lambda _=False, tag=s["tag"]: self._add_tag(tag))
            h.addWidget(b)
        h.addStretch(1)
        return row

    def _add_tag(self, tag: str):
        cur = self.ed.text().split()
        if tag.lower() not in [c.lstrip("#").lower() for c in cur]:
            self.ed.setText((self.ed.text() + " " + tag).strip())

    # ── 결과 (호출부가 store 에 적용 — §8.1) ─────────────────────────────
    def tags(self) -> str:
        """수동 태그 입력줄(기존 계약). 자동 태그는 여기 섞이지 않는다."""
        return self.ed.text()

    def rejected_tags(self) -> list:
        return [t for t, b in self._rej_btns.items() if b.isChecked()]

    def promoted_tags(self) -> list:
        return [t for t, b in self._pin_btns.items() if b.isChecked()]
