"""QThread 기반 백그라운드 작업자."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from viewer.indexer import PdfIndex


class IndexWorker(QObject):
    """폴더 인덱싱을 백그라운드에서 수행."""
    progress = pyqtSignal(int, int, str)  # done, total, current_file
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, db_path: Path, folder: Path,
                 single_file: Optional[Path] = None):
        super().__init__()
        self.db_path = db_path
        self.folder = folder
        self.single_file = single_file      # v1.6.11: 지정 시 이 파일만 인덱싱
        self._cancel = False                # 260611-89: 다른 폴더/파일 열 때 중단

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._cancel:
                return
            idx = PdfIndex(self.db_path)
            try:
                if self.single_file is not None:
                    if self._cancel:
                        return
                    self.progress.emit(0, 1, str(self.single_file))
                    # 260618-25: 이름(경로)·수정시각·크기 동일하면 재인덱싱 생략
                    #   (폴더 인덱싱과 동일한 needs_reindex 가드 — 단일 파일 열기마다
                    #    무조건 재인덱싱하던 비효율 제거).
                    p = Path(self.single_file)
                    if idx.needs_reindex(p):
                        idx.index_file(p)
                    self.progress.emit(1, 1, str(self.single_file))
                else:
                    idx.index_folder(
                        self.folder,
                        progress=lambda d, t, n: self.progress.emit(d, t, n),
                        should_cancel=lambda: self._cancel,
                    )
            finally:
                idx.close()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


def _pdf_is_scanned(pdf_path, sample: int = 12, ratio: float = 0.6) -> bool:
    """앞부분 표본 페이지를 보고 스캔 이미지 PDF인지 판정(260606-4 자동 분기용)."""
    try:
        import fitz
        from viewer.study import ocr as _ocr
        doc = fitz.open(str(pdf_path))
        try:
            n = doc.page_count
            if n == 0:
                return False
            idxs = list(range(min(n, sample)))
            scan = 0
            for i in idxs:
                src, _ = _ocr.decide_source(doc.load_page(i))
                if src == "ocr":
                    scan += 1
            return scan / len(idxs) >= ratio
        finally:
            doc.close()
    except Exception:
        return False


class BookmarkerWorker(QObject):
    """v1.6.16: 외부 pdf_bookmarker 호출. extract → (옵션) embed PDF / write txt.

    opts:
      input_pdf, mode("auto"|"toc"|"font"), offset(int|None),
      save_pdf(bool), save_txt(bool), out_dir(str), bookmarker_path(str).
    결과: {count, method, offset, pdf_out (Path|None), txt_out (Path|None)}.
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, input_pdf: Path, opts: dict):
        super().__init__()
        self.input_pdf = Path(input_pdf)
        self.opts = dict(opts)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            from viewer import bookmarker_bridge as bridge
            if not bridge.is_available(self.opts.get("bookmarker_path") or None):
                raise RuntimeError(
                    f"pdf_bookmarker 모듈 로드 실패: {bridge.get_status()}"
                )

            mode = self.opts.get("mode", "auto")
            # 260606-4: '자동'인데 스캔 이미지 PDF면 OCR 모드로 자동 전환
            if mode == "auto" and _pdf_is_scanned(self.input_pdf):
                self.progress.emit("스캔 이미지 감지 — OCR 모드로 추출")
                mode = "ocr"
            if mode == "ocr":
                # 스캔/이미지 PDF → OCR로 'CHAPTER 1' 등 헤딩 인식
                from viewer.study.ocr_headings import extract_ocr_bookmarks
                self.progress.emit("OCR 헤딩 인식 중...")
                bookmarks = extract_ocr_bookmarks(
                    self.input_pdf,
                    use_font_auto=bool(self.opts.get("ocr_font_auto", True)),
                    progress=lambda d, t, m: self.progress.emit(m),
                    should_cancel=lambda: self._cancel,
                )
                method = "ocr"
            else:
                self.progress.emit("책갈피 추출 중...")
                res = bridge.extract_auto(
                    self.input_pdf,
                    mode=mode,
                    offset=self.opts.get("offset"),
                )
                bookmarks = res["bookmarks"]
                method = res["method"]
            if self._cancel:
                raise RuntimeError("사용자가 취소했습니다.")
            # 260606-4(추가): 같은 페이지 다중 책갈피 → 헤딩(제목명/숫자)만 남김
            try:
                from viewer.study.ocr_headings import prefer_heading_per_page
                bookmarks = prefer_heading_per_page(bookmarks)
            except Exception:
                pass
            if not bookmarks:
                raise RuntimeError("추출된 책갈피가 없습니다.")

            out_dir = Path(self.opts.get("out_dir") or self.input_pdf.parent)
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = self.input_pdf.stem

            pdf_out = None
            if self.opts.get("save_pdf", True):
                self.progress.emit("PDF에 책갈피 임베드 중...")
                if self.opts.get("overwrite"):
                    # 260606-4: 현재 PDF에 저장 — 임시 파일로 쓰고 원본을 교체
                    import os as _os
                    tmp = self.input_pdf.with_name(self.input_pdf.stem + ".bm_tmp.pdf")
                    bridge.apply_to_pdf(self.input_pdf, tmp, bookmarks)
                    _os.replace(tmp, self.input_pdf)
                    pdf_out = self.input_pdf
                else:
                    pdf_out = bridge.apply_to_pdf(
                        self.input_pdf,
                        out_dir / f"{stem}_bookmarked.pdf",
                        bookmarks,
                    )

            txt_out = None
            if self.opts.get("save_txt", False):
                self.progress.emit("책갈피 텍스트 저장 중...")
                txt_out = bridge.write_txt(bookmarks, out_dir / f"{stem}_bookmarks.txt")

            self.finished.emit({
                "count": len(bookmarks),
                "method": method,
                "offset": (None if mode == "ocr" else res.get("offset")),
                "pdf_out": str(pdf_out) if pdf_out else None,
                "txt_out": str(txt_out) if txt_out else None,
            })
        except Exception as e:
            self.error.emit(str(e))


