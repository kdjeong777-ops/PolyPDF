"""번역 용어집 교정 다이얼로그 — 오역된 한글 대역을 고쳐 사용자 사전에 저장.

SOT: `PDF 번역·요약 작업 계획서.md`.
- 번역 방식(단일/배치)·문서를 닫았는지와 무관하게, 그 PDF 의 번역 용어집(사이드카
  `{이름}_용어집.json`)을 불러와 **편집 가능한 표**로 보여준다(원어 EN 편집 / 번역 KO 편집 / 출처).
- 행을 고르면 **본문에서 그 용어가 쓰인 문장(예문)** 을 아래에 보여줘 수정 시 맥락 참조.
- 영어(EN)도 수정 가능 — 한 단어가 아니라 **다른 단어와 묶인 용어**(예: 'asphalt binder')로
  바로잡을 수 있게.
- [✔ 사용자 사전에 저장]: 변경된 행만 `DictStore.upsert_user_term`(User·최우선·중복 갱신).
- [↻ 이 문서 재번역]: 교정 저장 후 그 PDF 를 다시 번역(부모의 번역 진입점 호출).
"""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QTextBrowser,
)


class GlossaryEditDialog(QDialog):
    def __init__(self, glossary, prefs=None, source_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("번역 용어집 교정")
        self.resize(720, 600)
        self._prefs = prefs or {}
        self._source_path = source_path or ""
        self._glossary = [g for g in (glossary or []) if g.get("en") and g.get("ko")]
        self._body = ""          # 예문 검색용 본문(지연 로드)
        self._body_loaded = False

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "잘못 번역된 <b>한글 뜻</b>을 고치세요. 한 단어가 아니라 다른 단어와 묶인 용어면 "
            "<b>원어(EN)</b>도 고칠 수 있습니다. <b>[사용자 사전에 저장]</b> 시 최우선으로 "
            "이후 <b>모든 PDF·번역</b>에 반영됩니다. 행을 누르면 아래에 <b>본문 예문</b>이 보입니다."))

        self.tbl = QTableWidget(len(self._glossary), 3)
        self.tbl.setHorizontalHeaderLabels(["원어(EN) — 수정 가능", "번역(KO) — 수정 가능", "출처"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for i, g in enumerate(self._glossary):
            en = QTableWidgetItem(g.get("en", ""))
            en.setData(Qt.ItemDataRole.UserRole, g.get("en", ""))      # 원래 EN
            ko = QTableWidgetItem(g.get("ko", ""))
            ko.setData(Qt.ItemDataRole.UserRole, g.get("ko", ""))      # 원래 KO
            src = QTableWidgetItem(g.get("source", ""))
            src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl.setItem(i, 0, en)
            self.tbl.setItem(i, 1, ko)
            self.tbl.setItem(i, 2, src)
        self.tbl.currentCellChanged.connect(lambda *_: self._show_examples())
        v.addWidget(self.tbl, 1)

        v.addWidget(QLabel("본문 예문 (선택한 용어가 쓰인 문장):"))
        self.examples = QTextBrowser()
        self.examples.setMaximumHeight(150)
        self.examples.setPlaceholderText("표에서 용어를 선택하면 본문에서 그 용어가 쓰인 문장을 보여줍니다.")
        v.addWidget(self.examples)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#555;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        row = QHBoxLayout()
        self.btn_save = QPushButton("✔ 사용자 사전에 저장")
        self.btn_save.clicked.connect(self._save)
        self.btn_retrans = QPushButton("↻ 이 문서 재번역")
        self.btn_retrans.setEnabled(bool(self._source_path))
        self.btn_retrans.clicked.connect(self._retranslate)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_retrans)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        v.addLayout(row)

        if not self._glossary:
            self.info.setText("이 PDF 의 번역 용어집을 찾지 못했습니다. 먼저 번역을 실행하세요.")
            self.btn_save.setEnabled(False)

    # ----- 본문 예문 -----
    def _ensure_body(self):
        if self._body_loaded:
            return
        self._body_loaded = True
        try:
            import os
            if self._source_path and os.path.exists(self._source_path):
                from ..study import pdf_extract as px
                self._body = px.extract_clean_text(self._source_path, max_chars=200000) or ""
        except Exception:
            self._body = ""

    def _show_examples(self):
        r = self.tbl.currentRow()
        if r < 0 or self.tbl.item(r, 0) is None:
            return
        term = self.tbl.item(r, 0).text().strip()
        if not term:
            self.examples.setPlainText("")
            return
        self._ensure_body()
        if not self._body:
            self.examples.setPlainText("(본문을 불러올 수 없어 예문을 표시할 수 없습니다.)")
            return
        sents = re.split(r"(?<=[.!?])\s+", self._body)
        rx = re.compile(re.escape(term), re.I)
        hits = [s.strip() for s in sents if rx.search(s)]
        if not hits:
            self.examples.setPlainText(f"본문에서 '{term}' 이(가) 쓰인 문장을 찾지 못했습니다.")
            return
        html = []
        for s in hits[:5]:
            s = (s[:400] + "…") if len(s) > 400 else s
            esc = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            esc = rx.sub(lambda m: f"<b style='color:#1456c4'>{m.group(0)}</b>", esc)
            html.append(f"<p style='margin:3px 0'>• {esc}</p>")
        more = f"<p style='color:#888'>… 외 {len(hits) - 5}문장</p>" if len(hits) > 5 else ""
        self.examples.setHtml("".join(html) + more)

    # ----- 저장 / 재번역 -----
    def _changed_terms(self):
        """변경된 행 → (row, en, ko). EN 또는 KO 가 원래값과 다르면 변경으로 본다."""
        out = []
        for i in range(self.tbl.rowCount()):
            en_it, ko_it = self.tbl.item(i, 0), self.tbl.item(i, 1)
            en, ko = en_it.text().strip(), ko_it.text().strip()
            oen = en_it.data(Qt.ItemDataRole.UserRole) or ""
            oko = ko_it.data(Qt.ItemDataRole.UserRole) or ""
            if en and ko and (en != oen or ko != oko):
                out.append((i, en, ko))
        return out

    def _save(self) -> bool:
        changed = self._changed_terms()
        if not changed:
            self.info.setText("변경된 용어가 없습니다. 원어(EN)나 한글 뜻을 고친 뒤 다시 저장하세요.")
            return False
        try:
            from ..study.dict_store import DictStore
            store = DictStore()
            for _i, en, ko in changed:
                store.upsert_user_term(en, ko)
            store.close()
        except Exception as e:
            self.info.setText(f"사용자 사전 저장 실패: {type(e).__name__}: {str(e)[:60]}")
            return False
        for i, en, ko in changed:        # 저장본을 새 원래값으로
            self.tbl.item(i, 0).setData(Qt.ItemDataRole.UserRole, en)
            self.tbl.item(i, 1).setData(Qt.ItemDataRole.UserRole, ko)
        self.info.setText(f"사용자 사전에 {len(changed)}개 용어 저장됨 — 이후 모든 번역에 적용.")
        return True

    def _retranslate(self):
        self._save()
        par = self.parent()
        if not (self._source_path and par is not None
                and hasattr(par, "_action_translate_files")):
            self.info.setText("재번역 진입점을 찾지 못했습니다. 저장만 완료했습니다.")
            return
        if QMessageBox.question(
                self, "재번역", "교정된 용어집으로 이 문서를 다시 번역합니다. 계속할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.accept()
        par._action_translate_files([self._source_path])   # PDF번역 창에 우측 담아 열기
