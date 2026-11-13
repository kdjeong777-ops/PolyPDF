# -*- coding: utf-8 -*-
"""환경설정 '일반 › 해시태그' 의 해시태그 내용 (태그 SOT §5.8, 디자인 SOT §2.14, 261107-10·261113-10).

자동 해시태그 (PDF 모드)(정해진 13 항목 켜고 끄기 — 이름은 고칠 수 없다, 261113-10) · 별칭 표(원래 태그 → 붙일 태그) ·
자동 해시태그 (사진 모드)(사진 머리 태그 종류 켜고 끄기).
값은 `tag_rules.json`(`viewer.tag_rules`) — 창의 결과에 `tag_rules` 로 내고, 저장([적용]·[확인])하면
`MainWindow._settings_apply` 가 `tag_rules.apply` 로 곧바로 다시 붙인다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from viewer.i18n import tr, tr_noop

PHOTO_LABELS = (("date", tr_noop("촬영일")), ("region", tr_noop("지역")), ("device", tr_noop("촬영 장비")),
                ("screenshot", tr_noop("스크린샷")))
PDF_COLS = 3


class TagRulesPanel(QWidget):
    def __init__(self, rules: dict | None = None, parent=None):
        super().__init__(parent)
        from viewer.auto_tag import PDF_AUTO_ITEMS
        from viewer import tag_rules as TR
        r = TR.normalize(rules)
        alias = dict(r.get("alias") or {})
        off = set(r.get("format_off") or ())
        poff = set(r.get("photo_off") or ())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # 자동 해시태그 (PDF 모드) — 정해진 항목 켜고 끄기만(261113-10 사용자 지시 — 이름 못 고침, 분류 더하기 없음).
        #   항목 이름은 태그 데이터라 번역하지 않는다 — 다국어 SOT §5
        g1 = QGroupBox(tr("자동 해시태그 (PDF 모드)"))
        v1 = QVBoxLayout(g1)
        self.pdf_lay = v1                       # 261113-10 덧붙임: 맨 위에 '파일 해시태그·키워드 자동 부여' 체크가 들어온다(attach)
        gl = QGridLayout()
        gl.setHorizontalSpacing(16)
        self.fmt_chk = {}
        for i, f in enumerate(PDF_AUTO_ITEMS):
            cb = QCheckBox(f)
            cb.setChecked(f not in off)
            row, col = divmod(i, PDF_COLS)
            gl.addWidget(cb, row, col)
            self.fmt_chk[f] = cb
        v1.addLayout(gl)
        v1.addWidget(_small(tr("켜고 끄기만 합니다 — 이름은 고칠 수 없습니다.")))
        lay.addWidget(g1)


        # 별칭 표 — 사진·주제 태그(§5.8). PDF 자동 해시태그 이름은 바꾸지 않는다
        g2 = QGroupBox(tr("별칭 — 이 태그 대신 붙일 이름"))
        v2 = QVBoxLayout(g2)
        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels([tr("원래 태그"), tr("붙일 태그")])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setMinimumHeight(110)
        for k, v in alias.items():
            self._add_row(k, v)
        v2.addWidget(self.tbl)
        hb = QHBoxLayout()
        self.btn_add = QPushButton(tr("줄 더하기"))
        self.btn_del = QPushButton(tr("고른 줄 빼기"))
        self.btn_add.clicked.connect(lambda: (self._add_row("", ""), self.tbl.editItem(self.tbl.item(self.tbl.rowCount() - 1, 0))))
        self.btn_del.clicked.connect(self._del_rows)
        hb.addWidget(self.btn_add)
        hb.addWidget(self.btn_del)
        hb.addStretch(1)
        v2.addLayout(hb)
        v2.addWidget(_small(tr("예: SamsungSM-S918N → GalaxyS23. 사진 장비·지역·종류 태그에도 쓰입니다.")))

        # 자동 해시태그 (사진 모드) — 사진 머리 태그 종류(261113-10: 종전 '사진 자동 해시태그 종류').
        #   261113-10 덧붙임(사용자 지시 'PDF 위·사진 아래로 모아'): 차례 PDF 모드 → 사진 모드 → 별칭, 사진 켜기 체크도 이 묶음 맨 위(attach)
        g3 = QGroupBox(tr("자동 해시태그 (사진 모드)"))
        self.photo_lay = QVBoxLayout(g3)
        h3 = QHBoxLayout()
        self.photo_lay.addLayout(h3)
        self.photo_chk = {}
        for key, label in PHOTO_LABELS:
            cb = QCheckBox(tr(label))
            cb.setChecked(key not in poff)
            h3.addWidget(cb)
            self.photo_chk[key] = cb
        h3.addStretch(1)
        lay.addWidget(g3)
        lay.addWidget(g2)
        lay.addWidget(_small(tr("저장하면 이미 붙은 자동 해시태그도 곧바로 새 규칙으로 바꿉니다(백그라운드, 작업 창에서 멈춤). "
                                "직접 붙인 해시태그는 그대로입니다.")))

    def _add_row(self, k: str, v: str):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        self.tbl.setItem(r, 0, QTableWidgetItem(k))
        self.tbl.setItem(r, 1, QTableWidgetItem(v))

    def _del_rows(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()}, reverse=True)
        for r in rows:
            self.tbl.removeRow(r)
        self.changed_hook()

    def changed_hook(self):
        pass

    def rules(self) -> dict:
        from viewer import tag_rules as TR
        alias = {}
        for r in range(self.tbl.rowCount()):
            a, b = self.tbl.item(r, 0), self.tbl.item(r, 1)
            k, v = (a.text() if a else "").strip(), (b.text() if b else "").strip()
            if k and v:
                alias[k] = v
        return TR.normalize({
            "alias": alias,
            "format_off": [f for f, cb in self.fmt_chk.items() if not cb.isChecked()],
            "photo_off": [k for k, cb in self.photo_chk.items() if not cb.isChecked()],
        })

    def connect_changed(self, fn):
        self.changed_hook = fn
        for cb in list(self.fmt_chk.values()) + list(self.photo_chk.values()):
            cb.toggled.connect(fn)
        self.tbl.itemChanged.connect(fn)
        self.tbl.model().rowsInserted.connect(fn)


def _small(text: str) -> QLabel:
    lb = QLabel("<small>%s</small>" % text)
    lb.setWordWrap(True)
    return lb


def attach(dlg) -> TagRulesPanel:
    """SettingsDialog 의 '해시태그 내용 자리'(`tag_content_layout`)에 붙인다(디자인 SOT §2.14)."""
    from viewer.auto_tag import load_rules
    panel = TagRulesPanel(load_rules())
    dlg.tag_content_layout.addWidget(panel)
    try:                                         # 261113-10 덧붙임(태그 SOT §3.5): PDF 자동 부여 켜기를 PDF 묶음 맨 위로, 끄면 13 항목 잠김
        cb = dlg.chk_auto_tag
        f = cb.font()
        f.setBold(True)
        cb.setFont(f)
        panel.pdf_lay.insertWidget(0, cb)
        if getattr(dlg, "lbl_auto_tag_note", None) is not None:
            panel.pdf_lay.insertWidget(1, dlg.lbl_auto_tag_note)
        cb.toggled.connect(lambda on: [c.setEnabled(on) for c in panel.fmt_chk.values()])
        for c in panel.fmt_chk.values():
            c.setEnabled(cb.isChecked())
        # 261113-10 덧붙임: 사진 켜기·종류 구분 체크와 안내를 '자동 해시태그 (사진 모드)' 맨 위로, 빈 위 묶음은 숨긴다
        for i, w in enumerate((dlg.chk_photo_tag, dlg.chk_photo_kind, getattr(dlg, "lbl_photo_tag_note", None))):
            if w is not None:
                panel.photo_lay.insertWidget(i, w)
        if getattr(dlg, "grp_auto_tags", None) is not None:
            dlg.grp_auto_tags.setVisible(False)
    except Exception:
        pass
    try:
        dlg.chk_photo_tag.toggled.connect(lambda on: [cb.setEnabled(on) for cb in panel.photo_chk.values()])
        for cb in panel.photo_chk.values():
            cb.setEnabled(dlg.chk_photo_tag.isChecked())
    except Exception:
        pass
    panel.connect_changed(dlg.mark_changed)
    dlg.tag_rules_panel = panel
    dlg.add_result_fn(lambda: {"tag_rules": panel.rules()})
    return panel
