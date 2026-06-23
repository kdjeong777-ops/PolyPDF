"""PDF 번역 PoC 다이얼로그 (P0) — 텍스트 1청크를 Claude 로 번역·토큰/비용 확인.

SOT: `PDF 번역·요약 작업 계획서.md` (P0). 본격 파이프라인(추출·용어집·문서조립)은 P1~.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QTextBrowser, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
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
    done = pyqtSignal(str, list, str, str, list)   # full_text, dbg, docx_path, pdf_path, glossary
    stage = pyqtSignal(str)                   # 진행 단계 안내

    def __init__(self, key, text, model, auth="api", source_path=""):
        super().__init__()
        self._key, self._text, self._model, self._auth = key, text, model, auth
        self._source_path = source_path or ""

    def run(self):
        # P4c/P4d: 원본 파일이 있으면 그림·표를 먼저 추출하고, 그 영역을 본문에서 제외해
        # 다시 정제 추출(표/캡션이 본문 번역에 중복 유입되는 문제 방지).
        figs, tabs, equations = [], [], []
        folder = name = ""
        if self._source_path:
            folder = os.path.dirname(os.path.abspath(self._source_path))
            name = os.path.splitext(os.path.basename(self._source_path))[0]
            figs, tabs = self._build_assets(folder, name)
            try:
                from ..study import pdf_assets as pa
                from ..study import pdf_extract as px
                equations = pa.extract_equations(self._source_path,
                                                 os.path.join(folder, name + "_assets"))
                regions = pa.regions_by_page(figs, tabs)
                placeholders = pa.equation_placeholders(equations)
                clean = px.extract_clean_text(self._source_path, max_chars=200000,
                                              exclude_regions=regions, placeholders=placeholders)
                if clean:
                    self._text = clean
            except Exception:
                pass
        # P2/P2b: 사전 1순위 + Claude 자동 제안 용어집(스레드 전용 DictStore)
        self.stage.emit("용어집 생성 중…")
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
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        self.stage.emit(f"용어집 {len(glossary)}개 적용 · 번역 중…")
        translation, dbg = tapi.translate_text_debug(
            self._key, self._text, model=self._model, glossary=glossary, auth=self._auth)
        if not translation:
            self.done.emit("", dbg, "", "", glossary)
            return
        # P3: 요약 + 서지(APA) → 산출물 순서로 조립(서지 → 요약 → 전문)
        self.stage.emit("요약·서지 생성 중…")
        from ..study import summarize as sm
        citation, _c = sm.citation_apa_debug(self._key, self._text[:2500],
                                             self._model, self._auth)
        summary, _s = sm.summarize_debug(self._key, self._text, self._model, self._auth)
        full = sm.assemble(citation, summary, translation)
        # P4: Word/PDF 산출물(논문 폴더, 책갈피) — 그림/표는 run() 앞부분에서 추출 완료
        docx_path = pdf_path = ""
        if self._source_path:
            try:
                self.stage.emit("Word/PDF 문서 생성 중…")
                from ..study import export_translation as ex
                docx_path, pdf_path, _d = ex.save_translation_doc(
                    folder, name, citation=citation, summary=summary,
                    translation=translation, glossary=glossary,
                    figures=figs, tables=tabs, equations=equations)
            except Exception:
                docx_path = pdf_path = ""
        self.done.emit(full, dbg, docx_path, pdf_path, glossary)

    def _build_assets(self, folder, name):
        """(figures, tables) — 그림/표 추출 + 캡션 일괄 번역 + 표 비전 그리드 재구성(최대 12)."""
        try:
            from ..study import pdf_assets as pa
            from ..study import summarize as sm
            self.stage.emit("그림·표 추출·재검토·누락 보완 중…")
            adir = os.path.join(folder, name + "_assets")
            figs, tabs, rep = pa.extract_assets_report(self._source_path, adir)
            miss = ("· 누락 " + ",".join(rep["missing"])) if rep.get("missing") else "· 누락 없음"
            self.stage.emit(f"그림 {len(figs)}·표 {len(tabs)} 추출(선언 {rep['declared']}) {miss}")
            if not figs and not tabs:
                return [], []
            caps = [f.get("caption", "") for f in figs] + [t.get("caption", "") for t in tabs]
            self.stage.emit("그림·표 캡션 번역 중…")
            ko = sm.translate_captions(self._key, caps, self._model, self._auth)
            for i, f in enumerate(figs):
                f["caption_ko"] = ko[i] if i < len(ko) else ""
            for j, t in enumerate(tabs):
                t["caption_ko"] = ko[len(figs) + j] if len(figs) + j < len(ko) else ""
            # 표는 비전으로 행/열 구조 그대로 한국어 그리드 재구성(연속 표는 여러 이미지 병합)
            for n, t in enumerate(tabs[:12]):
                self.stage.emit(f"표 번역 중… ({n + 1}/{min(len(tabs), 12)})")
                rows_all = []
                for k, im in enumerate(t.get("images") or [t.get("image")]):
                    if not (im and os.path.exists(im)):
                        continue
                    rows, _ = tapi.translate_table_image_debug(
                        self._key, im, model=self._model, auth=self._auth)
                    if k > 0 and rows and rows_all:
                        rows = rows[1:]              # 연속 페이지 머리글 반복 제거
                    rows_all.extend(rows)
                t["rows_ko"] = rows_all
            return figs, tabs
        except Exception:
            return [], []


class TranslatePocDialog(QDialog):
    def __init__(self, prefs: dict, parent=None, initial_text: str = "", glossary=None,
                 source_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("PDF 번역 (베타·Claude)")
        self.resize(820, 640)
        self._prefs = prefs or {}
        self._source_path = source_path or ""
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

        # ----- 용어집 교정(잘못된 번역 → 사용자 사전에 저장 → 재번역) -----
        self.gloss_label = QLabel("용어집 (잘못 번역된 한글 뜻을 고친 뒤 ‘사용자 사전에 저장’ → "
                                  "이후 모든 번역에 반영. ‘이 문서 재번역’으로 다시 번역)")
        self.gloss_label.setWordWrap(True)
        self.gloss_label.setVisible(False)
        v.addWidget(self.gloss_label)
        self.gloss = QTableWidget(0, 3)
        self.gloss.setHorizontalHeaderLabels(["원어(EN)", "번역(KO) — 수정 가능", "출처"])
        self.gloss.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.gloss.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.gloss.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.gloss.setMaximumHeight(200)
        self.gloss.setVisible(False)
        v.addWidget(self.gloss)
        grow = QHBoxLayout()
        self.btn_gloss_save = QPushButton("✔ 사용자 사전에 저장")
        self.btn_gloss_save.setToolTip("수정한 한글 뜻을 사용자 사전(User, 최우선)에 저장 — 모든 PDF·번역에 적용")
        self.btn_gloss_save.clicked.connect(self._save_glossary_corrections)
        self.btn_retrans = QPushButton("↻ 이 문서 재번역")
        self.btn_retrans.setToolTip("저장한 용어 교정으로 본문을 다시 번역(비용 발생)")
        self.btn_retrans.clicked.connect(self._retranslate)
        grow.addWidget(self.btn_gloss_save)
        grow.addWidget(self.btn_retrans)
        grow.addStretch(1)
        v.addLayout(grow)
        self.btn_gloss_save.setVisible(False)
        self.btn_retrans.setVisible(False)

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
        w = _TransWorker(self._key, text, self._model, self._auth, self._source_path)
        self._workers.append(w)
        w.stage.connect(self.info.setText)
        w.done.connect(self._on_trans)
        w.finished.connect(lambda w=w: self._drop(w))
        w.start()

    def _on_trans(self, out, dbg, docx_path="", pdf_path="", glossary=None):
        self.btn_run.setEnabled(True)
        self._glossary = list(glossary or [])
        self._fill_glossary_table(self._glossary)
        if not out:
            self.info.setText("번역 실패: " + (dbg[-1] if dbg else ""))
            return
        self.out.setPlainText(out)
        saved = ""
        if pdf_path:
            saved = " · 저장: " + os.path.basename(pdf_path) + " (+docx)"
        elif docx_path:
            saved = " · 저장: " + os.path.basename(docx_path) + " (PDF 변환 실패 — Word 필요)"
        self.info.setText("완료" + saved)
        # 저장된 PDF 를 뷰어로 열기
        if pdf_path:
            try:
                par = self.parent()
                if par is not None and hasattr(par, "open_pdf"):
                    par.open_pdf(Path(pdf_path))
            except Exception:
                pass

    # ----- 용어집 교정 -----
    def _fill_glossary_table(self, glossary):
        gl = [g for g in (glossary or []) if g.get("en") and g.get("ko")]
        show = bool(gl)
        for wdg in (self.gloss_label, self.gloss, self.btn_gloss_save, self.btn_retrans):
            wdg.setVisible(show)
        self.gloss.setRowCount(len(gl))
        for i, g in enumerate(gl):
            en = QTableWidgetItem(g.get("en", ""))
            en.setFlags(en.flags() & ~Qt.ItemFlag.ItemIsEditable)        # EN 읽기전용
            ko = QTableWidgetItem(g.get("ko", ""))                       # KO 편집 가능
            src = QTableWidgetItem(g.get("source", ""))
            src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.gloss.setItem(i, 0, en)
            self.gloss.setItem(i, 1, ko)
            self.gloss.setItem(i, 2, src)
            self.gloss.item(i, 1).setData(Qt.ItemDataRole.UserRole, g.get("ko", ""))  # 원래 값

    def _save_glossary_corrections(self):
        """KO 가 바뀐 행만 사용자 사전(User)에 저장(최우선 → 모든 번역에 적용)."""
        changed = []
        for i in range(self.gloss.rowCount()):
            en = self.gloss.item(i, 0).text().strip()
            ko_item = self.gloss.item(i, 1)
            ko = ko_item.text().strip()
            orig = (ko_item.data(Qt.ItemDataRole.UserRole) or "")
            if en and ko and ko != orig:
                changed.append((en, ko))
        if not changed:
            self.info.setText("변경된 용어가 없습니다. 한글 뜻을 고친 뒤 다시 저장하세요.")
            return
        try:
            from ..study.dict_store import DictStore
            store = DictStore()
            for en, ko in changed:
                store.upsert_user_term(en, ko)
            store.close()
        except Exception as e:
            self.info.setText(f"사용자 사전 저장 실패: {type(e).__name__}: {str(e)[:60]}")
            return
        for i in range(self.gloss.rowCount()):       # 저장본을 새 원래값으로
            it = self.gloss.item(i, 1)
            it.setData(Qt.ItemDataRole.UserRole, it.text().strip())
        self.info.setText(f"사용자 사전에 {len(changed)}개 용어 저장됨 — 이후 모든 번역에 적용. "
                          f"이 문서에 반영하려면 ‘이 문서 재번역’.")

    def _retranslate(self):
        """저장한 용어 교정으로 본문을 다시 번역(워커가 사전을 새로 읽음)."""
        if not self.ed.toPlainText().strip():
            self.info.setText("재번역할 본문이 없습니다.")
            return
        self._save_glossary_corrections()            # 미저장 수정도 먼저 반영
        self._run()

    def _drop(self, w):
        try:
            if w in self._workers:
                self._workers.remove(w)
        except Exception:
            pass
