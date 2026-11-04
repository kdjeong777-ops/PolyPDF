# -*- coding: utf-8 -*-
"""보기설정 — 사진 모드 줄 표기 스타일 (사진 보기 SOT 4.38, 261104-13 사용자 지시).

조각 단추(날짜·파일명·가로×세로·용량(MB)·확장자)와 구분자로 **구문**을 만들고(직접 고쳐도 된다), 이름을 붙여 스타일로 저장한다.
[적용] 하면 그 스타일로 보인다. 책갈피창은 한 줄, 썸네일창은 윗줄·아랫줄. 미리보기는 지금 사진으로.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from viewer import photo_label as PL
from viewer.i18n import tr


class PhotoLabelDialog(QDialog):
    """`prefs` 는 picture 묶음(바로 고친다 — 적용하면 부르는 쪽이 저장·다시 그린다). `on_apply()` 는 [적용]·[확인] 때."""

    def __init__(self, parent, prefs: dict, which: str, sample: dict, on_apply=None):
        super().__init__(parent)
        self.prefs, self.which, self.sample, self.on_apply = prefs, which, dict(sample or {}), on_apply
        self.setWindowTitle(tr("보기설정 — 책갈피창") if which == "tree" else tr("보기설정 — 썸네일창"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("스타일")))
        self.cb = QComboBox()
        self.cb.setObjectName("labelStyle")
        row.addWidget(self.cb, 1)
        self.b_new = QPushButton(tr("새 스타일..."))
        self.b_del = QPushButton(tr("지우기"))
        row.addWidget(self.b_new)
        row.addWidget(self.b_del)
        lay.addLayout(row)

        grid = QGridLayout()
        self.eds = []
        lines = [tr("구문")] if which == "tree" else [tr("윗줄"), tr("아랫줄")]
        for i, lab in enumerate(lines):
            grid.addWidget(QLabel(lab), i, 0)
            ed = QLineEdit()
            ed.setObjectName("labelLine%d" % i)
            ed.textChanged.connect(self._preview)
            grid.addWidget(ed, i, 1)
            self.eds.append(ed)
        lay.addLayout(grid)
        self._target = self.eds[0]
        for ed in self.eds:
            ed.installEventFilter(self)

        tok = QHBoxLayout()
        tok.addWidget(QLabel(tr("넣기")))
        for f in PL.FIELDS:
            b = QPushButton(tr(PL.FIELD_LABEL[f]))
            b.setObjectName("tok_" + f)
            b.clicked.connect(lambda _=False, k=f: self._insert("{%s}" % k))
            tok.addWidget(b)
        self.cb_sep = QComboBox()
        for s in PL.SEPARATORS:
            self.cb_sep.addItem(tr("빈칸") if s == " " else repr(s)[1:-1], s)
        b_sep = QPushButton(tr("구분자"))
        b_sep.setObjectName("tok_sep")
        b_sep.clicked.connect(lambda: self._insert(self.cb_sep.currentData()))
        tok.addWidget(self.cb_sep)
        tok.addWidget(b_sep)
        b_back = QPushButton(tr("마지막 조각 지우기"))
        b_back.setObjectName("tok_back")
        b_back.clicked.connect(self._drop_last)
        tok.addWidget(b_back)
        tok.addStretch(1)
        lay.addLayout(tok)

        self.lbl_prev = QLabel()
        self.lbl_prev.setObjectName("labelPreview")
        self.lbl_prev.setStyleSheet("padding: 6px; border: 1px solid palette(mid);")
        lay.addWidget(QLabel(tr("미리보기 (지금 사진)")))
        lay.addWidget(self.lbl_prev)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Apply
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Apply).setText(tr("적용"))
        bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.b_new.clicked.connect(self._new)
        self.b_del.clicked.connect(self._delete)
        self.cb.currentIndexChanged.connect(self._load)
        self._fill(PL.current_name(prefs, which))

    # ── 스타일 목록 ──────────────────────────────
    def _fill(self, pick: str):
        self.cb.blockSignals(True)
        self.cb.clear()
        for name in PL.styles(self.prefs, self.which):
            self.cb.addItem(PL.display_name(name), name)
        i = self.cb.findData(pick)
        self.cb.setCurrentIndex(max(0, i))
        self.cb.blockSignals(False)
        self._load()

    def _name(self) -> str:
        return self.cb.currentData() or PL.DEFAULT

    def _load(self, *_):
        tpl = PL.styles(self.prefs, self.which).get(self._name())
        vals = [tpl] if self.which == "tree" else list(tpl or ["", ""])
        for ed, v in zip(self.eds, vals):
            ed.blockSignals(True)
            ed.setText(v or "")
            ed.blockSignals(False)
        mine = ((self.prefs.get("label_styles") or {}).get(self.which) or {}).get("custom") or {}
        self.b_del.setText(tr("기본값으로") if PL.is_builtin(self.which, self._name()) else tr("지우기"))
        self.b_del.setEnabled(not PL.is_builtin(self.which, self._name()) or self._name() in mine)
        self._preview()

    def _tpl(self):
        return self.eds[0].text() if self.which == "tree" else [e.text() for e in self.eds]

    # ── 구문 고치기 ──────────────────────────────
    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.FocusIn and obj in self.eds:
            self._target = obj                      # 조각은 마지막으로 누른 줄에 넣는다
        return False

    def _insert(self, s: str):
        self._target.insert(s)
        self._target.setFocus()

    def _drop_last(self):
        """마지막 조각(`{…}` 하나 또는 끝의 구분자 글)을 지운다."""
        t = self._target.text()
        import re
        m = re.search(r"\{[a-z]+\}$", t)
        if m:
            t = t[:m.start()]
        else:
            t = re.sub(r"[^{}]+$", "", t) if not t.endswith("}") else t[:-1]
        self._target.setText(t)

    def _preview(self, *_):
        tpl = self._tpl()
        lines = [tpl] if self.which == "tree" else tpl
        self.lbl_prev.setText("\n".join(PL.render(x, self.sample) for x in lines))

    # ── 저장 ────────────────────────────────────
    def _new(self):
        name, ok = QInputDialog.getText(self, tr("새 스타일"), tr("스타일 이름"))
        name = (name or "").strip()
        if not ok or not name:
            return
        PL.save(self.prefs, self.which, name, self._tpl())
        self._fill(name)

    def _delete(self):
        name = self._name()
        if not PL.is_builtin(self.which, name):
            if QMessageBox.question(self, tr("스타일 지우기"), tr("'{name}' 스타일을 지울까요?").format(name=name)) \
                    != QMessageBox.StandardButton.Yes:
                return
        PL.delete(self.prefs, self.which, name)
        # 기본 스타일을 '기본값으로' 되돌렸으면 그 스타일에 머문다 — 지운 사용자 스타일이면 지금 스타일로
        self._fill(name if PL.is_builtin(self.which, name) else PL.current_name(self.prefs, self.which))

    def apply(self):
        """지금 구문을 고른 스타일에 남기고 지금 스타일로 — 부르는 쪽이 다시 그린다."""
        name = self._name()
        if self._tpl() != PL.styles(self.prefs, self.which).get(name) or not PL.is_builtin(self.which, name):
            PL.save(self.prefs, self.which, name, self._tpl())
        else:
            PL.select(self.prefs, self.which, name)
        self._load()
        if self.on_apply is not None:
            self.on_apply()

    def _ok(self):
        self.apply()
        self.accept()
