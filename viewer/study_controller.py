"""260628(감사 F-3): 단어장·번역 컨트롤러 — MainWindow 에서 분리한 믹스인.

app.py 분할 3단계(§11.11). 담당: 단어장 저장소 접근(`_study_get_*`), 언어 판별,
번역 실행(`_action_translate_*`)·용어집(`_action_edit_glossary`/`_action_import_glossary`),
사전 보강(`_enrich_rows_with_dict`/`_maybe_online_enrich`), 용어 스포팅(`_get_spot_terms`/
`_spot_page_terms`), 단어장 패널 갱신·이동(`_refresh_study_panel`/`_on_study_*`),
음성·mp3(`_on_study_mp3`/`_on_main_mp3`), 내보내기·사전 관리(`_action_*_dict`),
학습자료 생성(`_action_build_study`/`_build_bookmarks_from_study`).

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(StudyMixin, ...)`).
`self.*` 참조가 모두 그대로 동작하므로 **호출부(메뉴·패널 시그널)는 변경 없음**.
SOT: `단어장 작업 계획서.md`(총괄) / `단어학습(OCR·어휘) 기능 작업계획서.md`(하위) /
`PDF 번역·요약 작업 계획서.md`(번역).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from viewer.workers import StudyBuildWorker, run_in_thread

__all__ = ["StudyMixin"]


class StudyMixin:
    """MainWindow 에 믹스인되는 단어장·번역 메서드 모음."""

    def _study_get_store(self):
        if self._study_store is None:
            from viewer.study.study_store import StudyStore
            self._study_store = StudyStore()      # settings_dir()/study.db
        return self._study_store

    def _study_get_user(self):
        if self._user_store is None:
            from viewer.study.study_store import UserStore
            self._user_store = UserStore()        # settings_dir()/user_study.db
        return self._user_store

    def _study_get_dict(self):
        """260611-100(P1): 계층형 전문 용어사전(dict.db) — Base/User 항목.
        260611-101(P3): 최초 생성 시 동봉 기본 용어집(resources/dict/*.json) 시드."""
        if getattr(self, "_dict_store", None) is None:
            from viewer.study.dict_store import DictStore
            self._dict_store = DictStore()        # settings_dir()/dict.db
            try:
                from viewer.study.glossary_import import load_bundled_glossaries
                seeded = load_bundled_glossaries(self._dict_store)
                if seeded:
                    self.status.showMessage(
                        "기본 용어집 적재: " + ", ".join(seeded), 4000)
            except Exception:
                pass
            # 단어장 폴더 → dict.db 출처 동기화(하이브리드)
            try:
                from viewer.study import glossary_folder as _gf
                _gf.sync_folder(self._dict_store, self._prefs)
            except Exception:
                pass
        return self._dict_store

    def _action_dict_manager(self, checked: bool = False):
        """260621-70: 단어장 관리(출처 on/off·우선순위·폴더)."""
        from viewer.widgets.dict_manager_dialog import DictManagerDialog
        dlg = DictManagerDialog(self._study_get_dict(), self._prefs, host=self, parent=self)

        def _refresh():
            try:
                self.study_panel.set_dict_sources(self._study_get_dict().list_sources())
            except Exception:
                pass
        dlg.changed.connect(_refresh)
        dlg.exec()
        _refresh()

    def _study_get_tts(self):
        if self._tts is None:
            from viewer.study.tts import get_tts
            self._tts = get_tts()
        return self._tts

    def _detect_study_lang(self, path: Path) -> str:
        """간단 언어 감지 — 첫 몇 페이지에 한글이 많으면 kor, 아니면 eng."""
        try:
            import fitz, re
            doc = fitz.open(path)
            sample = "".join(doc.load_page(i).get_text("text")
                             for i in range(min(5, doc.page_count)))
            doc.close()
            hangul = len(re.findall(r"[가-힣]", sample))
            latin = len(re.findall(r"[A-Za-z]", sample))
            return "kor" if hangul > latin else "eng"
        except Exception:
            return "eng"

    def _translate_auth_ready_or_warn(self) -> bool:
        """260621-P0: 번역 사용 가능 여부(모듈·인증) 확인 + 안내."""
        from viewer.study import translate_api as _tapi
        if not _tapi.available():
            QMessageBox.information(
                self, "PDF 번역",
                "번역 모듈(anthropic)이 포함되어 있지 않습니다. 최신 배포본을 사용하세요.")
            return False
        auth = (self._prefs.get("translate_auth") or "api").strip()
        key = (self._prefs.get("anthropic_api_key") or "").strip()
        if auth != "login" and not key:
            QMessageBox.information(
                self, "PDF 번역",
                "설정 → '번역(Claude)' 에서 Anthropic API 키를 먼저 입력하세요.\n"
                "(키 발급: https://console.anthropic.com → API Keys)\n"
                "또는 인증 방식을 'Claude 로그인(구독)'으로 바꾸세요.")
            return False
        return True

    def _action_translate_pdf(self, checked: bool = False):
        """260621-P0: 현재 열린 PDF 번역(단일)."""
        if not self._study_pdf or not Path(self._study_pdf).exists():
            QMessageBox.information(self, "PDF 번역", "먼저 PDF 를 여세요.")
            return
        self._action_translate_file(str(self._study_pdf))

    def _action_translate_file(self, path: str):
        """260621-P0: 단일 PDF 번역 — 앞부분 텍스트를 채워 PoC 다이얼로그를 연다.
        (책갈피 우클릭 '번역...' / 현재 PDF 번역에서 호출)"""
        if not self._translate_auth_ready_or_warn():
            return
        from viewer.study import translate_api as _tapi
        init = ""
        try:
            if path and Path(path).exists():
                # P1: 머리말/꼬리말 제거·본문 연결된 정제 본문(실패 시 원시 추출 폴백)
                from viewer.study import pdf_extract as _px
                init = (_px.extract_clean_text(path, max_chars=200000)
                        or _tapi.extract_pdf_text(path, max_chars=200000))
        except Exception:
            init = ""
        # 용어집(사전 1순위 + 자동 제안)·요약·서지·Word/PDF 산출은 번역 워커가 백그라운드 처리
        from viewer.widgets.translate_dialog import TranslatePocDialog
        TranslatePocDialog(self._prefs, self, initial_text=init, source_path=str(path)).exec()

    def _action_edit_glossary(self, path: str):
        """260623: 그 PDF(원본/번역본)의 번역 용어집(사이드카)을 불러와 오역 용어 교정(→ 사용자 사전)."""
        if not path:
            return
        import json
        from viewer.study import export_translation as ex
        sc = ex.resolve_glossary_sidecar(path)
        gl = []
        if sc:
            try:
                with open(sc, encoding="utf-8") as f:
                    gl = (json.load(f) or {}).get("glossary") or []
            except Exception:
                gl = []
        if not gl:
            self.status.showMessage(
                f"'{Path(path).stem}' 의 번역 용어집이 없습니다. 먼저 번역을 실행하세요.", 6000)
            return
        from viewer.widgets.glossary_edit_dialog import GlossaryEditDialog
        GlossaryEditDialog(gl, self._prefs, str(path), self).exec()

    def _action_translate_files(self, preselected=None):
        """260621-P0: 여러 PDF 번역 — 병합형 선택 목록(좌 전체/우 대상, 추가·순서·삭제)."""
        if not self._translate_auth_ready_or_warn():
            return
        all_files = []
        try:
            all_files = self.bookmark_tree.all_file_paths()
        except Exception:
            pass
        pre = [p for p in (preselected or []) if p and str(p).lower().endswith(".pdf")]
        from viewer.widgets.translate_files_dialog import TranslateFilesDialog
        # 비모달 — 번역 실행 시 창을 숨기고 백그라운드로 돌릴 수 있게(앱이 참조 보관해 GC 방지)
        dlg = TranslateFilesDialog(all_files, pre, self._prefs, self)
        self._tr_files_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    @staticmethod
    def _dict_src_label(h: dict) -> str:
        """260615-7(P9): 출처 표시 = '구분 / 출처명'(구분 없으면 출처명만)."""
        nm = h.get("src_name") or ""
        cat = (h.get("src_category") or "").strip()
        return f"{cat} / {nm}" if cat else nm

    def _enrich_rows_with_dict(self, rows):
        """260611-102(P2): 각 단어를 계층형 사전(User▶Base)에서 조회해 뜻·예시·참고문헌
        을 우선 적용. 자동(Auto) 뜻은 아래에 유지. 텍스트 기준 중복 제거."""
        try:
            dic = self._study_get_dict()
        except Exception:
            return rows
        for r in rows:
            lemma = (r.get("lemma") or "").strip()
            if not lemma:
                continue
            try:
                hits = dic.lookup(lemma)
            except Exception:
                hits = []
            if not hits:
                continue
            ddefs, dex = [], []
            if any(h.get("src_kind") == "user" for h in hits):
                r["user_edited"] = True       # P5: 사용자 사전 항목 있음(✎ 표시)
            # 260611-105(P6): 전문 용어집(termbase)에 있는 단어는 '전문용어' 등급으로
            #   (빈도 낮다고 무조건 '고급'으로 몰리던 문제 해결). '일반' 사전은 제외.
            if any(h.get("src_is_termbase") for h in hits):
                r["level"] = "전문용어"
            # 260615-8(P10): 그림(첫 매칭 항목의 이미지) 부착
            img = next((h.get("image") for h in hits if (h.get("image") or "").strip()), "")
            if img:
                r["image"] = img
            for h in hits:
                src = self._dict_src_label(h)        # 260615-7(P9): 구분 / 출처명
                ref = (h.get("reference") or h.get("src_reference") or "").strip()
                for fld in ("def_ko", "def_en"):
                    t = (h.get(fld) or "").strip()
                    if t:
                        ddefs.append({"definition": t, "source": src, "ref": ref,
                                      "is_dict": True, "kind": h.get("src_kind")})
                for ex in (h.get("examples") or "").split("\n"):
                    ex = ex.strip()
                    if ex:
                        dex.append({"example": ex, "source": src})
            if not ddefs:
                continue
            r["has_dict"] = True
            # 사전 뜻 먼저 + 기존 자동 뜻, 텍스트 기준 중복 제거
            seen, merged = set(), []
            for d in ddefs + (r.get("definitions") or []):
                key = (d.get("definition") or "").strip()
                if key and key not in seen:
                    seen.add(key); merged.append(d)
            r["definitions"] = merged
            if dex:
                seen_e, merged_e = set(), []
                for e in dex + (r.get("examples") or []):
                    key = (e.get("example") or "").strip()
                    if key and key not in seen_e:
                        seen_e.add(key); merged_e.append(e)
                r["examples"] = merged_e
        return rows

    def _accumulate_and_merge_examples(self, rows):
        """260615-10(P12): 문서 예문(source='book')을 사용자 사전에 축적(구분='내 문서',
        출처명=문서명)하고, 같은 단어의 누적 예문(타 문서 포함)을 병합해 표시.
        예시의 '구분/출처명'은 참고문헌 토글로 표시/숨김."""
        if not self._study_pdf:
            return rows
        try:
            dic = self._study_get_dict()
            doc = Path(self._study_pdf).stem
        except Exception:
            return rows
        cat = "내 문서"
        for r in rows:
            lemma = r.get("lemma", "")
            ex_list = r.get("examples") or []
            book = [(e.get("example") or "").strip() for e in ex_list
                    if e.get("source") == "book"]
            book = [x for x in book if x]
            if book:
                dic.add_examples([{"lemma": lemma, "example": x,
                                   "category": cat, "source": doc} for x in book])
            merged, seen = [], set()
            # 사전(entry) 예문(이미 출처 라벨 있음) 우선
            for e in ex_list:
                if e.get("source") == "book":
                    continue
                t = (e.get("example") or "").strip()
                if t and t not in seen:
                    seen.add(t); merged.append(e)
            # 누적 예문(구분/출처 라벨)
            for a in dic.examples_for(lemma):
                t = (a.get("example") or "").strip()
                if t and t not in seen:
                    seen.add(t)
                    label = (f"{a['category']} / {a['source']}"
                             if a.get("category") else a.get("source", ""))
                    merged.append({"example": t, "source": label})
            if merged:
                r["examples"] = merged
        return rows

    def _maybe_online_enrich(self, rows, page):
        """260615-13(P11b): '인터넷 사전 포함'이 켜져 있으면, 현재 페이지 단어 중
        아직 조회 안 한 것을 백그라운드로 조회·캐시(dict.db)해 패널에 자동 표시."""
        if not self._prefs.get("online_dict_enabled"):
            return
        try:
            dic = self._study_get_dict()
        except Exception:
            return
        todo, seen = [], set()
        for r in rows:
            lm = (r.get("lemma") or "").strip()
            if not lm or lm in seen:
                continue
            seen.add(lm)
            try:
                # 260617-4: 전체 자료(dict.db) 우선 — 보유 자료 있으면 인터넷 조회 생략
                if dic.is_online_fetched(lm) or dic.lookup(lm):
                    continue
            except Exception:
                continue
            todo.append((lm, r.get("lang", "eng")))
        if not todo:
            return
        todo = todo[:30]                  # 페이지당 상한(과도한 호출 방지)
        from viewer.workers import OnlineDictFetchWorker
        w = OnlineDictFetchWorker(todo, dict(self._prefs))
        self._online_worker = w           # GC 방지

        def on_done(results):
            new = self._write_online_results(dic, results)
            if new and self.search_tabs.currentWidget() is self.study_panel \
                    and self.main_view.current_page() == page:
                self._spot_terms_cache = None
                self._refresh_study_panel(page)
        w.done.connect(on_done)
        w.start()

    def _write_online_results(self, dic, results) -> bool:
        """260615-20: 인터넷 조회 결과(제공처별)를 dict.db 에 저장. (지연/재분류 공용)"""
        new = False
        for lemma, lang, provs in results:
            try:
                dic.mark_online_fetched(lemma)
            except Exception:
                pass
            for p in (provs or []):
                try:
                    dic.ensure_online_provider(p["source_id"], p["name"],
                                               p["is_termbase"])
                    kw = {"source_id": p["source_id"], "reference": p["name"],
                          "def_ko": "\n".join(p.get("def_ko", [])),
                          "def_en": "\n".join(p.get("def_en", [])),
                          "examples": "\n".join(e.get("text", "")
                                                for e in p.get("examples", [])),
                          "hanja": p.get("hanja", "")}
                    if str(lang).startswith("ko"):
                        kw["term_ko"] = lemma
                    else:
                        kw["term_en"] = lemma
                    dic.add_entry(**kw); new = True
                except Exception:
                    pass
        return new

    def _action_reclassify_onterm(self, checked: bool = False):
        """260615-20: 온용어 캐시 비우고 다시 분류(재조회) — 용어집(glossary)별로 재저장."""
        dic = self._study_get_dict()
        terms = dic.onterm_cached_terms()
        if not terms:
            QMessageBox.information(self, "온용어 다시 분류",
                                   "재분류할 온용어 캐시가 없습니다.")
            return
        if not (self._prefs.get("onterm_key") or "").strip():
            QMessageBox.information(self, "온용어 다시 분류",
                                   "설정에 온용어 인증키를 먼저 입력하세요.")
            return
        if QMessageBox.question(
                self, "온용어 다시 분류(재조회)",
                f"기존 온용어 캐시({len(terms)}개 단어)를 비우고 인터넷에서 다시 받아\n"
                "용어집(glossary)별로 분류합니다. (인터넷 사용)\n계속할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        dic.clear_onterm_cache(terms)
        op = {"online_dict_enabled": True,
              "stdict_key": self._prefs.get("stdict_key", ""),
              "onterm_key": self._prefs.get("onterm_key", "")}
        from viewer.workers import OnlineDictFetchWorker
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        self.status.showMessage(f"온용어 재조회 중... ({len(terms)}개)")
        w = OnlineDictFetchWorker(terms, op)
        self._onterm_recl_worker = w

        def on_done(results):
            self.progress.setVisible(False)
            n = self._write_online_results(dic, results)
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "온용어 다시 분류",
                                   f"완료: {len(terms)}개 단어를 용어집별로 재분류했습니다.")
        w.done.connect(on_done)
        w.start()

    def _on_study_source_toggled(self, source_id: str, enabled: bool):
        """260611-102(P2): 사전 출처 on/off → 저장 후 패널 갱신."""
        try:
            self._study_get_dict().set_source_enabled(source_id, enabled)
        except Exception:
            pass
        self._spot_terms_cache = None     # 출처 변경 → spotting 목록 무효화
        self._refresh_study_panel(self.main_view.current_page())

    def _get_spot_terms(self):
        """260611-103(P4): 활성 사전의 다단어 표제어 [(norm, entry)] 캐시."""
        if self._spot_terms_cache is not None:
            return self._spot_terms_cache
        from viewer.study.dict_store import normalize_key
        terms = []
        try:
            for e in self._study_get_dict().all_terms():
                tko = (e.get("term_ko") or "").strip()
                ten = (e.get("term_en") or "").strip()
                if " " in tko:
                    terms.append((normalize_key(tko), e))
                if " " in ten:
                    terms.append((normalize_key(ten), e))
        except Exception:
            terms = []
        self._spot_terms_cache = terms
        return terms

    def _spot_page_terms(self, page: int):
        """260611-103(P4): 페이지 본문에서 다단어 전문용어 인식 → (term_rows, rects_map).

        rects_map: {term_key: [(x0,y0,x1,y1), ...]} (표시 좌표; 회전/ dpi 보정 포함)."""
        terms = self._get_spot_terms()
        if not terms or not self._study_pdf:
            return [], {}
        try:
            from viewer.study.study_store import file_key_for
            from viewer.study.term_spotter import spot
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            words = store.get_page_words(fkey, page)
            if not words:
                return [], {}
            dpi = store.get_page_dpi(fkey, page)
            rot, rmat = (self._study_page_rotation(page)
                         if not (dpi and dpi > 0) else (0, None))
            surfaces = [w.get("surface", "") for w in words]
            matches = spot(surfaces, terms)
            # 더 긴 매칭에 완전히 포함된 짧은(하위구) 매칭은 억제 — 가장 구체적 용어 우선
            spans = [(w0, w1) for _e, w0, w1 in matches]
            def _contained(a0, a1):
                return any((b0 <= a0 and b1 >= a1 and (b1 - b0) > (a1 - a0))
                           for (b0, b1) in spans)
            matches = [(e, w0, w1) for (e, w0, w1) in matches if not _contained(w0, w1)]
            groups = {}
            for entry, w0, w1 in matches:
                x0 = y0 = 1e18
                x1 = y1 = -1e18
                for wi in range(w0, w1 + 1):
                    rx0, ry0, rx1, ry1 = self._study_disp_rect(words[wi], dpi, rot, rmat)
                    x0 = min(x0, rx0); y0 = min(y0, ry0)
                    x1 = max(x1, rx1); y1 = max(y1, ry1)
                key = (entry.get("term_ko") or entry.get("term_en") or "").strip()
                if not key:
                    continue
                g = groups.setdefault(key, {"entry": entry, "rects": [], "first": w0})
                g["rects"].append((x0, y0, x1, y1))
                g["first"] = min(g["first"], w0)
            rows, rects_map = [], {}
            for key, g in groups.items():
                e = g["entry"]
                src = self._dict_src_label(e)        # 260615-7(P9): 구분 / 출처명
                ref = (e.get("reference") or e.get("src_reference") or "").strip()
                ddefs = []
                for fld in ("def_ko", "def_en"):
                    t = (e.get(fld) or "").strip()
                    if t:
                        ddefs.append({"definition": t, "source": src, "ref": ref,
                                      "is_dict": True, "kind": e.get("src_kind")})
                ex = [{"example": x.strip(), "source": src}
                      for x in (e.get("examples") or "").split("\n") if x.strip()]
                lang = "kor" if (e.get("term_ko") or "").strip() else "eng"
                rows.append({"lemma": key, "lang": lang, "level": "전문용어",
                             "count": len(g["rects"]), "pos": g["first"],
                             "has_dict": True, "is_term": True,
                             "image": (e.get("image") or ""),
                             "definitions": ddefs, "examples": ex})
                rects_map[key] = g["rects"]
            rows.sort(key=lambda r: r["pos"])
            return rows, rects_map
        except Exception:
            return [], {}

    def _refresh_study_panel(self, page: int):
        """현재 PDF·페이지의 학습단어를 패널에 표시 (데이터 있으면)."""
        if not self._study_pdf:
            return
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            if store.vocab_count(fkey) == 0:
                self.study_panel.set_page(page)
                self.study_panel.set_page_words(page, [])
                self.study_panel.set_status(
                    "이 PDF 의 단어장이 없습니다. [단어장 생성] 을 누르세요.")
                return
            # 260611-104(P5): 사용자 편집은 계층형 사전(dict user)에서 적용 → 여기선 자동만
            rows = store.get_page_study(fkey, page)
            rows = self._apply_word_filter(fkey, rows)        # 표시 필터(전체/선택/날짜/초기)
            rows = self._enrich_rows_with_dict(rows)          # 260611-102(P2): 사전(User▶Base) 적용
            rows = self._accumulate_and_merge_examples(rows)  # 260615-10(P12): 예시 누적·병합
            # 260611-103(P4): 다단어 전문용어 인식 → 별도 행으로 앞에 추가
            term_rows, term_rects = self._spot_page_terms(page)
            self._page_term_rects = term_rects
            rows = term_rows + rows
            self.study_panel.set_filter_dates(self._study_get_user().event_dates(fkey))
            try:
                self.study_panel.set_dict_sources(self._study_get_dict().list_sources())
            except Exception:
                pass
            self.study_panel.set_page_words(page, rows)
            self._maybe_online_enrich(rows, page)   # 260615-13(P11b): 인터넷 사전 자동 보강
            # 호버 영역 설정(메인 뷰어에서 단어 위 → 포인터 변경 + 패널 선택)
            rects = self._compute_word_rects(page, rows)
            # P4: 다단어 용어 영역도 호버/강조에 포함(키=용어 표제어)
            term_hover = [(x0, y0, x1, y1, key)
                          for key, rs in term_rects.items() for (x0, y0, x1, y1) in rs]
            rects = rects + term_hover
            self.main_view.set_hover_words(rects)
            # 본문 강조 옵션 — 단, 읽기 모드에서는 카라오케와 충돌하므로 적용하지 않음
            reading = getattr(self, "read_aloud", None) and self.read_aloud.is_active()
            if self.study_panel.is_auto_highlight() and not reading:
                self.main_view.highlight_word_rects([r[:4] for r in rects], style="all")
            # 자동 읽기: 리더가 넘긴 페이지가 아니고(사용자 이동) 새 페이지면 그 페이지부터 읽기 시작
            if (self.study_panel.is_auto_read() and not self._ar_advancing
                    and page != self._last_read_page):
                self._last_read_page = page
                self._ar_start_page(from_selection=False)
        except Exception as e:
            self.study_panel.set_status(f"단어 조회 오류: {e}")

    def _on_study_page_changed(self, page: int):
        # 단어장 탭이 활성일 때만 갱신(비용 절약). 탭 전환 시에도 1회 갱신됨.
        if self.search_tabs.currentWidget() is self.study_panel:
            self._refresh_study_panel(page)

    # --- 음성 읽기 / 편집 / 내보내기 / 본문강조 (260603) -------------------
    def _ar_start_page(self, from_selection: bool = True) -> None:
        """단어장 자동읽기 — 현재 페이지의 단어를 한 개씩(정렬 순서) 읽기 시작.
        from_selection=True 이고 선택 단어가 있으면 그 위치부터."""
        tts = self._study_get_tts()
        if not tts.available():
            return
        self._ar_items = self.study_panel.shown_lemmas()   # 정렬·필터 반영 순서
        if not self._ar_items:
            self._autoread_timer.stop()
            return
        self._ar_idx = 0
        if from_selection:
            sel = self.study_panel.current_lemma()
            if sel:
                for k, (lm, _l) in enumerate(self._ar_items):
                    if lm == sel:
                        self._ar_idx = k
                        break
        self._ar_speak_current()
        self._autoread_timer.start()

    def _ar_speak_current(self) -> None:
        """현재 인덱스 단어: 단어장 상단으로 + 메인 강조 + (재생내용 포함) 음성."""
        if not (0 <= self._ar_idx < len(self._ar_items)):
            return
        lemma, lang = self._ar_items[self._ar_idx]
        self.study_panel.select_lemma(lemma, to_top=True)   # 단어장 상단 표시
        self._highlight_vocab_word(lemma)                    # 메인 뷰어 강조
        row = next((r for r in self.study_panel._rows if r["lemma"] == lemma), None)
        segs = self._study_read_text_for(row) if row else [(lemma, lang)]
        tts = self._study_get_tts()
        for i, (text, lg) in enumerate(segs):
            tts.speak(text, lg, queue=(i > 0))               # 단어→뜻→예시 순차

    def _highlight_vocab_word(self, lemma: str) -> None:
        """단어장 단어를 메인 뷰어에서 강조(주황). 현재 페이지를 보여줌."""
        page = self.main_view.current_page()
        rects = [r[:4] for r in self._compute_word_rects(page,
                 self.study_panel._shown_rows()) if r[4] == lemma]
        if rects:
            self.main_view.highlight_word_rects(rects, style="read_vocab")

    def _on_autoread_tick(self) -> None:
        if not self.study_panel.is_auto_read():
            self._autoread_timer.stop()
            return
        tts = self._study_get_tts()
        if tts.is_speaking():
            return
        self._ar_idx += 1
        if self._ar_idx < len(self._ar_items):
            self._ar_speak_current()
            return
        # 현재 페이지 단어 끝 → 모드별 처리
        mode = self.study_panel.read_mode()
        from viewer.widgets.study_panel import (
            READ_ONCE, READ_REPEAT, READ_ALL_ONCE, READ_ALL_REPEAT)
        if mode == READ_REPEAT:                  # 현재 페이지 반복
            self._ar_idx = 0
            self._ar_speak_current()
        elif mode in (READ_ALL_ONCE, READ_ALL_REPEAT):
            nxt = self._next_vocab_page(self.main_view.current_page(),
                                        wrap=(mode == READ_ALL_REPEAT))
            if nxt is None:
                self._stop_autoread()
            else:
                self._ar_advancing = True
                self.main_view.go_to_page(nxt)   # 메인 화면=읽는 페이지
                self._refresh_study_panel(nxt)   # 패널 갱신(리더 주도)
                self._ar_advancing = False
                self._last_read_page = nxt
                self._ar_start_page(from_selection=False)
        else:                                    # 1회
            self._stop_autoread()

    def _next_vocab_page(self, cur: int, wrap: bool):
        """cur 다음으로 어휘가 있는 페이지. 없으면 wrap 시 첫 어휘 페이지, 아니면 None."""
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            pages = store.vocab_pages(file_key_for(self._study_pdf))
        except Exception:
            return None
        later = [p for p in pages if p > cur]
        if later:
            return later[0]
        return pages[0] if (wrap and pages) else None

    def _stop_autoread(self) -> None:
        self._autoread_timer.stop()
        try:
            self._study_get_tts().stop()
        except Exception:
            pass
        self.study_panel.set_playing(False)     # ▶ 로 복귀

    def _on_study_autoread(self, on: bool) -> None:
        if on:
            self._last_read_page = self.main_view.current_page()
            self._ar_start_page(from_selection=True)   # 선택 단어부터
        else:                       # 끄면 즉시 정지
            self._stop_autoread()

    def _on_main_word_hovered(self, lemma: str) -> None:
        self.study_panel.select_lemma(lemma)        # 단어장에서 선택(배경 강조)
        if self.study_panel.is_speak_on_select():   # 260606: 본 화면 선택시 읽기
            row = next((r for r in self.study_panel._rows if r["lemma"] == lemma), None)
            lang = row.get("lang", "eng") if row else "eng"
            self._study_get_tts().speak(lemma, lang)

    # --- 표시 필터 / 선택단어 / mp3 (260606) ----------------------------
    def _apply_word_filter(self, fkey: str, rows: list) -> list:
        from viewer.widgets.study_panel import (FILTER_ALL, FILTER_SELECTED, FILTER_ORIG)
        f = self.study_panel.word_filter()
        user = self._study_get_user()
        if f == FILTER_ORIG:
            return rows                                    # 초기: 원본 전체
        if f == FILTER_SELECTED:
            sel = user.selected_set(fkey)
            return [r for r in rows if r["lemma"] in sel]
        if f == FILTER_ALL:
            dele = user.deleted_set(fkey)                  # 현재 삭제 반영
            return [r for r in rows if r["lemma"] not in dele]
        # 날짜 D: 그 날짜까지의 삭제 반영(스냅샷)
        dele = user.deleted_set(fkey, upto_date=f)
        return [r for r in rows if r["lemma"] not in dele]

    def _on_study_cross_page(self, direction: int) -> None:
        """단어장 목록 끝에서 ↑/↓ → 이전/다음 어휘 페이지로, 위치는 마지막/첫 단어."""
        if not self._study_pdf:
            return
        cur = self.main_view.current_page()
        if direction < 0:
            nxt = self._prev_vocab_page(cur)
        else:
            nxt = self._next_vocab_page(cur, wrap=False)
        if nxt is None:
            return
        self.main_view.go_to_page(nxt)
        self._refresh_study_panel(nxt)
        if direction < 0:
            self.study_panel.select_last()      # 위 페이지 → 마지막 단어
        else:
            self.study_panel.select_first()     # 아래 페이지 → 첫 단어

    def _prev_vocab_page(self, cur: int):
        try:
            from viewer.study.study_store import file_key_for
            pages = self._study_get_store().vocab_pages(file_key_for(self._study_pdf))
        except Exception:
            return None
        earlier = [p for p in pages if p < cur]
        return earlier[-1] if earlier else None

    def _on_study_mark_selected(self) -> None:
        lm = self.study_panel.current_lemma()
        if not lm or not self._study_pdf:
            return
        from viewer.study.study_store import file_key_for
        self._study_get_user().add_event(file_key_for(self._study_pdf), lm, "select")
        self.status.showMessage(f"'{lm}' 선택단어로 저장", 2000)
        self.study_panel.select_next()

    def _on_study_delete_word(self) -> None:
        lm = self.study_panel.current_lemma()
        if not lm or not self._study_pdf:
            return
        from viewer.study.study_store import file_key_for
        self._study_get_user().add_event(file_key_for(self._study_pdf), lm, "delete")
        self.status.showMessage(f"'{lm}' 리스트에서 삭제(모든 페이지)", 2000)
        self._refresh_study_panel(self.main_view.current_page())   # 즉시 사라짐

    def _study_read_text_for(self, row: dict) -> list:
        """재생내용 옵션을 반영한 (text,lang) 세그먼트: 단어 + 한/영뜻 + 예시."""
        import re as _re
        lang = row.get("lang", "eng")
        segs = [(row["lemma"], lang)]
        c = self.study_panel.content_read()
        defs = row.get("definitions") or []
        ko = [d["definition"] for d in defs if _re.search(r"[가-힣]", d["definition"])]
        en = [d["definition"] for d in defs if not _re.search(r"[가-힣]", d["definition"])]
        if c["ko"] and ko:
            segs.append((ko[0], "kor"))
        if c["en"] and en:
            segs.append((en[0], "eng"))
        if c["ex"] and row.get("examples"):
            ex = row["examples"][0]["example"]
            segs.append((ex, "kor" if _re.search(r"[가-힣]", ex) else "eng"))
        return segs

    def _on_study_mp3(self) -> None:
        """전체 페이지 단어장을 페이지별 mp3(+가사 lrc)로 폴더에 저장."""
        if not self._study_pdf:
            QMessageBox.information(self, "mp3", "먼저 단어장을 생성하세요.")
            return
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(self._study_pdf)
        if store.vocab_count(fkey) == 0:
            QMessageBox.information(self, "mp3", "단어장이 없습니다.")
            return
        # 읽는 중이면 중지(끊김 방지)
        if getattr(self, "read_aloud", None) and self.read_aloud.is_active():
            self.read_aloud.stop()
        if self.study_panel.is_playing():
            self.study_panel.set_playing(False); self._stop_autoread()

        from PyQt6.QtWidgets import QFileDialog
        stem = Path(self._study_pdf).stem
        parent = QFileDialog.getExistingDirectory(
            self, "mp3 저장 폴더 선택", str(Path(self._study_pdf).parent))
        if not parent:
            return
        from viewer.study.mp3_export import unique_dir
        base = Path(parent) / f"{stem}_MP3"
        resume = False
        if base.exists() and any(base.glob("*.mp3")):
            ret = QMessageBox.question(
                self, "이어서 저장",
                f"'{base.name}' 폴더에 mp3 가 있습니다.\n"
                "기존 폴더에 이어서 저장할까요?\n(예=이미 있는 페이지는 건너뜀, 아니오=새 폴더)")
            if ret == QMessageBox.StandardButton.Yes:
                out_dir, resume = base, True
            else:
                out_dir = unique_dir(base)
        else:
            out_dir = base
        out_dir.mkdir(parents=True, exist_ok=True)

        # 페이지별 세그먼트 구성(현재 표시필터·재생내용 반영)
        try:
            total_pages = self.main_view._doc.page_count
        except Exception:
            total_pages = 999
        width = max(2, len(str(total_pages)))
        overrides = self._study_get_user().all_words()
        jobs = []
        for p in store.vocab_pages(fkey):
            rows = store.get_page_study(fkey, p, user_overrides=overrides)
            rows = self._apply_word_filter(fkey, rows)
            segs = []
            for r in rows:
                segs.extend(self._study_read_text_for(r))
            if not segs:
                continue
            name = f"{stem}_{p + 1:0{width}d}"
            jobs.append((str(out_dir / f"{name}.mp3"), str(out_dir / f"{name}.lrc"), segs))
        if not jobs:
            QMessageBox.information(self, "mp3", "저장할 내용이 없습니다.")
            return

        from viewer.workers import StudyMp3Worker
        self.progress.setVisible(True); self.progress.setRange(0, len(jobs))
        worker = StudyMp3Worker(jobs, rate=self.read_aloud.rate,
                                voice_name=getattr(self.read_aloud, "voice_name", None),
                                resume=resume)

        def on_prog(i, n, msg):
            self.progress.setValue(i); self.status.showMessage(f"mp3: {msg}")

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "mp3 저장 실패", res["error"])
            else:
                self.status.showMessage(
                    f"mp3 저장 완료: {res.get('saved')}/{res.get('total')} 페이지 → "
                    f"{out_dir.name}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    # ===== 260606-3: 메인창 mp3(현재 PDF를 책갈피 기준 분할 저장) =====
    @staticmethod
    def _safe_name(s: str, fallback: str) -> str:
        """260628: 표준 `pathutil.safe_name` 위임(SOT §7.0)."""
        from viewer.pathutil import safe_name
        return safe_name(s, fallback)

    @staticmethod
    def _seg_lang(s: str) -> str:
        import re as _re
        return "ko" if _re.search(r"[가-힣]", s or "") else "en"

    def _doc_sections(self, doc, level: int):
        """get_toc 를 기준으로 (제목, 시작페이지0based, 끝페이지exclusive) 구간 목록.
        분할점 = level 이하 책갈피. 책갈피 없으면 전체 1개 구간."""
        try:
            toc = doc.get_toc(simple=True)      # [lvl, title, page(1based)]
        except Exception:
            toc = []
        total = doc.page_count
        pts = []
        for lv, title, pg in toc:
            if lv <= level:
                p0 = max(0, min(total - 1, int(pg) - 1))
                pts.append((p0, title))
        if not pts:
            return None      # 책갈피 없음 → 전체
        # 시작페이지 정렬·병합(같은 페이지 다중 책갈피는 첫 제목 사용)
        pts.sort(key=lambda x: x[0])
        secs = []
        for i, (p0, title) in enumerate(pts):
            end = pts[i + 1][0] if i + 1 < len(pts) else total
            if end <= p0:
                end = p0 + 1
            secs.append((title, p0, end))
        return secs

    def _on_main_mp3(self, checked: bool = False, view=None) -> None:
        view = view or self.main_view
        path = view.current_file()
        if not path or not str(path).lower().endswith(".pdf"):
            QMessageBox.information(self, "mp3", "먼저 PDF를 표시하세요.")
            return
        try:
            doc = view._doc.doc
        except Exception:
            QMessageBox.information(self, "mp3", "PDF 문서를 찾을 수 없습니다.")
            return

        # 책갈피 위계 선택(존재하는 깊이까지만)
        try:
            toc = doc.get_toc(simple=True)
        except Exception:
            toc = []
        maxlv = min(3, max((lv for lv, *_ in toc), default=0))
        level = 1
        if maxlv >= 1:
            from PyQt6.QtWidgets import QInputDialog
            opts = [f"{i}단계 책갈피 기준" for i in range(1, maxlv + 1)]
            sel, ok = QInputDialog.getItem(
                self, "mp3 분할 기준", "어느 위계의 책갈피로 나눌까요?",
                opts, 0, False)
            if not ok:
                return
            level = opts.index(sel) + 1
        # (책갈피 없으면 전체 1개)

        # 읽는 중이면 중지 + 텍스트 추출 대상을 이 창으로
        if getattr(self, "read_aloud", None) and self.read_aloud.is_active():
            self.read_aloud.stop()
        self.read_aloud.set_target(view)

        from PyQt6.QtWidgets import QFileDialog
        stem = Path(path).stem
        parent = QFileDialog.getExistingDirectory(
            self, "mp3 저장 폴더 선택", str(Path(path).parent))
        if not parent:
            return
        from viewer.study.mp3_export import unique_dir
        base = Path(parent) / f"{stem}_MP3"
        resume = False
        if base.exists() and any(base.glob("*.mp3")):
            ret = QMessageBox.question(
                self, "이어서 저장",
                f"'{base.name}' 폴더에 mp3 가 있습니다.\n"
                "기존 폴더에 이어서 저장할까요?\n(예=이미 있는 파일은 건너뜀, 아니오=새 폴더)")
            if ret == QMessageBox.StandardButton.Yes:
                out_dir, resume = base, True
            else:
                out_dir = unique_dir(base)
        else:
            out_dir = base
        out_dir.mkdir(parents=True, exist_ok=True)

        # 구간 → 세그먼트
        from viewer.widgets.read_aloud import sentences_of
        secs = self._doc_sections(doc, level)
        if secs is None:
            secs = [(stem, 0, doc.page_count)]
        width = max(2, len(str(len(secs))))
        jobs = []
        for i, (title, p0, p1) in enumerate(secs):
            segs = []
            for p in range(p0, p1):
                txt = self.read_aloud._page_text(p)
                for s in sentences_of(txt):
                    segs.append((s, self._seg_lang(s)))
            if not segs:
                continue
            nm = f"{i + 1:0{width}d}_{self._safe_name(title, stem)}"
            jobs.append((str(out_dir / f"{nm}.mp3"),
                         str(out_dir / f"{nm}.lrc"), segs))
        if not jobs:
            QMessageBox.information(self, "mp3", "읽을 본문을 찾지 못했습니다.")
            return

        from viewer.workers import StudyMp3Worker
        self.progress.setVisible(True); self.progress.setRange(0, len(jobs))
        worker = StudyMp3Worker(jobs, rate=self.read_aloud.rate,
                                voice_name=getattr(self.read_aloud, "voice_name", None),
                                resume=resume)

        def on_prog(i, n, msg):
            self.progress.setValue(i); self.status.showMessage(f"mp3: {msg}")

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "mp3 저장 실패", res["error"])
            else:
                self.status.showMessage(
                    f"mp3 저장 완료: {res.get('saved')}/{res.get('total')} 구간 → "
                    f"{out_dir.name}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    def _on_study_speak(self, lemma: str, lang: str) -> None:
        tts = self._study_get_tts()
        if not tts.available():
            self.status.showMessage("음성(SAPI)을 사용할 수 없습니다.", 3000)
            return
        tts.speak(lemma, lang)

    def _on_study_edit(self, lemma: str, lang: str) -> None:
        """260611-104(P5): 선택 단어/용어 편집 → 사용자 사전(dict_entry user) 등록/수정/삭제."""
        self._open_term_editor(lemma=lemma, lang=lang)

    def _on_study_add_term(self) -> None:
        """260611-104(P5): 빈 양식으로 새 용어 등록(＋)."""
        self._open_term_editor(lemma="", lang="kor")

    def _open_term_editor(self, *, lemma: str, lang: str) -> None:
        from viewer.widgets.study_edit_dialog import StudyEditDialog
        dic = self._study_get_dict()
        # 기존 사용자 항목 찾기(있으면 수정, 없으면 base/auto 로 초기값 채워 새로 생성)
        entry, eid = {}, None
        if lemma:
            hits = dic.lookup(lemma)
            uhit = next((h for h in hits if h.get("src_kind") == "user"), None)
            if uhit:
                eid = uhit["entry_id"]
                entry = dict(uhit)
            else:
                base = hits[0] if hits else None
                if base:                       # base 정의를 초기값으로(저장 시 user 로 복제)
                    entry = {"term_ko": base.get("term_ko", ""),
                             "term_en": base.get("term_en", ""),
                             "hanja": base.get("hanja", ""),
                             "def_ko": base.get("def_ko", ""),
                             "def_en": base.get("def_en", ""),
                             "examples": base.get("examples", ""),
                             "reference": base.get("reference", ""),
                             "image": base.get("image", ""),
                             "image_ref": base.get("image_ref", "")}
                else:                          # 사전에 없으면 표제어만 채움 + 자동 뜻 가져오기
                    if str(lang).startswith("ko"):
                        entry["term_ko"] = lemma
                    else:
                        entry["term_en"] = lemma
                    entry.update(self._auto_def_for(lemma))
        online = None
        if self._prefs.get("online_dict_enabled"):
            def online(ko, en):
                from viewer.study.online_dict import lookup_all
                return lookup_all(ko, en, prefs=self._prefs)
        dlg = StudyEditDialog(entry, related_provider=self._dict_related,
                              online_provider=online,
                              allow_delete=(eid is not None),
                              title=("용어 편집 — " + lemma) if lemma else "용어 추가",
                              parent=self)
        if not dlg.exec():
            return
        if dlg.is_deleted() and eid is not None:
            dic.delete_entry(eid)
            self.status.showMessage("용어 삭제(사용자 사전)", 2500)
        else:
            v = dlg.values()
            if eid is not None:
                dic.update_entry(eid, **v)
            else:
                from viewer.study.dict_store import USER_SOURCE_ID
                dic.add_entry(source_id=USER_SOURCE_ID, **v)
            self.status.showMessage(
                f"'{v.get('term_ko') or v.get('term_en')}' 저장(사용자 사전)", 2500)
        self._spot_terms_cache = None
        self._refresh_study_panel(self.main_view.current_page())

    def _dict_related(self, query: str) -> list:
        """편집기 '관련 단어' 공급자 — 사전 부분일치(중복 entry 표제어 1회씩)."""
        try:
            rows = self._study_get_dict().search(query, limit=60)
        except Exception:
            return []
        seen, out = set(), []
        for r in rows:
            key = (r.get("term_ko") or r.get("term_en") or "").strip()
            if key and key not in seen:
                seen.add(key); out.append(r)
        return out

    def _auto_def_for(self, lemma: str) -> dict:
        """자동(study.db) 뜻/예시를 편집 초기값으로 — 한글/영어 칸 자동 배치."""
        out = {}
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf) if self._study_pdf else ""
            page = self.main_view.current_page()
            import re as _re
            for r in store.get_page_study(fkey, page):
                if r["lemma"] != lemma:
                    continue
                ko = [d["definition"] for d in (r.get("definitions") or [])
                      if _re.search(r"[가-힣]", d["definition"])]
                en = [d["definition"] for d in (r.get("definitions") or [])
                      if not _re.search(r"[가-힣]", d["definition"])]
                if ko:
                    out["def_ko"] = "\n".join(ko)
                if en:
                    out["def_en"] = "\n".join(en)
                if r.get("examples"):
                    out["examples"] = "\n".join(e["example"] for e in r["examples"])
                break
        except Exception:
            pass
        return out

    def _on_study_export(self) -> None:
        if not self._study_pdf:
            QMessageBox.information(self, "단어장", "먼저 PDF 를 열고 단어장을 생성하세요.")
            return
        from PyQt6.QtWidgets import QFileDialog
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(self._study_pdf)
        if store.vocab_count(fkey) == 0:
            QMessageBox.information(self, "단어장", "단어장이 없습니다. [단어장 생성] 먼저.")
            return
        default = str(Path(self._study_pdf).with_suffix("")) + "_단어장.docx"
        out, _ = QFileDialog.getSaveFileName(self, "Word 저장", default,
                                             "Word 문서 (*.docx)")
        if not out:
            return
        sp = self.study_panel
        opts = {
            "title": Path(self._study_pdf).stem + " 단어장",
            "levels": sp.selected_levels(),                 # 현재 난이도 필터
            "user_overrides": self._study_get_user().all_words(),
            "sort": sp.sort_combo.currentText(),            # 현재 정렬
            "show_ko": sp.chk_ko.isChecked(),
            "show_en": sp.chk_en.isChecked(),
            "show_ex": sp.chk_ex.isChecked(),
        }
        # 백그라운드 저장(대용량에서 UI 멈춤 방지)
        from viewer.workers import StudyExportWorker
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        worker = StudyExportWorker(store.db_path, fkey, out, opts)

        def on_prog(i, n, _m):
            if n:
                self.progress.setRange(0, n)
                self.progress.setValue(i)

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "Word 저장 실패", res["error"])
            else:
                self.status.showMessage(f"Word 저장 완료: {Path(out).name}", 4000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    def _on_study_auto_highlight(self, on: bool) -> None:
        if on:
            self._refresh_study_panel(self.main_view.current_page())
        else:
            self.main_view.clear_word_highlights()

    def _study_page_rotation(self, page: int):
        """260611-99: 메인뷰에 렌더되는 해당 페이지의 (회전각, 회전행렬).

        PPT→PDF 는 슬라이드를 세로 MediaBox + /Rotate 90 로 저장하는 경우가 많아,
        텍스트 레이어 좌표(get_text)는 '회전 전' 공간이지만 페이지는 회전되어 렌더된다.
        레이어 단어 좌표를 표시 공간으로 옮기기 위한 회전행렬을 돌려준다."""
        try:
            mv = getattr(self, "main_view", None)
            doc = mv._doc.doc if (mv is not None and getattr(mv, "_doc", None)) else None
            if doc is None:
                return 0, None
            p = doc.load_page(int(page))
            return p.rotation, p.rotation_matrix
        except Exception:
            return 0, None

    def _study_disp_rect(self, w, dpi, rot, rmat):
        """단어 저장좌표 → 메인뷰 표시 좌표(PDF point).
        OCR(dpi>0): 렌더 픽셀(회전 반영됨) → 72/dpi 스케일. 레이어(dpi=0): 회전 보정."""
        if dpi and dpi > 0:
            s = 72.0 / dpi
            return (w["x0"] * s, w["y0"] * s, w["x1"] * s, w["y1"] * s)
        if rot and rmat is not None:
            import fitz
            r = fitz.Rect(w["x0"], w["y0"], w["x1"], w["y1"]) * rmat
            r.normalize()
            return (r.x0, r.y0, r.x1, r.y1)
        return (w["x0"], w["y0"], w["x1"], w["y1"])

    def _compute_word_rects(self, page: int, rows: list) -> list:
        """페이지의 단어장 단어 영역 [(x0,y0,x1,y1,lemma)] (PDF point). 호버·본문강조 공용."""
        if not self._study_pdf:
            return []
        try:
            import re as _re
            from viewer.study.study_store import file_key_for
            from viewer.study.vocab import lemma_en
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            lemset = {r["lemma"] for r in rows}
            ko = any(r.get("lang", "eng").startswith("ko") for r in rows)
            words = store.get_page_words(fkey, page)
            dpi = store.get_page_dpi(fkey, page)
            rot, rmat = (self._study_page_rotation(page) if not (dpi and dpi > 0)
                         else (0, None))
            out = []
            for w in words:
                s = (w.get("surface") or "")
                clean = _re.sub(r"[^0-9a-z가-힣]", "", s.lower())
                if not clean:
                    continue
                lemma = None
                if clean in lemset:
                    lemma = clean
                elif lemma_en(clean) in lemset:
                    lemma = lemma_en(clean)
                elif ko:
                    lemma = next((lm for lm in lemset if len(lm) >= 2 and lm in clean), None)
                if lemma:
                    out.append((*self._study_disp_rect(w, dpi, rot, rmat), lemma))
            return out
        except Exception:
            return []

    def _highlight_all_page_words(self, page: int, rows: list) -> None:
        """페이지의 단어장 단어 전체를 메인 뷰어에 옅게 강조(본문강조 옵션)."""
        rects = self._compute_word_rects(page, rows)
        self.main_view.highlight_word_rects([r[:4] for r in rects], style="all")

    def _on_study_word_activated(self, lemma: str, page: int):
        """단어 클릭 → 현재 페이지에서 해당 표제어 위치를 하이라이트.
        260611-103(P4): 다단어 전문용어면 미리 계산된 영역(rects)으로 강조."""
        if not self._study_pdf:
            return
        # P4: 다단어 용어(spotted)면 캐시된 rects 로 바로 강조
        tr = (self._page_term_rects or {}).get(lemma)
        if tr:
            if self.main_view.current_page() != page:
                self.main_view.go_to_page(page)
            self.main_view.highlight_word_rects([r[:4] for r in tr])
            self.status.showMessage(f"'{lemma}' {len(tr)}곳 표시", 2500)
            return
        try:
            from viewer.study.study_store import file_key_for
            from viewer.study.vocab import lemma_en
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            # 현재 메인 페이지가 다르면 이동
            if self.main_view.current_page() != page:
                self.main_view.go_to_page(page)
            words = store.get_page_words(fkey, page)
            dpi = store.get_page_dpi(fkey, page)
            # 260611-99: 레이어(회전 PDF) 좌표 보정 — PPT→PDF /Rotate 대응
            rot, rmat = (self._study_page_rotation(page) if not (dpi and dpi > 0)
                         else (0, None))
            import re as _re
            base = lemma[:-1] if lemma.endswith("다") else lemma
            rects = []
            for w in words:
                s = (w.get("surface") or "")
                # OCR surface 의 따옴표·문장부호 제거 후 비교
                clean = _re.sub(r"[^0-9a-z가-힣]", "", s.lower())
                if not clean:
                    continue
                hit = (clean == lemma or lemma_en(clean) == lemma
                       or (base and base in clean))
                if hit:
                    rects.append(self._study_disp_rect(w, dpi, rot, rmat))
            self.main_view.highlight_word_rects(rects)
            if rects:
                self.status.showMessage(f"'{lemma}' {len(rects)}곳 표시", 2500)
        except Exception as e:
            self.status.showMessage(f"하이라이트 오류: {e}", 3000)

    def _action_import_glossary(self, checked: bool = False):
        """260611-101(P3): 용어집(PDF/CSV) 가져오기 → 전문 용어사전 보강.

        PDF: 'Ÿ' 불릿 `한글명(English)` 형식. CSV: 첫 행 헤더(term_ko/term_en/def_ko/
        def_en/examples/reference/level) 자동 매핑. 기본/사용자 출처로 적재(멱등)."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        fn, _ = QFileDialog.getOpenFileName(
            self, "용어집 파일 선택", "",
            "용어집 (*.pdf *.csv *.tsv *.txt);;모든 파일 (*.*)")
        if not fn:
            return
        name, ok = QInputDialog.getText(
            self, "용어집 이름", "사전(출처) 표시명:",
            text=Path(fn).stem)
        if not ok or not name.strip():
            return
        ref, _ = QInputDialog.getText(
            self, "참고문헌", "참고문헌/출처 인용 (선택):", text=name.strip())
        kind_label, ok = QInputDialog.getItem(
            self, "사전 구분", "어느 사전으로 넣을까요?",
            ["기본 사전(Base)", "내 사전(User)"], 0, False)
        if not ok:
            return
        kind = "user" if kind_label.startswith("내") else "base"
        tb_label, ok = QInputDialog.getItem(
            self, "사전 종류", "용어 난이도 분류:",
            ["전문 용어집(전문용어로 분류)", "일반 사전(난이도 분류 안 함)"], 0, False)
        if not ok:
            return
        is_termbase = tb_label.startswith("전문")
        # 260615-7(P9): 구분(일반/도로/IT 등) — 기존 구분 목록 + 새로 입력
        try:
            cats = sorted({(s.get("category") or "").strip()
                           for s in self._study_get_dict().list_sources()
                           if (s.get("category") or "").strip()})
        except Exception:
            cats = []
        cat_label, ok = QInputDialog.getItem(
            self, "구분", "구분(분류) — 선택하거나 새로 입력:",
            (cats + ["(구분 없음)"]) or ["(구분 없음)"], 0, True)
        if not ok:
            return
        category = "" if cat_label.strip() in ("", "(구분 없음)") else cat_label.strip()
        import re as _re
        sid = _re.sub(r"[^0-9a-z]+", "_", Path(fn).stem.lower()).strip("_") or "glossary"
        try:
            from viewer.study.glossary_import import import_glossary_file
            store = self._study_get_dict()
            mapping = {f: f for f in ("term_ko", "term_en", "def_ko", "def_en",
                                      "examples", "reference", "level", "hanja", "image")}
            n = import_glossary_file(store, fn, source_id=sid, name=name.strip(),
                                     reference=ref.strip(), kind=kind,
                                     csv_mapping=mapping, is_termbase=is_termbase,
                                     category=category)
            self._spot_terms_cache = None      # 용어 추가 → spotting 목록 무효화
            QMessageBox.information(
                self, "용어집 가져오기",
                f"'{name.strip()}' — {n}개 용어를 {kind_label} 에 적재했습니다.")
            self.status.showMessage(f"용어집 적재: {name.strip()} ({n}개)", 4000)
            self._refresh_study_panel(self.main_view.current_page())
        except Exception as e:
            QMessageBox.warning(self, "용어집 가져오기", f"실패: {e}")

    def _action_save_csv_sample(self, checked: bool = False):
        """260615-6: ⑦ 사용자 CSV 사전 양식 예제를 저장(헤더+예시 행)."""
        from PyQt6.QtWidgets import QFileDialog
        from viewer.resources_path import resource_path
        import shutil
        src = resource_path("dict/sample_glossary.csv")
        out, _ = QFileDialog.getSaveFileName(
            self, "용어집 CSV 양식 예제 저장", "용어집_양식_예제.csv", "CSV (*.csv)")
        if not out:
            return
        try:
            if src:
                shutil.copyfile(src, out)
            else:   # 동봉본이 없으면 헤더만이라도 기록
                Path(out).write_text(
                    "term_ko,term_en,def_ko,def_en,examples,reference,level,hanja\n",
                    encoding="utf-8-sig")
            QMessageBox.information(
                self, "CSV 양식 예제",
                f"양식 예제를 저장했습니다.\n{out}\n\n"
                "열: term_ko(한글표제어), term_en(영문표제어), def_ko(한글뜻), "
                "def_en(영어뜻), examples(예시), reference(참고문헌), level(난이도), hanja(한자)\n"
                "엑셀에서 편집 후 '용어집 가져오기'로 불러오세요.")
        except Exception as e:
            QMessageBox.warning(self, "CSV 양식 예제", f"저장 실패: {e}")

    def _action_sanitize_dict(self, checked: bool = False):
        """260615-17: 사전(dict.db)의 HTML 마크업(&#44;·<strong> 등) 일괄 제거."""
        try:
            n = self._study_get_dict().sanitize_markup()
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "사전 정리",
                                   f"HTML 마크업을 정리했습니다. (변경 {n}개 항목)")
        except Exception as e:
            QMessageBox.warning(self, "사전 정리", f"실패: {e}")

    def _action_backup_dict(self, checked: bool = False):
        """260615-15: 사전 백업 — dict.db + dict_images/ 를 zip 으로(여러 PC 이전·동기화)."""
        from PyQt6.QtWidgets import QFileDialog
        import zipfile
        from viewer.study.dict_store import default_db_path
        from viewer.study.image_fetch import dict_images_dir
        out, _ = QFileDialog.getSaveFileName(
            self, "사전 백업 저장", "PolyPDF_사전백업.zip", "ZIP (*.zip)")
        if not out:
            return
        # dict.db 일관성 위해 연결 닫기(이후 지연 재오픈)
        try:
            if getattr(self, "_dict_store", None) is not None:
                self._dict_store.close(); self._dict_store = None
        except Exception:
            pass
        try:
            dbp = default_db_path()
            imgs = dict_images_dir()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                if dbp.exists():
                    z.write(str(dbp), "dict.db")
                for f in imgs.glob("*"):
                    if f.is_file():
                        z.write(str(f), f"dict_images/{f.name}")
            QMessageBox.information(self, "사전 백업",
                                   f"사전(용어·그림·인터넷 캐시)을 백업했습니다.\n{out}\n\n"
                                   "다른 PC에서 '사전 복원'으로 불러오세요.")
        except Exception as e:
            QMessageBox.warning(self, "사전 백업", f"실패: {e}")

    def _action_restore_dict(self, checked: bool = False):
        """260615-15: 사전 복원 — 백업 zip 의 dict.db + dict_images/ 로 교체(기존은 .bak)."""
        from PyQt6.QtWidgets import QFileDialog
        import zipfile, shutil
        from viewer.study.dict_store import default_db_path
        from viewer.study.image_fetch import dict_images_dir
        fn, _ = QFileDialog.getOpenFileName(
            self, "사전 백업 파일 선택", "", "ZIP (*.zip)")
        if not fn:
            return
        if QMessageBox.question(
                self, "사전 복원",
                "현재 사전(용어·그림·인터넷 캐시)을 백업 내용으로 교체할까요?\n"
                "(기존 dict.db 는 dict.db.bak 으로 보관)") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            if getattr(self, "_dict_store", None) is not None:
                self._dict_store.close(); self._dict_store = None
        except Exception:
            pass
        try:
            dbp = default_db_path()
            imgs = dict_images_dir()
            if dbp.exists():
                shutil.copyfile(str(dbp), str(dbp) + ".bak")
            with zipfile.ZipFile(fn, "r") as z:
                names = z.namelist()
                if "dict.db" in names:
                    with z.open("dict.db") as src, open(dbp, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                for nm in names:
                    if nm.startswith("dict_images/") and not nm.endswith("/"):
                        target = imgs / Path(nm).name
                        with z.open(nm) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "사전 복원",
                                   "사전을 복원했습니다. (기존 dict.db → dict.db.bak)")
        except Exception as e:
            QMessageBox.warning(self, "사전 복원", f"실패: {e}")

    def _action_online_enrich(self, checked: bool = False):
        """260615-15: 인터넷 사전 보강(이어하기) — 재OCR 없이 현재 PDF 단어를 온라인 조회·캐시.
        중간에 끊겨도 online_fetched 로 이미 받은 단어는 건너뜀."""
        if not self._study_pdf or not Path(self._study_pdf).exists():
            QMessageBox.information(self, "인터넷 사전 보강", "먼저 단어장이 있는 PDF 를 여세요.")
            return
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        if store.vocab_count(file_key_for(self._study_pdf)) == 0:
            QMessageBox.information(self, "인터넷 사전 보강",
                                   "이 PDF 의 단어장이 없습니다. 먼저 [단어장 생성].")
            return
        # 옵션이 꺼져 있어도 이 동작은 명시적이므로 강제로 켜서 조회
        op = {"online_dict_enabled": True,
              "stdict_key": self._prefs.get("stdict_key", ""),
              "onterm_key": self._prefs.get("onterm_key", "")}
        path = Path(self._study_pdf)
        self.study_panel.set_building(True)
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        worker = StudyBuildWorker(path, lang=self._detect_study_lang(path),
                                  online_prefs=op, online_only=True)
        self._study_worker = worker

        def on_prog(done, total, m):
            if total:
                self.progress.setRange(0, total); self.progress.setValue(done)
            self.status.showMessage(m)

        def on_done(summary):
            self.study_panel.set_building(False)
            self.progress.setVisible(False)
            if summary.get("error"):
                QMessageBox.warning(self, "인터넷 사전 보강", f"실패: {summary['error']}")
                return
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            self.status.showMessage(
                f"인터넷 사전 보강 완료: {summary.get('online', 0)}개 추가", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        worker.error.connect(lambda e: self.status.showMessage(f"인터넷 사전 보강 오류: {e}", 5000))
        run_in_thread(worker, self._study_threads)

    def _action_export_dict(self, checked: bool = False):
        """260611-106(P7): 사전(사용자/기본) → TBX·CSV 내보내기(상호운용)."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        try:
            dic = self._study_get_dict()
            srcs = dic.list_sources()
        except Exception as e:
            QMessageBox.warning(self, "사전 내보내기", f"사전 열기 실패: {e}")
            return
        if not srcs:
            QMessageBox.information(self, "사전 내보내기", "내보낼 사전이 없습니다.")
            return
        # 출처 선택(전체 + 개별)
        labels = ["전체"] + [f"{s.get('name', s['source_id'])} ({s.get('n_entries', 0)})"
                             for s in srcs]
        pick, ok = QInputDialog.getItem(self, "내보낼 사전", "출처:", labels, 0, False)
        if not ok:
            return
        source_id = None if pick == "전체" else srcs[labels.index(pick) - 1]["source_id"]
        fmt, ok = QInputDialog.getItem(
            self, "형식", "내보내기 형식:",
            ["TBX (ISO 30042)", "CSV (엑셀)"], 0, False)
        if not ok:
            return
        is_tbx = fmt.startswith("TBX")
        ext = "tbx" if is_tbx else "csv"
        default = str(Path(self._study_pdf).with_suffix("")) + f"_용어사전.{ext}" \
            if self._study_pdf else f"용어사전.{ext}"
        out, _ = QFileDialog.getSaveFileName(
            self, "사전 내보내기", default,
            ("TBX (*.tbx)" if is_tbx else "CSV (*.csv)"))
        if not out:
            return
        try:
            from viewer.study import dict_export
            n = (dict_export.export_tbx(dic, out, source_id=source_id) if is_tbx
                 else dict_export.export_csv(dic, out, source_id=source_id))
            QMessageBox.information(self, "사전 내보내기",
                                   f"{n}개 항목을 내보냈습니다.\n{out}")
            self.status.showMessage(f"사전 내보내기 완료: {Path(out).name} ({n}개)", 4000)
        except Exception as e:
            QMessageBox.warning(self, "사전 내보내기", f"실패: {e}")

    def _action_build_study(self, checked: bool = False, also_bookmarks: bool = False):
        """현재 PDF 를 OCR·어휘 분석해 study.db 생성 (백그라운드).
        also_bookmarks=True 면 같은 OCR 결과(study.db)를 재사용해 책갈피까지 동시 생성."""
        if not self._study_pdf or not Path(self._study_pdf).exists():
            QMessageBox.information(self, "단어장", "먼저 PDF 를 여세요.")
            return
        path = Path(self._study_pdf)
        lang = self._detect_study_lang(path)
        what = "단어장·책갈피 동시 생성" if also_bookmarks else "단어장 생성"
        extra = ("\n(OCR 1회로 단어장과 책갈피를 함께 만듭니다 — 따로 만드는 것보다 빠릅니다.)"
                 if also_bookmarks else "")
        # 260615-6: ① 이미 단어장이 있으면 '다시 만들기' 를 묻고, 예 → 기존 캐시 삭제 후 재생성
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(path)
        already = store.vocab_count(fkey) > 0 or len(store.done_pages(fkey)) > 0
        if already:
            msg = (f"'{path.name}' 의 단어장이 이미 있습니다.\n"
                   f"기존 내용을 삭제하고 다시 만들까요?\n(감지 언어: {lang}){extra}")
            if QMessageBox.question(self, what + " — 다시 만들기", msg) \
                    != QMessageBox.StandardButton.Yes:
                return
            store.clear_file(fkey)        # 재생성 위해 기존 OCR·어휘 캐시 삭제
        else:
            msg = (f"'{path.name}' 을(를) OCR·분석합니다.\n"
                   f"감지 언어: {lang}.  분량에 따라 수 분 걸릴 수 있습니다.{extra}\n계속할까요?")
            if QMessageBox.question(self, what, msg) != QMessageBox.StandardButton.Yes:
                return
        self.study_panel.set_building(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)        # busy until first progress
        # 260615-14: 인터넷 사전 포함 옵션이면 빌드 시 각 단어를 온라인 조회·캐시
        online_prefs = {k: self._prefs.get(k) for k in
                        ("online_dict_enabled", "stdict_key",
                         "onterm_key")}
        worker = StudyBuildWorker(path, lang=lang, online_prefs=online_prefs)
        self._study_worker = worker

        def on_prog(done, total, m):
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
            self.status.showMessage(f"{what}: {m} ({done}/{total})")

        def on_done(summary):
            self.study_panel.set_building(False)
            self.progress.setVisible(False)
            if summary.get("error"):
                QMessageBox.warning(self, "단어장", f"실패: {summary['error']}")
                self.status.showMessage("단어장 생성 실패", 4000)
                return
            v = (summary.get("vocab") or {}).get("vocab", 0)
            nb = 0
            if also_bookmarks:
                nb = self._build_bookmarks_from_study(path)   # 재OCR 없이 책갈피
            self.search_tabs.setCurrentWidget(self.study_panel)
            self._refresh_study_panel(self.main_view.current_page())
            tail = f", 책갈피 {nb}개" if also_bookmarks else ""
            on = summary.get("online") or 0
            on_tail = f", 인터넷 사전 {on}개" if on else ""
            self.status.showMessage(
                f"{what} 완료: {summary.get('done')}p, 어휘 {v}{tail}{on_tail}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        worker.error.connect(lambda e: self.status.showMessage(f"단어장 오류: {e}", 5000))
        run_in_thread(worker, self._study_threads)

    def _build_bookmarks_from_study(self, path) -> int:
        """260606-11(시간단축): 방금 만든 study.db 의 OCR 단어좌표를 재사용해
        책갈피(헤딩)를 추출 → 책갈피 트리에 추가(재OCR 없음). 추가 개수 반환."""
        try:
            import fitz
            from viewer.study.study_store import file_key_for
            from viewer.study.ocr_headings import extract_headings_from_store
            store = self._study_get_store()
            fk = file_key_for(path)
            doc = fitz.open(str(path))
            try:
                total = doc.page_count
            finally:
                doc.close()
            bms = extract_headings_from_store(store, fk, total, use_font_auto=False)
            for b in bms:
                self.bookmark_tree.add_bookmark(str(path), b.page, b.title)
            if bms:
                self.status.showMessage(
                    f"책갈피 {len(bms)}개 추가됨 — 책갈피창 편집(✏)에서 저장(💾)하면 PDF에 반영", 7000)
            return len(bms)
        except Exception:
            return 0
