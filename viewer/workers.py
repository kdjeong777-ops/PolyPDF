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
            res = {}
            # ── 260904-1(§4.4): 검토 표에서 확정한 책갈피 — 추출 없이 바로 저장 ──
            pre = self.opts.get("bookmarks")
            if pre:
                import pdf_bookmarker as _pb
                bookmarks = [_pb.Bookmark(title=str(t_), page=int(p_), level=int(l_))
                             for (t_, p_, l_) in pre if str(t_).strip() and int(p_) > 0]
                method = self.opts.get("method") or "review"
                mode = "review"
                if not bookmarks:
                    raise RuntimeError("저장할 책갈피가 없습니다.")
                self._write_and_finish(bridge, bookmarks, method, res, mode)
                return
            # ── 260904-1(§4.4): 목차 쪽 지정 → 관대한 파서(toc_parse) 로 표 생성 ──
            #   사용자가 쪽을 지정했거나, auto/toc 에서 탐지된 목차 쪽이 있으면 이 경로.
            #   (내장 파서는 점선 리더 형식만 알아 OCR 텍스트층 스캔본에서 0건이었다.)
            toc_pages = list(self.opts.get("toc_pages") or [])
            if mode in ("auto", "toc") and not toc_pages:
                try:
                    from viewer import toc_parse as _tp
                    toc_pages = _tp.find_toc_pages(self.input_pdf)     # 260904-2: 관대한 탐지
                except Exception:
                    toc_pages = []
            if toc_pages and mode in ("auto", "toc"):
                from viewer import toc_parse
                self.progress.emit(f"목차 쪽 {toc_pages[0]}~{toc_pages[-1]} 읽는 중...")
                rows = toc_parse.parse_toc_pages(self.input_pdf, toc_pages)
                if rows:
                    self.progress.emit("오프셋(목차 쪽 → 실제 쪽) 추정 중...")
                    cands = toc_parse.suggest_offsets(self.input_pdf, rows, toc_pages)
                    off = self.opts.get("offset")
                    if off is None:
                        off = cands[0][0] if cands else 0
                    if self.opts.get("review"):
                        # 검토 단계: 표만 돌려주고 끝. 앱이 검토 창을 띄운 뒤 bookmarks 로 재호출.
                        self.finished.emit({"phase": "review", "method": "toc",
                                            "rows": rows, "candidates": cands, "offset": int(off),
                                            "toc_pages": toc_pages})
                        return
                    import fitz
                    _d = fitz.open(str(self.input_pdf)); _n = _d.page_count; _d.close()
                    toc_parse.apply_offset(rows, int(off), _n, keep_manual=False)
                    import pdf_bookmarker as _pb
                    bookmarks = [_pb.Bookmark(title=t_, page=p_, level=l_)
                                 for (t_, p_, l_) in toc_parse.to_bookmarks(rows)]
                    res = {"offset": int(off)}
                    self._write_and_finish(bridge, bookmarks, "toc", res, "toc")
                    return
                elif mode == "toc":
                    raise RuntimeError("지정한 목차 쪽에서 항목을 읽지 못했습니다. 쪽 범위를 확인하세요.")
                # auto 인데 항목이 없으면 종전 경로(폰트/OCR)로 계속
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
            # 260904-1: 폰트/OCR 결과도 검토 표를 거칠 수 있다(오프셋 없음 — 실제 쪽 그대로)
            if self.opts.get("review"):
                rows = [{"title": b.title, "toc_page": None, "page": int(b.page),
                         "level": int(b.level), "src": method} for b in bookmarks]
                self.finished.emit({"phase": "review", "method": method, "rows": rows,
                                    "candidates": [], "offset": 0, "toc_pages": []})
                return
            self._write_and_finish(bridge, bookmarks, method, res, mode)
        except Exception as e:
            self.error.emit(str(e))

    def _write_and_finish(self, bridge, bookmarks, method, res, mode):
        """260904-1: 추출/검토 결과를 PDF·txt 로 쓰고 finished 발신(종전 저장 꼬리를 분리)."""
        try:
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
                "phase": "done",
                "count": len(bookmarks),
                "method": method,
                "offset": (None if mode in ("ocr", "review") else res.get("offset")),
                "pdf_out": str(pdf_out) if pdf_out else None,
                "txt_out": str(txt_out) if txt_out else None,
            })
        except Exception as e:
            self.error.emit(str(e))