class SearchWorker(QObject):
    """검색을 백그라운드에서 수행."""
    finished = pyqtSignal(str, list)   # query, results
    error = pyqtSignal(str)

    def __init__(self, db_path: Path, query: str):
        super().__init__()
        self.db_path = db_path
        self.query = query

    def run(self):
        try:
            idx = PdfIndex(self.db_path)
            try:
                res = idx.search(self.query)
            finally:
                idx.close()
            self.finished.emit(self.query, res)
        except Exception as e:
            self.error.emit(str(e))


class StudyBuildWorker(QObject):
    """단어학습 OCR/인덱싱을 백그라운드에서 수행 (계획서 P1).

    - 스캔 감지 후 페이지별 레이어 사용 또는 Tesseract OCR → study.db(ocr_page/ocr_word).
    - 재개: 이미 처리된 페이지(ocr_page) 스킵.
    - 취소: request_cancel() → 다음 페이지 경계에서 중단.
    progress(done, total, msg) / finished(dict) / error(str).
    """
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: Path, *, lang: str = "eng", dpi: int = 300,
                 db_path: Optional[Path] = None, force_ocr: bool = False,
                 with_vocab: bool = True, online_prefs: Optional[dict] = None,
                 online_only: bool = False):
        super().__init__()
        self.pdf_path = Path(pdf_path)
        self.lang = lang
        self.dpi = dpi
        self.db_path = db_path
        self.force_ocr = force_ocr
        self.with_vocab = with_vocab       # OCR 후 어휘(P2)까지 빌드
        self.online_prefs = dict(online_prefs or {})  # 260615-14: 빌드 시 인터넷 사전 보강
        self.online_only = online_only     # 260615-15: 재OCR 없이 인터넷 보강만(이어하기)
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self):
        # 260615-15: 인터넷 사전 보강만(이어하기) — 재OCR/어휘 없이 온라인 캐시만 채움
        if self.online_only:
            store = None
            try:
                from viewer.study.study_store import StudyStore, file_key_for
                store = StudyStore(self.db_path)
                fkey = file_key_for(self.pdf_path)
                n = self._online_enrich(store, fkey)
                self.finished.emit({"file_key": fkey, "online": n,
                                    "online_only": True, "cancelled": self._cancel})
            except Exception as e:
                self.error.emit(str(e))
                self.finished.emit({"error": str(e)})
            finally:
                if store is not None:
                    store.close()
            return
        store = None
        doc = None
        try:
            import fitz
            from viewer.study import ocr as study_ocr
            from viewer.study.study_store import StudyStore, file_key_for

            info = study_ocr.ensure_tesseract()
            # 레이어 전용 문서는 Tesseract 없이도 가능하므로 여기서 막지 않음.

            store = StudyStore(self.db_path)
            fkey = file_key_for(self.pdf_path)
            doc = fitz.open(self.pdf_path)
            total = doc.page_count
            store.set_meta(fkey, str(self.pdf_path), total, self.lang)

            done0 = len(store.done_pages(fkey))
            self.progress.emit(done0, total, f"재개: {done0}/{total} 완료됨")

            processed = done0
            ocr_used = False
            for i in range(total):
                if self._cancel:
                    break
                if store.is_page_done(fkey, i):
                    continue
                try:
                    res = study_ocr.build_page(doc, i, lang=self.lang,
                                               dpi=self.dpi, force_ocr=self.force_ocr)
                except Exception as pe:
                    # OCR 필요한데 Tesseract 불가 등 — 페이지 스킵하고 계속
                    if not info.get("ok"):
                        raise RuntimeError(
                            f"OCR 필요하나 Tesseract 사용 불가: {info.get('error')}") from pe
                    raise
                if res["source"] == "ocr":
                    ocr_used = True
                store.save_page(fkey, i, res["text"], dpi=res["dpi"],
                                engine=res["engine"], source=res["source"],
                                conf=res["conf"], words=res["words"], lang=self.lang)
                processed += 1
                if i % 1 == 0:
                    self.progress.emit(processed, total,
                                       f"{i+1}p [{res['source']}]")

            vocab_summary = None
            if self.with_vocab and not self._cancel:
                self.progress.emit(total, total, "어휘 분석 중...")
                from viewer.study import vocab as study_vocab
                vocab_summary = study_vocab.build_vocab(store, fkey, self.lang)

            # 260615-14: 인터넷 사전 자동 보강(옵션) — 각 단어를 온라인 조회해 dict.db 캐시
            online_n = 0
            if (self.with_vocab and not self._cancel
                    and self.online_prefs.get("online_dict_enabled")):
                online_n = self._online_enrich(store, fkey)

            done, _ = store.page_progress(fkey)
            self.finished.emit({
                "file_key": fkey, "pages": total, "done": done,
                "cancelled": self._cancel, "ocr_used": ocr_used,
                "tesseract": info, "vocab": vocab_summary, "online": online_n,
            })
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({"error": str(e)})
        finally:
            if doc is not None:
                doc.close()
            if store is not None:
                store.close()

    def _online_enrich(self, store, fkey) -> int:
        """260615-14: 빌드 단어들을 인터넷 사전(모든 단어 API)으로 조회·캐시.
        재조회 방지(online_fetched) + 취소/상한/스로틀. 반환: 새로 캐시한 단어 수."""
        import time
        try:
            from viewer.study.dict_store import DictStore
            from viewer.study.online_dict import lookup_sources
        except Exception:
            return 0
        rows = list(store.conn.execute(
            "SELECT DISTINCT lemma, lang FROM vocab WHERE file_key=?", (fkey,)))
        if not rows:
            return 0
        dic = DictStore()             # 워커 스레드 전용 연결
        cap = int(self.online_prefs.get("online_cap", 600))
        total = min(len(rows), cap)
        n = 0
        for idx, r in enumerate(rows[:cap]):
            if self._cancel:
                break
            lemma = r["lemma"]; lang = r["lang"]
            # 260617-4: 인터넷 접속 전 '전체 자료(dict.db)' 를 먼저 검색 —
            #   이미 사전(User/Base/Auto, 다른 파일 포함)에 자료가 있으면 인터넷 조회 생략.
            #   (is_online_fetched=과거 인터넷 조회 표시, lookup=현재 보유 자료)
            if dic.is_online_fetched(lemma) or dic.lookup(lemma):
                continue
            if idx % 5 == 0:
                self.progress.emit(idx, total, f"인터넷 사전 조회 {idx}/{total}")
            ko = lemma if str(lang).startswith("ko") else ""
            en = lemma if not str(lang).startswith("ko") else ""
            try:
                provs = lookup_sources(ko, en, prefs=self.online_prefs)
            except Exception:
                provs = []
            dic.mark_online_fetched(lemma)
            for p in provs:            # 제공처별 출처에 각각 저장
                dic.ensure_online_provider(p["source_id"], p["name"], p["is_termbase"])
                kw = {"source_id": p["source_id"], "reference": p["name"],
                      "def_ko": "\n".join(p.get("def_ko", [])),
                      "def_en": "\n".join(p.get("def_en", [])),
                      "examples": "\n".join(e.get("text", "") for e in p.get("examples", [])),
                      "hanja": p.get("hanja", "")}
                if str(lang).startswith("ko"):
                    kw["term_ko"] = lemma
                else:
                    kw["term_en"] = lemma
                try:
                    dic.add_entry(**kw); n += 1
                except Exception:
                    pass
            time.sleep(0.03)          # 과도한 호출 방지(예의)
        dic.close()
        return n


