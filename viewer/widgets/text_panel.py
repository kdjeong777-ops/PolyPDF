# -*- coding: utf-8 -*-
"""260908-2: 우측 '텍스트' 창 (텍스트 창 SOT).

현재 쪽의 본문을 글로 보여 주고, 고치고, 칠하고, 내보낸다.
  - 표시 범위는 **현재 쪽**(사용자 결정 260908) — 수백 쪽 문서에서도 즉시 뜬다.
  - 스타일은 **제목 / 내용** 둘. 글꼴·굵기·크기·자간·줄간격을 스타일마다 정한다.
  - 고친 줄은 교정 저장소에 남고(즉시 반영), [PDF 에 반영] 을 누르면 OCR 텍스트층까지 적는다.
  - 줄을 고르거나 고치면 **본문 뷰어의 그 자리를 강조**한다(사용자 요청 260908).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                             QToolButton, QCheckBox, QTextEdit, QPushButton,
                             QDoubleSpinBox, QMenu)

# 기본 스타일(설정에 없으면 이것으로 시작) — SOT §3.4
DEFAULT_STYLES = {
    "title": {"family": "맑은 고딕", "size_pt": 15.0, "bold": True,
              "spacing_pt": 0.0, "line_spacing": 1.3},
    "body": {"family": "맑은 고딕", "size_pt": 11.0, "bold": False,
             "spacing_pt": 0.0, "line_spacing": 1.2},
}
HL_COLOR = "#ffe680"
_FONTS = ["맑은 고딕", "굴림", "바탕", "돋움", "Segoe UI"]


class TextPanel(QWidget):
    """페이지 본문 표시·편집 창."""

    # 줄을 고르거나 고쳤다 — (쪽, [사각형…]) 을 본문 뷰어가 받아 강조한다
    lineFocused = pyqtSignal(int, object)
    # 고친 줄 (쪽, 줄, 글) — 앱이 저장소에 남긴다
    lineEdited = pyqtSignal(int, int, str, str)   # 쪽, 줄, 고친 글, 원래 글
    applyToPdfRequested = pyqtSignal()          # [PDF 에 반영]
    bookmarkFromHighlight = pyqtSignal(object)  # [{page,title,level}, …]
    exportWordRequested = pyqtSignal(str)       # "page" | "range" | "all"
    ocrRequested = pyqtSignal()                 # 스캔본인데 OCR 결과가 없을 때
    highlightAdded = pyqtSignal(int, int, int, int, str)  # 쪽, 줄, 시작, 끝, 색

    def __init__(self, parent=None):
        super().__init__(parent)
        self._styles = {k: dict(v) for k, v in DEFAULT_STYLES.items()}
        self._rows = []                 # text_extract2.page_lines 결과
        self._page = 0
        self._path = ""
        self._loading = False
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(3)
        self.cmb_style = QComboBox()
        self.cmb_style.addItem("제목", "title")
        self.cmb_style.addItem("내용", "body")
        self.cmb_style.setToolTip("고른 줄의 스타일 / 아래 값이 적용될 스타일")
        self.cmb_style.currentIndexChanged.connect(self._on_style_pick)
        bar.addWidget(QLabel("스타일"))
        bar.addWidget(self.cmb_style)

        self.cmb_font = QComboBox()
        self.cmb_font.addItems(_FONTS)
        self.cmb_font.setToolTip("이 스타일의 글꼴")
        self.cmb_font.currentTextChanged.connect(lambda t: self._set_style("family", t))
        bar.addWidget(self.cmb_font, 1)

        self.sp_size = QDoubleSpinBox()
        self.sp_size.setRange(6.0, 72.0); self.sp_size.setSingleStep(1.0)
        self.sp_size.setDecimals(0); self.sp_size.setSuffix(" pt")
        self.sp_size.setToolTip("글자 크기")
        self.sp_size.valueChanged.connect(lambda x: self._set_style("size_pt", float(x)))
        bar.addWidget(self.sp_size)

        self.btn_bold = QToolButton(); self.btn_bold.setText("B")
        self.btn_bold.setCheckable(True); self.btn_bold.setToolTip("굵게")
        self.btn_bold.setStyleSheet("QToolButton{font-weight:bold;}")
        self.btn_bold.toggled.connect(lambda b: self._set_style("bold", bool(b)))
        bar.addWidget(self.btn_bold)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(3)
        bar2.addWidget(QLabel("자간"))
        self.sp_sp = QDoubleSpinBox()
        self.sp_sp.setRange(-2.0, 20.0); self.sp_sp.setSingleStep(0.5)
        self.sp_sp.setDecimals(1); self.sp_sp.setSuffix(" pt")
        self.sp_sp.valueChanged.connect(lambda x: self._set_style("spacing_pt", float(x)))
        bar2.addWidget(self.sp_sp)
        bar2.addWidget(QLabel("줄간격"))
        self.sp_ls = QDoubleSpinBox()
        self.sp_ls.setRange(0.8, 3.0); self.sp_ls.setSingleStep(0.1)
        self.sp_ls.setDecimals(1); self.sp_ls.setSuffix(" 배")
        self.sp_ls.valueChanged.connect(lambda x: self._set_style("line_spacing", float(x)))
        bar2.addWidget(self.sp_ls)
        self.cb_omit = QCheckBox("표 생략")
        self.cb_omit.setToolTip("표 안 내용을 '[표 n열 × m행]' 한 줄로 줄입니다")
        self.cb_omit.toggled.connect(lambda _: self.reload())
        bar2.addWidget(self.cb_omit)
        bar2.addStretch(1)
        v.addLayout(bar2)

        bar3 = QHBoxLayout()
        bar3.setSpacing(3)
        self.btn_hl = QPushButton("하이라이트")
        self.btn_hl.setToolTip("고른 글을 칠합니다")
        self.btn_hl.clicked.connect(self._on_highlight)
        self.btn_style_apply = QPushButton("스타일 적용")
        self.btn_style_apply.setToolTip("고른 줄을 위에서 고른 스타일(제목/내용)로 바꿉니다")
        self.btn_style_apply.clicked.connect(self.apply_style_to_selection)
        bar3.addWidget(self.btn_style_apply)
        self.btn_ocr = QPushButton("단어장 생성")
        self.btn_ocr.setToolTip("스캔본을 읽어 글자를 만듭니다(OCR)")
        self.btn_ocr.clicked.connect(self.ocrRequested.emit)
        self.btn_ocr.setVisible(False)
        bar3.addWidget(self.btn_ocr)
        bar3.addWidget(self.btn_hl)
        self.btn_bm = QPushButton("책갈피로")
        self.btn_bm.setToolTip("칠한 곳으로 책갈피를 만듭니다(저장은 책갈피창 💾)")
        self.btn_bm.clicked.connect(self._on_make_bookmarks)
        bar3.addWidget(self.btn_bm)
        self.btn_apply = QPushButton("PDF 에 반영")
        self.btn_apply.setToolTip("고친 글을 OCR 텍스트층에 다시 적습니다(원본 백업)")
        self.btn_apply.clicked.connect(self.applyToPdfRequested.emit)
        bar3.addWidget(self.btn_apply)
        self.btn_word = QToolButton()
        self.btn_word.setText("Word 저장")
        self.btn_word.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.btn_word)
        for key, label in (("page", "현재 쪽"), ("range", "쪽 범위…"), ("all", "문서 전체")):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, k=key: self.exportWordRequested.emit(k))
        self.btn_word.setMenu(m)
        bar3.addWidget(self.btn_word)
        bar3.addStretch(1)
        v.addLayout(bar3)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        self.edit = QTextEdit()
        self.edit.setAcceptRichText(False)
        self.edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.edit.cursorPositionChanged.connect(self._on_cursor)
        self.edit.textChanged.connect(self._on_text_changed)
        v.addWidget(self.edit, 1)

        self._sync_style_widgets()

    # ---------------- 스타일 ----------------
    def styles(self) -> dict:
        return {k: dict(v) for k, v in self._styles.items()}

    def set_styles(self, styles: dict):
        """설정에서 불러온 값 주입(SOT §3.4 — settings.json `text_panel_styles`)."""
        for k in ("title", "body"):
            if isinstance((styles or {}).get(k), dict):
                self._styles[k].update(styles[k])
        self._sync_style_widgets()
        self._apply_styles()

    def _cur_style_key(self) -> str:
        return self.cmb_style.currentData() or "body"

    def _sync_style_widgets(self):
        st = self._styles[self._cur_style_key()]
        for w in (self.cmb_font, self.sp_size, self.btn_bold, self.sp_sp, self.sp_ls):
            w.blockSignals(True)
        i = self.cmb_font.findText(st.get("family", "맑은 고딕"))
        self.cmb_font.setCurrentIndex(max(0, i))
        self.sp_size.setValue(float(st.get("size_pt", 11)))
        self.btn_bold.setChecked(bool(st.get("bold", False)))
        self.sp_sp.setValue(float(st.get("spacing_pt", 0.0)))
        self.sp_ls.setValue(float(st.get("line_spacing", 1.2)))
        for w in (self.cmb_font, self.sp_size, self.btn_bold, self.sp_sp, self.sp_ls):
            w.blockSignals(False)

    def _on_style_pick(self):
        self._sync_style_widgets()

    def apply_style_to_selection(self):
        """260908-3(감사, SOT §4): 고른 줄(들)의 **스타일을 바꾼다**.

        SOT 표에는 있었는데 코드에 없었다 — 콤보가 '어느 스타일을 편집할지' 만 골랐다.
        OCR 폴백에는 글자 크기가 없어 전부 '내용' 으로 잡히므로, 손으로 제목을 지정하는
        길이 반드시 필요하다(SOT §3.4)."""
        key = self._cur_style_key()
        cur = self.edit.textCursor()
        a, b = sorted((cur.selectionStart(), cur.selectionEnd()))
        doc = self.edit.document()
        i0 = doc.findBlock(a).blockNumber()
        i1 = doc.findBlock(b).blockNumber()
        n = 0
        for i in range(i0, i1 + 1):
            if 0 <= i < len(self._rows):
                self._rows[i]["style"] = key
                n += 1
        self._apply_styles()
        self.info.setText(f"{n}줄을 '{'제목' if key == 'title' else '내용'}' 으로 바꿨습니다.")

    def _set_style(self, key, value):
        self._styles[self._cur_style_key()][key] = value
        self._apply_styles()

    def _qfont(self, key: str) -> QFont:
        st = self._styles[key]
        f = QFont(st.get("family", "맑은 고딕"))
        f.setPointSizeF(float(st.get("size_pt", 11)))
        f.setBold(bool(st.get("bold", False)))
        sp = float(st.get("spacing_pt", 0.0) or 0.0)
        if sp:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, sp)
        return f

    def _apply_styles(self):
        """줄마다 그 스타일의 글꼴·자간·줄간격을 입힌다."""
        if not self._rows:
            return
        self._loading = True
        try:
            doc = self.edit.document()
            cur = QTextCursor(doc)
            for i, row in enumerate(self._rows):
                blk = doc.findBlockByNumber(i)
                if not blk.isValid():
                    break
                cur.setPosition(blk.position())
                cur.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                 QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setFont(self._qfont(row.get("style", "body")))
                cur.setCharFormat(fmt)
                bf = cur.blockFormat()
                ls = float(self._styles[row.get("style", "body")].get("line_spacing", 1.2))
                bf.setLineHeight(ls * 100.0, 1)      # 1 = ProportionalHeight
                cur.setBlockFormat(bf)
        finally:
            self._loading = False

    # ---------------- 내용 ----------------
    def set_page(self, path: str, page: int, rows: list, note: str = ""):
        """앱이 뽑아 준 줄 목록을 표시(SOT §3)."""
        self._path, self._page, self._rows = str(path or ""), int(page), list(rows or [])
        self._loading = True
        try:
            self.edit.setPlainText("\n".join(r.get("text", "") for r in self._rows))
        finally:
            self._loading = False
        self._apply_styles()
        n_t = sum(1 for r in self._rows if r.get("style") == "title")
        n_tb = sum(1 for r in self._rows if r.get("kind") == "table")
        msg = f"p.{self._page + 1} · {len(self._rows)}줄 (제목 {n_t}"
        if n_tb:
            msg += f" · 표 {n_tb}"
        msg += ")"
        self.info.setText(note or msg)
        # 스캔본인데 OCR 결과가 없으면 그 자리에서 만들 수 있게(SOT §3.1)
        self.btn_ocr.setVisible(bool(note) and not self._rows)

    def set_busy(self, msg: str) -> None:
        """260908-3: 워커가 뽑는 동안 무엇을 하는지 알린다(응답성 SOT §4 ④)."""
        self.info.setText(msg or "")

    def restore_highlights(self, marks) -> None:
        """260908-3(감사, SOT §6): 저장해 둔 하이라이트를 다시 칠한다.

        종전에는 칠한 것이 **쪽을 넘기면 사라졌다** — 저장소(`text_fix_store`)는 만들어
        놓고 창이 쓰지 않았다. SOT 와 코드가 어긋난 자리였다."""
        if not marks:
            return
        doc = self.edit.document()
        self._loading = True
        try:
            for line, a, b, color in marks:
                blk = doc.findBlockByNumber(int(line))
                if not blk.isValid():
                    continue
                cur = QTextCursor(blk)
                cur.setPosition(blk.position() + int(a))
                cur.setPosition(blk.position() + int(b),
                                QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(color or HL_COLOR))
                cur.mergeCharFormat(fmt)
        finally:
            self._loading = False

    def omit_tables(self) -> bool:
        return self.cb_omit.isChecked()

    def reload(self):
        """표 옵션이 바뀌면 앱에 다시 뽑아 달라고 한다."""
        self.lineFocused.emit(-1, None)          # 앱이 이 신호로 재적재를 알아챈다

    def rows(self) -> list:
        return list(self._rows)

    def current_line(self) -> int:
        return self.edit.textCursor().blockNumber()

    # ---------------- 상호작용 ----------------
    def _on_cursor(self):
        """줄을 고르면 **본문 뷰어의 그 자리를 강조**한다(사용자 요청 260908)."""
        if self._loading:
            return
        i = self.current_line()
        if 0 <= i < len(self._rows):
            rc = self._rows[i].get("rect")
            self.lineFocused.emit(self._page, [rc] if rc else [])

    def _on_text_changed(self):
        if self._loading:
            return
        i = self.current_line()
        if not (0 <= i < len(self._rows)):
            return
        blk = self.edit.document().findBlockByNumber(i)
        if not blk.isValid():
            return
        txt = blk.text()
        if txt != self._rows[i].get("text"):
            orig = self._rows[i].get("orig") or self._rows[i].get("text") or ""
            self._rows[i].setdefault("orig", orig)
            self._rows[i]["text"] = txt
            self.lineEdited.emit(self._page, i, txt, orig)
            rc = self._rows[i].get("rect")
            self.lineFocused.emit(self._page, [rc] if rc else [])

    def _on_highlight(self):
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            self.info.setText("칠할 글을 먼저 고르세요.")
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(HL_COLOR))
        cur.mergeCharFormat(fmt)
        # 260908-3(SOT §6): 저장해 둬야 쪽을 넘겼다 와도 남는다
        blk = self.edit.document().findBlock(cur.selectionStart())
        if blk.isValid():
            a = cur.selectionStart() - blk.position()
            b = cur.selectionEnd() - blk.position()
            self.highlightAdded.emit(self._page, blk.blockNumber(),
                                     int(a), int(b), HL_COLOR)
        self.info.setText("칠했습니다. [책갈피로] 를 누르면 칠한 곳으로 책갈피를 만듭니다.")

    def highlighted_lines(self) -> list:
        """칠해진 줄 → [{"line": i, "text": 칠한 글, "style": …}] (SOT §6)."""
        out = []
        doc = self.edit.document()
        for i in range(doc.blockCount()):
            blk = doc.findBlockByNumber(i)
            if not blk.isValid():
                continue
            picked = []
            for it in blk.textFormats():
                bg = it.format.background()
                if bg.style() != Qt.BrushStyle.NoBrush and bg.color().alpha() > 0 \
                        and bg.color() != QColor(Qt.GlobalColor.white):
                    picked.append(blk.text()[it.start:it.start + it.length])
            if picked:
                style = (self._rows[i].get("style") if i < len(self._rows) else "body")
                out.append({"line": i, "text": "".join(picked).strip(), "style": style})
        return out

    def _on_make_bookmarks(self):
        picks = self.highlighted_lines()
        if not picks:
            self.info.setText("먼저 [하이라이트] 로 글을 칠하세요.")
            return
        items = []
        for p in picks:
            title = (p["text"] or "").strip()[:40]
            if not title:
                continue
            items.append({"page": self._page + 1, "title": title,
                          "level": 1 if p["style"] == "title" else 2})
        if items:
            self.bookmarkFromHighlight.emit(items)
            self.info.setText(f"책갈피 {len(items)}개를 만들었습니다 — 책갈피창에서 💾 저장하세요.")