class SearchWorker(QObject):
    """검색을 백그라운드에서 수행."""
    finished = pyqtSignal(str, list)   # query, results
    error = pyqtSignal(str)

    def __init__(self, db_path: Path, query: str, paths: list | None = None):
        super().__init__()
        self.db_path = db_path
        self.query = query
        self.paths = paths                 # 260828: 검색 범위 파일 목록(None=전체)

    def run(self):
        try:
            idx = PdfIndex(self.db_path)
            try:
                res = idx.search(self.query, paths=self.paths)
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
    GC 로 사라지지 않는다.

    260628: **완료 시 keep 리스트에서 자동 제거**(누수 정리). 종전에는 append 만 하고
    제거가 없어 긴 세션에서 죽은 QThread·worker 래퍼가 무한 누적됐다. 호출측은 별도
    정리 코드를 넣지 않는다(마스터 SOT §11.9)."""
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

    def _prune():
        # 스레드 종료 후 keep 리스트에서 자기 자신(th·worker)만 제거. 리스트를 통째로
        # 비우지 않는다 — 동시에 도는 다른 작업의 참조를 끊으면 안 됨.
        for obj in (th, worker):
            try:
                parent_keep.remove(obj)
            except ValueError:
                pass

    th.finished.connect(_prune)
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


class AutoTagWorker(QObject):
    """260829(태그 SOT §8.2·P2): 태그·연도 자동 계산 워커.

    ★ TagStore 를 직접 만지지 않는다 — 스레드 경합 회피. 계산 결과만 emit 하고
      적용(rehome·set_auto·set_year)은 UI 스레드(app._on_autotag_finished)가
      `store.bulk()` 안에서 한다. 지문(§6.1)도 여기서 계산해 넘긴다(무거운 부분).
    본문은 index.db(`page_texts`) 우선 — 미색인만 fitz 폴백(§7 재파싱 금지).
    """
    progress = pyqtSignal(int, int, str)      # done, total, current
    finished = pyqtSignal(list, dict)         # results, stats
    error = pyqtSignal(str)

    def __init__(self, db_path, paths, tagged_docs, known_tags, rules,
                 today_year, store_keys, fp_missing_keys, kw_skip_keys=()):
        super().__init__()
        self.db_path = db_path
        self.paths = [str(p) for p in paths]
        self.tagged_docs = dict(tagged_docs)      # {태그: [경로…]} — 프로파일 학습용
        self.known_tags = list(known_tags)
        self.rules = dict(rules or {})
        self.today_year = int(today_year)
        self.store_keys = set(store_keys)         # 경로 적중 판별(지문 생략 — §6.1 ①)
        self.fp_missing_keys = set(fp_missing_keys)   # 항목은 있는데 fp 없는 것 — 채움
        self.kw_skip_keys = set(kw_skip_keys)     # 260830 P4: kw_edited(§9.1) — 생성 생략
        self._cancel = False

    @staticmethod
    def _ko_lookup_map():
        """260830 P4(§9.2-5): dict.db 영→한 대역 맵 — 없거나 실패하면 None(병기 생략)."""
        try:
            import sqlite3
            from viewer.settings_store import settings_dir
            p = Path(settings_dir()) / "dict.db"
            if not p.exists():
                return None
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            try:
                m = {}
                for ne, tk in con.execute(
                        "SELECT norm_en, term_ko FROM dict_entry "
                        "WHERE enabled=1 AND norm_en<>'' AND term_ko<>''"):
                    m.setdefault(ne.lower(), tk)
                return m
            finally:
                con.close()
        except Exception:
            return None

    def _folder_ctx(self):
        """260830 P5(§5.4.1 ③·⑤): 파일별 상위 폴더명(루트 제외·3단계)과
        점유율 30% 초과 폴더 제외 집합, 대형 폴더(≥20) 목록."""
        import os as _os
        total = max(1, len(self.paths))
        try:
            root = _os.path.commonpath(self.paths) if len(self.paths) > 1 \
                else _os.path.dirname(self.paths[0])
        except Exception:
            root = ""
        dir_count = {}
        for p in self.paths:
            d = _os.path.dirname(p)
            dir_count[d] = dir_count.get(d, 0) + 1
        over = {d for d, n in dir_count.items() if n / total >= 0.30}  # 점유율 상한
        names = {}
        for p in self.paths:
            out, d = [], _os.path.dirname(p)
            depth = 0
            while d and _os.path.normcase(d) != _os.path.normcase(root) and depth < 3:
                if d not in over:
                    out.append(_os.path.basename(d))
                d2 = _os.path.dirname(d)
                if d2 == d:
                    break
                d, depth = d2, depth + 1
            names[p] = out
        big_dirs = {d for d, n in dir_count.items() if n >= 20}
        return names, big_dirs, dir_count

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            import os as _os
            from viewer.auto_tag import (build_profiles, extract_features,
                                         extract_year, new_tag_candidates,
                                         partition, suggest_keywords,
                                         suggest_tags)
            from viewer.tag_store import TagStore
            try:
                ix = PdfIndex(self.db_path)
            except Exception:
                ix = None

            def texts(p):
                if ix is not None:
                    t = ix.page_texts(p)
                    if t:
                        return t
                return None                       # extract_features 가 fitz 폴백

            folder_names, big_dirs, dir_count = self._folder_ctx()
            ko_map = self._ko_lookup_map()
            ko_lookup = (lambda w: ko_map.get(w.lower())) if ko_map else None

            # 1패스: 특징 추출 + 전역 DF(§3.3.1-①) + 대형 폴더 공통어 DF(§9.2-3)
            feats, df = {}, {}
            dir_term_df = {d: {} for d in big_dirs}
            total = len(self.paths)
            for i, p in enumerate(self.paths):
                if self._cancel:
                    return
                try:
                    f = extract_features(p, page_texts=texts(p),
                                         folder_names=folder_names.get(p))
                except Exception:
                    continue
                feats[p] = f
                for t in set(f.terms):
                    df[t] = df.get(t, 0) + 1
                d = _os.path.dirname(p)
                if d in big_dirs:
                    dd = dir_term_df[d]
                    for t in set(f.terms):
                        dd[t] = dd.get(t, 0) + 1
                self.progress.emit(i + 1, total * 2, p)
            n_docs = max(1, len(feats))
            # 폴더 공통어(§9.2-3): ≥20파일 폴더에서 60% 이상 문서에 나오는 어휘
            folder_common = {}
            for d in big_dirs:
                th = max(2, int(dir_count[d] * 0.6))
                folder_common[d] = {t for t, n in dir_term_df[d].items() if n >= th}

            # 프로파일(§5.2) — 태그가 붙은 파일들의 특징어로 학습
            tag_docs = {}
            for tag, plist in self.tagged_docs.items():
                cs = [feats[p].terms for p in plist if p in feats]
                if cs:
                    tag_docs[tag] = cs
            profiles = build_profiles(tag_docs, df, n_docs)
            # 260830 P3: 단일 파일 즉석 제안(§8.1)용 세션 캐시 — app 이 회수해 보관
            self.profiles, self.df, self.n_docs = profiles, df, n_docs

            # 2패스: 제안·게이트·연도·지문·키워드(§9)·신규 후보 적립(§5.4-5)
            results = []
            n_auto_files = 0
            candidates = {}                            # {태그: {"n":, "files": []}}
            key = TagStore._key
            for i, p in enumerate(self.paths):
                if self._cancel:
                    return
                f = feats.get(p)
                if f is None:
                    continue
                sugg = suggest_tags(f, profiles, df, n_docs,
                                    known_tags=self.known_tags, rules=self.rules)
                part = partition(sugg)
                year, ysrc, yconf = extract_year(f, self.today_year)
                k = key(p)
                fp = size = None
                try:
                    if k not in self.store_keys or k in self.fp_missing_keys:
                        fp, size = TagStore._fp_of(p)      # 무거운 계산은 워커에서(§6.1)
                except Exception:
                    pass
                # §9 키워드 — 게이트 없음, kw_edited 만 생략. 표시는 병기(치환 아님)
                kws = None
                if k not in self.kw_skip_keys:
                    fc = folder_common.get(_os.path.dirname(p))
                    kws = [(w["word"] + (f" ({w['ko']})" if w.get("ko") else ""))
                           for w in suggest_keywords(f, df, n_docs,
                                                     ko_lookup=ko_lookup,
                                                     folder_common=fc)]
                # §5.4-5 신규 후보 — 붙이지 않고 적립
                for c in new_tag_candidates(f, df, n_docs, self.known_tags,
                                            ko_lookup=ko_lookup):
                    cur = candidates.setdefault(c["tag"], {"n": 0, "files": []})
                    cur["n"] += 1
                    if len(cur["files"]) < 8:
                        cur["files"].append(p)
                auto = [(s["tag"], s["score"]) for s in part["auto"]]
                if auto:
                    n_auto_files += 1
                results.append({"path": p, "auto": auto, "keywords": kws,
                                "year": year, "year_src": ysrc, "year_conf": yconf,
                                "fp": fp, "size": size, "scanned": f.scanned})
                self.progress.emit(total + i + 1, total * 2, p)
            if ix is not None:
                ix.close()
            self.finished.emit(results, {
                "total": total, "auto_files": n_auto_files,
                "new_candidates": len(candidates), "candidates": candidates,
                "known_tags": len(self.known_tags)})
        except Exception as e:                    # noqa: BLE001
            self.error.emit(str(e))