class StudyExportWorker(QObject):
    """단어장 Word(.docx) 저장을 백그라운드에서 (UI 멈춤 방지). 260603."""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db_path, file_key: str, out_path, opts: dict):
        super().__init__()
        self.db_path = db_path
        self.file_key = file_key
        self.out_path = out_path
        self.opts = dict(opts)

    def run(self):
        store = None
        try:
            from viewer.study.study_store import StudyStore
            from viewer.study.export_docx import export_study_docx
            store = StudyStore(self.db_path)
            export_study_docx(
                store, self.file_key, self.out_path,
                progress=lambda i, n: self.progress.emit(i, n, "Word 저장 중..."),
                **self.opts)
            self.finished.emit({"out": str(self.out_path)})
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({"error": str(e)})
        finally:
            if store is not None:
                store.close()


class StudyMp3Worker(QObject):
    """페이지별 mp3(+가사 lrc) 저장을 백그라운드에서 (260606-2). UI 멈춤 방지."""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, jobs: list, rate: int = 0, voice_name: str = None,
                 resume: bool = False):
        super().__init__()
        self.jobs = jobs              # [(mp3_path, lrc_path, segments)]
        self.rate = rate
        self.voice_name = voice_name
        self.resume = resume          # 이미 있는 파일은 건너뜀(이어서 저장)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from pathlib import Path as _P
        try:
            from viewer.study.mp3_export import synth_to_mp3, _make_voice
            import pythoncom, win32com.client
            pythoncom.CoInitialize()
            voice, tok = _make_voice(self.rate)        # 1회 생성·재사용(빠름)
            by = {t.GetAttribute("Name"): t for t in voice.GetVoices()}
            forced = by.get(self.voice_name) if self.voice_name else None
            n = len(self.jobs)
            done = skipped = 0
            for i, (mp3, lrc, segs) in enumerate(self.jobs):
                if self._cancel:
                    break
                self.progress.emit(i, n, f"{i+1}/{n}")
                if self.resume and _P(mp3).exists() and _P(mp3).stat().st_size > 0:
                    skipped += 1
                    continue
                try:
                    synth_to_mp3(segs, mp3, lrc_path=lrc,
                                 voice=voice, tok=tok, forced=forced)
                    done += 1
                except Exception:
                    pass
            self.progress.emit(n, n, "완료")
            self.finished.emit({"saved": done, "skipped": skipped, "total": n,
                                "cancelled": self._cancel})
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit({"error": str(e)})
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass


