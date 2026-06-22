"""여러 PDF 번역 — 좌(전체 파일)/우(번역 대상) 2리스트 (병합 다이얼로그와 유사 구조).

SOT: `PDF 번역·요약 작업 계획서.md`.
- 좌: 책갈피창 전체 PDF. 다중 선택 → [→]로 우측 등록.
- 우: 번역 대상(순서 = 처리 순서). ▲▼ 이동·삭제, 외부 PDF 드래그앤드롭 추가.
- '번역 실행' → 순서대로 각 파일 본문을 추출·번역해 원본 옆에 `{이름}_번역.txt` 저장(P0 간이).
  (요약·Word/PDF·책갈피·용어집 산출은 후속 P1~P4 에서 이 자리에 연결.)
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView, QPlainTextEdit, QMessageBox,
)

from ..study import translate_api as tapi


def _has_pdf_urls(mime) -> bool:
    return mime.hasUrls() and any(
        u.toLocalFile().lower().endswith(".pdf") for u in mime.urls())


class _BatchWorker(QThread):
    progress = pyqtSignal(int, int, str)   # idx, total, message
    one_done = pyqtSignal(str, bool, str)  # path, ok, detail
    all_done = pyqtSignal(int, int)        # ok_count, total

    def __init__(self, files, key, model, auth):
        super().__init__()
        self._files = list(files)
        self._key, self._model, self._auth = key, model, auth
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self._files)
        ok = 0
        # P2: 워커 스레드 전용 DictStore(용어집 1순위) — 메인 연결과 분리
        store = None
        try:
            from ..study.dict_store import DictStore
            store = DictStore()
        except Exception:
            store = None
        for i, p in enumerate(self._files, 1):
            if self._stop:
                break
            name = Path(p).name
            self.progress.emit(i, total, f"[{i}/{total}] {name} 추출·번역 중…")
            # P1: 머리말/꼬리말 제거·본문 연결된 정제 본문(실패 시 원시 추출 폴백)
            from ..study import pdf_extract as px
            text = px.extract_clean_text(p, max_chars=200000) or tapi.extract_pdf_text(p, max_chars=200000)
            if not text:
                self.one_done.emit(str(p), False, "본문 텍스트 추출 실패(스캔본일 수 있음)")
                continue
            glossary = []
            try:
                from ..study import glossary_build as gb
                glossary = gb.build_glossary_with_auto(
                    text, store, self._key, self._model, self._auth)
            except Exception:
                glossary = []
            out, dbg = tapi.translate_text_debug(
                self._key, text, model=self._model, auth=self._auth, glossary=glossary)
            if not out:
                self.one_done.emit(str(p), False, (dbg[-1] if dbg else "번역 실패"))
                continue
            # P3: 요약 + 서지(APA)
            translation = out
            citation = summary = ""
            try:
                from ..study import summarize as sm
                citation, _c = sm.citation_apa_debug(self._key, text[:2500], self._model, self._auth)
                summary, _s = sm.summarize_debug(self._key, text, self._model, self._auth)
            except Exception:
                pass
            # P4: Word/PDF 산출물(서지→요약→전문→용어집, 책갈피)
            try:
                from ..study import export_translation as ex
                docx_path, pdf_path, _d = ex.save_translation_doc(
                    str(Path(p).parent), Path(p).stem,
                    citation=citation, summary=summary, translation=translation,
                    glossary=glossary)
                ok += 1
                self.one_done.emit(str(p), True, f"저장: {Path(pdf_path or docx_path).name}")
            except Exception as e:
                self.one_done.emit(str(p), False, f"저장 실패: {type(e).__name__}: {str(e)[:60]}")
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        self.all_done.emit(ok, total)


class TranslateFilesDialog(QDialog):
    _DATA = Qt.ItemDataRole.UserRole

    def __init__(self, all_files: list, preselected: list = None,
                 prefs: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("여러 PDF 번역")
        self.setMinimumSize(760, 520)
        self.setAcceptDrops(True)
        self._prefs = prefs or {}
        self._auth = str(self._prefs.get("translate_auth", "api")).strip()
        self._key = str(self._prefs.get("anthropic_api_key", "")).strip()
        self._model = str(self._prefs.get("translate_model", tapi.DEFAULT_MODEL))
        self._worker = None

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "왼쪽에서 파일을 골라 <b>→</b> 로 오른쪽(번역 대상)에 등록하세요. "
            "오른쪽 <b>위에서부터</b> 순서대로 번역합니다. 외부 PDF는 끌어다 놓기로 추가."))

        body = QHBoxLayout()
        # 좌: 전체 파일
        lcol = QVBoxLayout()
        lcol.addWidget(QLabel("책갈피창 전체 파일"))
        self.left = QListWidget()
        self.left.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for p in (all_files or []):
            if not str(p).lower().endswith(".pdf"):
                continue
            it = QListWidgetItem(Path(p).stem)
            it.setData(self._DATA, str(p))
            it.setToolTip(str(p))
            self.left.addItem(it)
        lcol.addWidget(self.left, 1)
        body.addLayout(lcol, 1)

        # 가운데: → 버튼
        mid = QVBoxLayout()
        mid.addStretch(1)
        btn_add = QPushButton("→")
        btn_add.setToolTip("선택 파일을 오른쪽(번역 대상)으로")
        btn_add.setFixedWidth(44)
        btn_add.clicked.connect(self._move_selected)
        mid.addWidget(btn_add)
        mid.addStretch(1)
        body.addLayout(mid)

        # 우: 번역 대상 + ▲▼·삭제
        rcol = QVBoxLayout()
        rcol.addWidget(QLabel("번역 대상 (위→아래 순서)"))
        rlist_row = QHBoxLayout()
        self.right = QListWidget()
        self.right.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.right.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.right.setDefaultDropAction(Qt.DropAction.MoveAction)
        rlist_row.addWidget(self.right, 1)
        rbtncol = QVBoxLayout()
        rbtncol.addStretch(1)
        btn_up = QPushButton("▲"); btn_up.setFixedWidth(40)
        btn_dn = QPushButton("▼"); btn_dn.setFixedWidth(40)
        btn_up.clicked.connect(lambda: self._move_right(-1))
        btn_dn.clicked.connect(lambda: self._move_right(+1))
        rbtncol.addWidget(btn_up); rbtncol.addWidget(btn_dn)
        rbtncol.addSpacing(18)
        btn_del = QPushButton("삭제"); btn_del.setFixedWidth(40)
        btn_del.clicked.connect(self._delete_right)
        rbtncol.addWidget(btn_del)
        rbtncol.addStretch(1)
        rlist_row.addLayout(rbtncol)
        rcol.addLayout(rlist_row, 1)
        body.addLayout(rcol, 1)
        v.addLayout(body, 1)

        for p in (preselected or []):
            self._add_right(p)

        # 실행 행
        run_row = QHBoxLayout()
        self.btn_run = QPushButton("번역 실행")
        self.btn_run.clicked.connect(self._run)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.reject)
        run_row.addWidget(self.btn_run)
        run_row.addStretch(1)
        run_row.addWidget(self.btn_close)
        v.addLayout(run_row)

        self.info = QLabel("각 PDF 옆에 '{이름}_번역.docx/.pdf' 로 저장됩니다 "
                           "(서지→요약→전문→용어집, PDF 책갈피).")
        self.info.setStyleSheet("color:#555;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        v.addWidget(self.log)

        # 드롭 오버레이
        self._overlay = QLabel("📄 여기에 PDF 를 끌어다 놓으세요 (번역 목록에 추가)", self)
        self._overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay.setStyleSheet(
            "QLabel{background:rgba(42,125,225,0.16);border:3px dashed #2a7de1;"
            "border-radius:12px;color:#1565c0;font-size:17px;font-weight:bold;}")
        self._overlay.hide()

    # ── 목록 조작 ──────────────────────────────────────────────
    def _has_right(self, path: str) -> bool:
        rp = str(Path(path).resolve()).lower()
        for i in range(self.right.count()):
            try:
                if str(Path(self.right.item(i).data(self._DATA)).resolve()).lower() == rp:
                    return True
            except Exception:
                pass
        return False

    def _add_right(self, path: str):
        if not path or not str(path).lower().endswith(".pdf") or self._has_right(path):
            return
        it = QListWidgetItem(Path(path).stem)
        it.setData(self._DATA, str(path))
        it.setToolTip(str(path))
        self.right.addItem(it)

    def _move_selected(self):
        for it in self.left.selectedItems():
            self._add_right(it.data(self._DATA))

    def _move_right(self, direction: int):
        rows = sorted(self.right.row(it) for it in self.right.selectedItems())
        if not rows:
            return
        if direction < 0:
            if rows[0] <= 0:
                return
            for r in rows:
                it = self.right.takeItem(r); self.right.insertItem(r - 1, it); it.setSelected(True)
        else:
            if rows[-1] >= self.right.count() - 1:
                return
            for r in reversed(rows):
                it = self.right.takeItem(r); self.right.insertItem(r + 1, it); it.setSelected(True)

    def _delete_right(self):
        for it in self.right.selectedItems():
            self.right.takeItem(self.right.row(it))

    def result_files(self) -> list:
        return [self.right.item(i).data(self._DATA) for i in range(self.right.count())]

    # ── 드래그앤드롭(외부 PDF) ─────────────────────────────────
    def _show_overlay(self, on):
        if on:
            self._overlay.setGeometry(self.rect().adjusted(8, 8, -8, -8))
            self._overlay.raise_(); self._overlay.show()
        else:
            self._overlay.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect().adjusted(8, 8, -8, -8))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction(); self._show_overlay(_has_pdf_urls(e.mimeData()))

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._show_overlay(False)

    def dropEvent(self, e):
        self._show_overlay(False)
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and p.lower().endswith(".pdf"):
                self._add_right(p)
        e.acceptProposedAction()

    # ── 실행 ───────────────────────────────────────────────────
    def _run(self):
        files = self.result_files()
        if not files:
            self.info.setText("번역할 파일을 오른쪽에 추가하세요.")
            return
        if not tapi.available():
            self.info.setText("번역 모듈(anthropic)이 없습니다. 최신 배포본을 사용하세요.")
            return
        if self._auth != "login" and not self._key:
            self.info.setText("설정 → '번역(Claude)' 에서 API 키를 입력하거나 "
                              "인증 방식을 'Claude 로그인'으로 바꾸세요.")
            return
        if not bool(self._prefs.get("translate_consent", False)):
            if QMessageBox.question(
                    self, "외부 전송 동의",
                    f"{len(files)}개 파일 본문이 Anthropic(Claude) 서버로 전송됩니다.\n계속할까요?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.btn_run.setEnabled(False)
        self.log.clear()
        self._worker = _BatchWorker(files, self._key, self._model, self._auth)
        self._worker.progress.connect(lambda i, n, m: self.info.setText(m))
        self._worker.one_done.connect(
            lambda p, ok, d: self.log.appendPlainText(("✓ " if ok else "✗ ") + Path(p).name + " — " + d))
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_all_done(self, ok, total):
        self.btn_run.setEnabled(True)
        self.info.setText(f"완료: {ok}/{total} 개 번역 저장 (각 PDF 옆 '_번역.docx/.pdf').")

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        super().reject()
