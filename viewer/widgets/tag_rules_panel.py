# -*- coding: utf-8 -*-
"""환경설정 '일반 › 해시태그' 의 해시태그 내용 (태그 SOT §5.8, 디자인 SOT §2.14, 261107-10).

형식 낱말(켜고 끄기·붙일 이름) · 별칭 표(원래 태그 → 붙일 태그) · 사진 머리 태그 종류(켜고 끄기).
값은 `tag_rules.json`(`viewer.tag_rules`) — 창의 결과에 `tag_rules` 로 내고, 저장([적용]·[확인])하면
`MainWindow._settings_apply` 가 `tag_rules.apply` 로 곧바로 다시 붙인다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from viewer.i18n import tr, tr_noop

PHOTO_LABELS = (("date", tr_noop("촬영일")), ("region", tr_noop("지역")), ("device", tr_noop("촬영 장비")),
                ("screenshot", tr_noop("스크린샷")))


class TagRulesPanel(QWidget):
    def __init__(self, rules: dict | None = None, parent=None):
        super().__init__(parent)
        from viewer.auto_tag import FORMAT_VOCAB
        from viewer import tag_rules as TR
        r = TR.normalize(rules)
        alias = dict(r.get("alias") or {})
        off = set(r.get("format_off") or ())
        poff = set(r.get("photo_off") or ())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # 형식 낱말 — 줄마다 체크 상자(켜고 끄기) + 이름 글 상자 하나(261112-11 — 고칠 수 없는 이름 글을 뺐다).
        #   글 상자에는 지금 붙는 이름, 비우면 표준 이름. 형식 이름은 저장 데이터라 번역하지 않는다 — 다국어 SOT §5
        g1 = QGroupBox(tr("형식 낱말 (PDF 자동 해시태그)"))
        v1 = QVBoxLayout(g1)
        gl = QGridLayout()
        gl.setHorizontalSpacing(8)
        self.fmt_chk, self.fmt_name = {}, {}
        for i, f in enumerate(FORMAT_VOCAB):
            cb, ed = self._fmt_pair(f, alias.pop(f, "") or f, f not in off)
            row, col = divmod(i, 2)
            gl.addWidget(cb, row, col * 2)
            gl.addWidget(ed, row, col * 2 + 1)
            gl.setColumnStretch(col * 2 + 1, 1)
            self.fmt_chk[f], self.fmt_name[f] = cb, ed
        v1.addLayout(gl)
        # 사용자가 더한 분류(태그 SOT §5.8 `format_custom`) — 체크 + 이름 + 찾을 낱말 + [빼기]
        self.cust_lay = QVBoxLayout()
        self.cust_lay.setContentsMargins(0, 0, 0, 0)
        self.cust_rows = []
        v1.addLayout(self.cust_lay)
        for c in r.get("format_custom") or ():
            self._add_custom(c["name"], alias.pop(c["name"], "") or c["name"], ", ".join(c.get("words") or ()),
                             c["name"] not in off)
        hb1 = QHBoxLayout()
        self.btn_fmt_add = QPushButton(tr("분류 더하기"))
        self.btn_fmt_add.clicked.connect(lambda: self._add_custom(None, "", "", True, focus=True))
        hb1.addWidget(self.btn_fmt_add)
        hb1.addStretch(1)
        v1.addLayout(hb1)
        v1.addWidget(_small(tr("더한 분류는 이름이나 찾을 낱말이 파일 이름·PDF 제목에 있으면 붙습니다.")))
        lay.addWidget(g1)

        # 별칭 표 — 형식 이름 바꾸기와 같은 표(§5.8) — 여기에는 형식이 아닌 태그만
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
        lay.addWidget(g2)

        # 사진 머리 태그 종류
        g3 = QGroupBox(tr("사진 자동 해시태그 종류"))
        h3 = QHBoxLayout(g3)
        self.photo_chk = {}
        for key, label in PHOTO_LABELS:
            cb = QCheckBox(tr(label))
            cb.setChecked(key not in poff)
            h3.addWidget(cb)
            self.photo_chk[key] = cb
        h3.addStretch(1)
        lay.addWidget(g3)
        lay.addWidget(_small(tr("저장하면 이미 붙은 자동 해시태그도 곧바로 새 규칙으로 바꿉니다(백그라운드, 작업 창에서 멈춤). "
                                "직접 붙인 해시태그는 그대로입니다.")))

    def _fmt_pair(self, std: str | None, text: str, on: bool):
        """체크 상자(글 없음) + 이름 글 상자 — 끄면 글 상자가 잠긴다. std 가 있으면 비울 때 그 이름(자리표시)."""
        cb = QCheckBox()
        cb.setChecked(on)
        ed = QLineEdit(text)
        if std:
            ed.setPlaceholderText(std)
            ed.setToolTip(tr("붙일 이름 — 비우면 '{f}'").format(f=std))
            cb.setToolTip(tr("'{f}' 붙이기").format(f=std))
            cb.setAccessibleName(std)
        else:
            ed.setPlaceholderText(tr("분류 이름"))
        cb.toggled.connect(ed.setEnabled)
        ed.setEnabled(on)
        return cb, ed

    def _add_custom(self, std, text: str, words: str, on: bool, focus: bool = False):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        cb, ed = self._fmt_pair(std, text, on)
        wd = QLineEdit(words)
        wd.setPlaceholderText(tr("찾을 낱말 (쉼표로)"))
        wd.setToolTip(tr("파일 이름·PDF 제목에 이 낱말이 있어도 이 분류를 붙입니다 — 쉼표로 나눠 여러 개"))
        cb.toggled.connect(wd.setEnabled)
        wd.setEnabled(on)
        bx = QPushButton(tr("빼기"))
        row = {"std": std, "cb": cb, "name": ed, "words": wd, "w": w}
        bx.clicked.connect(lambda: self._del_custom(row))
        h.addWidget(cb)
        h.addWidget(ed, 1)
        h.addWidget(wd, 2)
        h.addWidget(bx)
        self.cust_lay.addWidget(w)
        self.cust_rows.append(row)
        for sig in (cb.toggled, ed.textChanged, wd.textChanged):
            sig.connect(lambda *_: self.changed_hook())
        if focus:
            ed.setFocus()
            self.changed_hook()
        return row

    def _del_custom(self, row: dict):
        if row in self.cust_rows:
            self.cust_rows.remove(row)
            row["w"].setParent(None)
            row["w"].deleteLater()
            self.changed_hook()

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
        off = [f for f, cb in self.fmt_chk.items() if not cb.isChecked()]
        for f, ed in self.fmt_name.items():
            if ed.text().strip():
                alias[f] = ed.text().strip()
        custom = []
        for row in self.cust_rows:
            nm = row["name"].text().strip().lstrip("#").strip()
            std = row["std"] or nm                    # 새 줄은 처음 저장 때의 이름이 표준 이름(§5.8)
            if not std:
                continue                              # 이름 없는 새 줄은 버린다
            if nm and nm != std:
                alias[std] = nm
            custom.append({"name": std, "words": TR.split_words(row["words"].text())})
            if not row["cb"].isChecked():
                off.append(std)
        return TR.normalize({
            "alias": alias,
            "format_custom": custom,
            "format_off": off,
            "photo_off": [k for k, cb in self.photo_chk.items() if not cb.isChecked()],
        })

    def connect_changed(self, fn):
        self.changed_hook = fn
        for cb in list(self.fmt_chk.values()) + list(self.photo_chk.values()):
            cb.toggled.connect(fn)
        for ed in self.fmt_name.values():
            ed.textChanged.connect(fn)
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