def run_in_thread(worker: QObject, parent_keep: list) -> QThread:
    """worker.run 을 새 QThread 에서 실행. 참조 보존을 위해 parent_keep 리스트에 넣어두면
    GC 로 사라지지 않는다."""
    th = QThread()
    worker.moveToThread(th)
    th.started.connect(worker.run)
    if hasattr(worker, "finished"):
        worker.finished.connect(th.quit)
    th.finished.connect(th.deleteLater)
    if hasattr(worker, "finished"):
        worker.finished.connect(worker.deleteLater)
    parent_keep.append(th)
    parent_keep.append(worker)
    th.start()
    return th


class OnlineDictFetchWorker(QThread):
    """260615-13(P11b): 인터넷 사전 조회를 백그라운드로. UI 멈춤 방지.
    items: [(lemma, lang)]. 결과: [(lemma, lang, result_dict)]."""
    done = pyqtSignal(list)

    def __init__(self, items, prefs: dict):
        super().__init__()
        self._items = list(items)
        self._prefs = dict(prefs or {})

    def run(self):
        from viewer.study.online_dict import lookup_sources
        out = []
        for lemma, lang in self._items:
            ko = lemma if str(lang).startswith("ko") else ""
            en = lemma if not str(lang).startswith("ko") else ""
            try:
                provs = lookup_sources(ko, en, prefs=self._prefs)
            except Exception:
                provs = []
            out.append((lemma, lang, provs))
        self.done.emit(out)
