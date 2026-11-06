# -*- coding: utf-8 -*-
"""261019-1(사용자 지시): 오래 걸리는 작업 창 + 저장하지 않은 OCR·단어장(보류 저장소).

작업 창 (응답성 SOT §4.6 · 디자인 SOT §2.18)
  - 상태 표시줄의 진행 바나 왼쪽 진행 메시지를 누르면 **작업** 창이 열린다(작업이 있을 때만, 261105-25) — 지금 도는 작업과
    [중단]·[취소], 맨 아래 [계속](기본 — 창만 닫는다). 중단 = 다음 안전한 지점(쪽 하나·파일 하나가 끝난 뒤)에서 멈추고
    여기까지 한 것은 남긴다. 취소 = 멈추고 그 파일의 저장 안 한 결과를 버린다(버림 함수가 있는 작업만). 일시정지는 두지 않는다
    (멈춘 채 파일을 잡고 있으면 이름 변경·저장·덮어쓰기와 부딪힌다 — 사용자 결정 261019).
  - 이어하기: 읽은 OCR 쪽은 보류 저장소에 남아, 같은 작업을 다시 시작하면 그 쪽은 건너뛴다(이 실행 동안).
  - 작업은 `job_add(id, 이름, 중단 함수, 버림 함수)` → `job_progress(id, 글)` → `job_done(id)` 로만 알린다.
    버림은 `job_done` 때(워커가 끝난 뒤) 부르고, `job_done` 은 취소됐으면 True — 부른 쪽은 끝 처리를 건너뛴다.

저장하지 않은 OCR·단어장 (단어학습 SOT §14.21)
  - OCR·단어장 결과는 [저장] 전까지 보류 저장소에만 있다(`study_store.enable_pending`).
  - 확정: 책갈피창 [저장](그 파일) · 상태 표시줄 '저장 안 한 OCR' 단추 · 종료 때 묻는 창.
  - 저장하지 않고 끝내면 버린다(다음 실행 때 남은 보류 파일도 지운다).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QToolButton, QVBoxLayout, QWidget)

from viewer.i18n import tr


class _ClickFilter(QObject):
    """누르면 작업 창. `owner` 를 주면 작업 창에 오른 작업이 있을 때만(상태 표시줄 진행 메시지 — 261105-25)."""

    def __init__(self, fn, owner=None):
        super().__init__()
        self._fn = fn
        self._owner = owner

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            if self._owner is not None and not self._owner._jobs:
                return False
            self._fn()
            return True
        return False


class JobsDialog(QDialog):
    """지금 도는 작업 목록 + [중단]·[취소], 맨 아래 [계속](기본). 모달이 아니다 — 열어 둔 채 다른 일을 해도 된다."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setWindowTitle(tr("작업"))
        self.setMinimumWidth(460)
        self._lay = QVBoxLayout(self)
        self._rows = QVBoxLayout()
        self._lay.addLayout(self._rows)
        self._empty = QLabel(tr("진행 중인 작업이 없습니다."))
        self._lay.addWidget(self._empty)
        hint = QLabel(tr("<small>[계속] 은 창만 닫고 작업은 계속합니다. [중단] 은 지금 쪽(또는 파일)을 마친 뒤 멈추고 "
                         "여기까지 한 것은 남깁니다 — 같은 작업을 다시 시작하면 이어서 합니다. "
                         "[취소] 는 멈추고 그 파일의 저장하지 않은 결과를 버립니다.</small>"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        self._lay.addWidget(hint)
        bb = QHBoxLayout(); bb.addStretch(1)
        # 261105-25(사용자 결정): 기본 단추는 [계속] — Enter 가 되돌릴 수 없는 [취소] 를 누르지 않게
        self.btn_continue = QPushButton(tr("계속"))
        self.btn_continue.setObjectName("job_continue")
        self.btn_continue.setDefault(True)
        self.btn_continue.clicked.connect(self.close)
        bb.addWidget(self.btn_continue)
        self._lay.addLayout(bb)
        self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.btn_continue.setFocus()

    def refresh(self):
        while self._rows.count():
            it = self._rows.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        jobs = self._owner._jobs_list()
        self._empty.setVisible(not jobs)
        for jid, j in jobs:
            row = QWidget()
            h = QHBoxLayout(row); h.setContentsMargins(0, 2, 0, 2)
            lab = QLabel(f"<b>{j['label']}</b><br><small>{j.get('msg') or ''}</small>")
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            busy = j.get("stopping")
            btn = QPushButton(tr("멈추는 중…") if busy == "stop" else tr("중단"))
            btn.setAutoDefault(False)
            btn.setEnabled(bool(j.get("cancel")) and not busy)
            btn.clicked.connect(lambda _c=False, k=jid: self._owner.job_stop(k))
            btn.setObjectName(f"job_stop_{jid}")
            self._fit(btn, tr("중단"), tr("멈추는 중…"))
            h.addWidget(btn)
            if j.get("discard"):
                bc = QPushButton(tr("취소하는 중…") if busy == "discard" else tr("취소"))
                bc.setAutoDefault(False)
                bc.setEnabled(bool(j.get("cancel")) and not busy)
                bc.setToolTip(tr("멈추고 이 파일의 저장하지 않은 결과를 버립니다"))
                bc.clicked.connect(lambda _c=False, k=jid: self._owner.job_cancel(k))
                bc.setObjectName(f"job_cancel_{jid}")
                self._fit(bc, tr("취소"), tr("취소하는 중…"))
                h.addWidget(bc)
            self._rows.addWidget(row)

    @staticmethod
    def _fit(btn, *labels):
        """단추 폭을 가장 긴 글(누른 뒤의 '…하는 중' 포함)에 맞춘다 — 눌러도 글이 잘리지 않고 줄이 흔들리지 않게."""
        fm = btn.fontMetrics()
        btn.setMinimumWidth(max(fm.horizontalAdvance(t) for t in labels) + 24)


class JobsMixin:
    # ── 작업 창 ────────────────────────────────────────────────────
    def _jobs_init(self):
        self._jobs = {}
        self._jobs_dlg = None
        self._jobs_seq = 0
        self._jobs_sync_bar()                # 처음에는 작업이 없다 — 막대 숨김
        try:
            self.progress.setToolTip(tr("눌러서 진행 중인 작업 보기·중단·취소"))
            self.progress.setCursor(Qt.CursorShape.PointingHandCursor)
            self._jobs_click = _ClickFilter(self.open_jobs_window)
            self.progress.installEventFilter(self._jobs_click)
            # 261105-25(사용자 지시): 왼쪽 진행 메시지(상태 표시줄이 그리는 글·개수 칸)를 눌러도 — 작업이 있을 때만
            self._jobs_msg_click = _ClickFilter(self.open_jobs_window, owner=self)
            self.status.installEventFilter(self._jobs_msg_click)
        except Exception:
            pass
        # 저장 안 한 OCR·단어장 단추(있을 때만 보인다)
        self.btn_pending = QToolButton()
        self.btn_pending.setText(tr("💾 저장 안 한 OCR"))
        self.btn_pending.setToolTip(tr("OCR·단어장 결과가 아직 저장되지 않았습니다 — 눌러서 저장하거나 버립니다"))
        self.btn_pending.setVisible(False)
        self.btn_pending.clicked.connect(self._pending_dialog)
        try:
            self.status.addPermanentWidget(self.btn_pending)
        except Exception:
            pass

    def job_add(self, jid: str, label: str, cancel=None, discard=None) -> str:
        """cancel = [중단] 때 부를 함수(워커 `request_cancel`), discard = [취소] 때 작업이 끝난 뒤 버릴 함수(있으면 [취소] 단추)."""
        self._jobs[jid] = {"label": label, "cancel": cancel, "discard": discard, "msg": "", "stopping": False}
        self._jobs_sync_bar()
        self._jobs_entry_hint()
        self._jobs_refresh()
        return jid

    def job_progress(self, jid: str, msg: str) -> None:
        j = self._jobs.get(jid)
        if j is not None:
            j["msg"] = str(msg or "")
            if self._jobs_dlg is not None and self._jobs_dlg.isVisible():
                self._jobs_refresh()

    def job_done(self, jid: str) -> bool:
        """작업 끝. [취소] 를 눌렀던 작업이면 이제(워커가 끝난 뒤) 버리고 True — 부른 쪽은 끝 처리를 건너뛴다."""
        j = self._jobs.pop(jid, None)
        discarded = bool(j and j.get("stopping") == "discard")
        self._jobs_sync_bar()
        self._jobs_entry_hint()
        self._jobs_refresh()
        if discarded:
            try:
                j["discard"]()               # 배경(_file_op_bg) — 응답성 SOT §4 ⑤
            except Exception:
                pass
            self.status.showMessage(tr("'{label}' 를 취소했습니다 — 저장하지 않은 결과를 버렸습니다.").format(label=j["label"]), 6000)
        self._pending_refresh()
        return discarded

    def job_stop(self, jid: str) -> None:
        """[중단] — 다음 안전한 경계에서 멈추고 여기까지 한 것은 남긴다."""
        j = self._jobs.get(jid)
        if not j or not j.get("cancel") or j.get("stopping"):
            return
        j["stopping"] = "stop"
        try:
            j["cancel"]()
        except Exception:
            pass
        self.status.showMessage(tr("'{label}' 를 멈추는 중 — 지금 쪽을 마치면 멈춥니다").format(label=j["label"]), 6000)
        self._jobs_refresh()

    def job_cancel(self, jid: str) -> None:
        """[취소] — 멈추게 하고, 끝나면(`job_done`) 저장하지 않은 결과를 버린다. 다시 묻지 않는다(261105-25, 사용자 결정)."""
        j = self._jobs.get(jid)
        if not j or not j.get("cancel") or not j.get("discard") or j.get("stopping"):
            return
        j["stopping"] = "discard"
        try:
            j["cancel"]()
        except Exception:
            pass
        self.status.showMessage(tr("'{label}' 를 취소하는 중 — 지금 쪽을 마치면 멈추고 결과를 버립니다").format(label=j["label"]), 6000)
        self._jobs_refresh()

    def _jobs_sync_bar(self) -> None:
        """261106-19(응답성 SOT §4.6 '진행 막대'): 상태 표시줄 진행 막대는 **작업 창에 오른 작업이 있을 때만** 보인다 —
        보이고 숨기는 곳은 여기 하나다. 다른 코드는 범위·값(`setRange`·`setValue`)만 바꾼다(`test_tool_cancel_jobs_bar_261106`).
        종전에는 `job_add` 가 켜고 끄는 것은 부른 쪽 몫이라, 끄지 않은 작업(zip 풀기 등)이 끝나도 막대가 남아
        눌러 보면 '진행 중인 작업이 없습니다' 였다(사용자 보고)."""
        try:
            on = bool(self._jobs)
            if on and not self.progress.isVisible():
                self.progress.setRange(0, 0)         # 첫 진행 전에는 바쁨 표시 — 작업이 범위를 주면 그 값으로
            self.progress.setVisible(on)
        except Exception:
            pass

    def _jobs_entry_hint(self) -> None:
        """상태 표시줄(진행 메시지 자리)은 작업이 있을 때만 손가락 커서·툴팁 — 누르면 작업 창."""
        try:
            if self._jobs:
                self.status.setCursor(Qt.CursorShape.PointingHandCursor)
                self.status.setToolTip(tr("눌러서 진행 중인 작업 보기·중단·취소"))
            else:
                self.status.unsetCursor()
                self.status.setToolTip("")
        except Exception:
            pass

    def _jobs_list(self):
        return list(self._jobs.items())

    def _jobs_refresh(self):
        if self._jobs_dlg is not None:
            try:
                self._jobs_dlg.refresh()
            except RuntimeError:
                self._jobs_dlg = None

    def open_jobs_window(self):
        if self._jobs_dlg is None:
            self._jobs_dlg = JobsDialog(self, self)
        self._jobs_dlg.refresh()
        self._jobs_dlg.show()
        self._jobs_dlg.raise_()
        self._jobs_dlg.activateWindow()

    # ── 저장 안 한 OCR·단어장 ──────────────────────────────────────
    #   응답성 SOT §4 ⑤·§4.4: study.db 를 메인에서 열지 않는다 — 목록은 배경에서 세어 기억해 두고(`_pending_cache`),
    #   확정·버림은 `_file_op_bg`(배경 + 0.3초 넘으면 진행창)로 한다.
    def _pending_cache_get(self) -> dict:
        return dict(getattr(self, "_pending_cache", None) or {})

    def _pending_refresh(self) -> None:
        """보류 목록을 배경에서 다시 센다 → 끝나면 단추를 보이거나 감춘다."""
        from viewer.workers import run_in_thread
        w = _PendingScan()
        w.finished.connect(self._on_pending_scanned)
        try:
            run_in_thread(w, self._thread_keep)
        except Exception:
            pass

    def _on_pending_scanned(self, cache: dict) -> None:
        self._pending_cache = dict(cache or {})
        try:
            self.btn_pending.setVisible(bool(self._pending_cache))
        except Exception:
            pass

    def study_pending_for(self, path) -> bool:
        """그 파일에 저장 안 한 OCR·단어장이 있나 — 배경에서 세어 둔 목록으로(메인에서 DB 를 열지 않는다)."""
        from viewer.study.study_store import file_key_for
        try:
            return file_key_for(str(path)) in self._pending_cache_get()
        except Exception:
            return False

    def study_discard_for(self, path) -> None:
        from viewer.study.study_store import file_key_for
        self._pending_apply([file_key_for(str(path))], False, quiet=True)

    def study_commit_for(self, path) -> bool:
        """그 파일의 보류 OCR·단어장을 확정한다(책갈피창 [저장]·PDF 에 반영·OCR 글자층이 부른다).
        배경에서 옮긴다. 보류가 있었으면 True — 목록을 아직 세지 못했으면 일단 옮겨 보고 결과로 답한다."""
        from viewer.study.study_store import file_key_for
        k = file_key_for(str(path))
        ok = self._pending_apply([k], True, quiet=True)
        return bool(ok.get(k))

    def _pending_apply(self, keys, commit: bool, quiet: bool = False, index_now: bool = True) -> dict:
        """확정(commit) 또는 버림 — 배경. {key: 옮긴 것이 있었나}."""
        done = {}
        reindex = []
        photos = []                                  # 사진 보기 SOT §4.36 — OCR 을 확정한 사진: (경로, 확정 글, 형식, 키워드)

        def _fn():
            from viewer.study.study_store import StudyStore, path_for_key
            from viewer.image_page import PHOTO_EXTS
            st = StudyStore()
            try:
                have = set(st.pending_keys())
                for k in keys:
                    done[k] = k in have
                    if k in have:
                        if commit:
                            st.commit_pending(k)
                            p = path_for_key(k)
                            if p and Path(p).suffix.lower() in PHOTO_EXTS:
                                from viewer.photo_controller import photo_auto_tags, photo_saved_ocr
                                text = photo_saved_ocr(st, p)
                                if text:
                                    photos.append((p, text) + tuple(photo_auto_tags(p, text)))
                            elif p:
                                reindex.append(p)        # PDF 만 다시 색인(G2 — 사진은 PDF 색인에 넣지 않는다)
                        else:
                            st.discard_pending(k)
            finally:
                st.close()
            # 261019-4(검색창 SOT §3.2): 저장한 OCR 은 스캔 쪽 검색 원천이다 — 그 파일을 다시 색인하게 표시
            if reindex and getattr(self, "_db_path", None):
                try:
                    from viewer.indexer import PdfIndex
                    ix = PdfIndex(self._db_path)
                    try:
                        for pth in reindex:
                            ix.invalidate(pth)
                    finally:
                        ix.close()
                except Exception:
                    pass
        e = self._file_op_bg(_fn, tr("OCR·단어장 결과 저장 중…") if commit else tr("OCR·단어장 결과 버리는 중…"))
        if e is not None and not quiet:
            QMessageBox.warning(self, tr("저장"), str(e))
        if photos:
            try:
                self._photo_ocr_committed(photos)
            except Exception:
                pass
        cache = self._pending_cache_get()
        for k in keys:
            cache.pop(k, None)
        self._on_pending_scanned(cache)
        # 배경 색인(그 파일들만) — 종료 때는 표시만(다음 실행이 다시 읽는다). 파일마다 따로 걸면 앞 작업·진행 중인
        #   폴더 색인을 서로 취소하므로(한 번에 하나), 색인 중이면 끝난 뒤에, 아니면 한 작업으로(검색창 SOT §3 — 이름 변경과 같은 길)
        todo = [str(p) for p in (reindex if index_now else [])]
        try:
            if todo and getattr(self, "_index_workers", None):
                self._index_after = list(getattr(self, "_index_after", []) or []) + todo
            elif len(todo) == 1:
                self._index_single_file(Path(todo[0]))
            elif todo:
                self._index_files(todo)
        except Exception:
            pass
        if any(done.values()):
            try:
                self._refresh_study_panel(self.main_view.current_page())
            except Exception:
                pass
        return done

    def _pending_describe(self, cache: dict) -> str:
        from viewer.study.study_store import path_for_key
        out = []
        for k, s in cache.items():
            pth = s.get("path") or path_for_key(k)
            name = Path(pth).name if pth else k
            bits = []
            if s.get("pages"):
                bits.append(tr("OCR {n}쪽").format(n=s["pages"]))
            if s.get("vocab"):
                bits.append(tr("단어 {n}개").format(n=s["vocab"]))
            out.append(f"• {name} — {', '.join(bits) or tr('지운 결과')}")
        return "\n".join(out[:12]) + ("\n…" if len(out) > 12 else "")

    def _pending_dialog(self):
        cache = self._pending_cache_get()
        if not cache:
            self._pending_refresh(); return
        keys = list(cache)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("저장 안 한 OCR·단어장"))
        box.setText(tr("아직 저장하지 않은 OCR·단어장 결과가 있습니다.\n\n{list}").format(list=self._pending_describe(cache)))
        b_save = box.addButton(tr("저장"), QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton(tr("버리기"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("닫기"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        c = box.clickedButton()
        if c is b_save:
            self._pending_apply(keys, True)
            self.status.showMessage(tr("OCR·단어장 결과를 저장했습니다."), 5000)
        elif c is b_disc:
            if QMessageBox.question(self, tr("버리기"),
                                    tr("저장하지 않은 OCR·단어장 결과를 버릴까요? (되돌릴 수 없습니다)")) \
                    == QMessageBox.StandardButton.Yes:
                self._pending_apply(keys, False)
                self.status.showMessage(tr("저장하지 않은 OCR·단어장 결과를 버렸습니다."), 5000)

    def _confirm_close_pending(self) -> bool:
        """종료 전 — 보류 결과가 있으면 저장/저장 안 함/취소. True=종료 진행.
        목록은 그 자리에서 배경으로 다시 센다(놓치면 말없이 버려진다)."""
        # 261019-4(점검): 종료 때는 **늘 다시 센다** — 미리 센 목록은 방금 끝난 OCR·도는 작업의 결과를 빠뜨릴 수 있다
        got = {}
        self._file_op_bg(lambda: got.update(_pending_scan_now()), tr("저장 안 한 OCR 확인 중…"))
        self._pending_cache = got
        cache = self._pending_cache_get()
        if not cache:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("저장 안 한 OCR·단어장"))
        box.setText(tr("저장하지 않은 OCR·단어장 결과가 있습니다. 종료하기 전에 어떻게 할까요?\n\n{list}")
                    .format(list=self._pending_describe(cache)))
        b_save = box.addButton(tr("저장 후 종료"), QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton(tr("저장 안 하고 종료"), QMessageBox.ButtonRole.DestructiveRole)
        b_cancel = box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        c = box.clickedButton()
        if c is b_cancel or c is None:
            return False
        self._pending_apply(list(cache), c is b_save, index_now=False)
        return True


def _pending_scan_now() -> dict:
    """{file_key: {pages, vocab, path}} — 워커 스레드에서 부른다."""
    from viewer.study.study_store import StudyStore, path_for_key
    out = {}
    st = StudyStore()
    try:
        for k in st.pending_keys():
            d = st.pending_summary(k)
            d["path"] = path_for_key(k)
            out[k] = d
    finally:
        st.close()
    return out


class _PendingScan(QObject):
    """보류 목록 세기 — 배경(응답성 SOT §4 ⑤). 결과는 finished(dict) 하나."""
    finished = pyqtSignal(dict)

    def run(self):
        try:
            res = _pending_scan_now()
        except Exception:
            res = {}
        self.finished.emit(res)
