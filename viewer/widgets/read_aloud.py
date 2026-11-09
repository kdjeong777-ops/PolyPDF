"""본문 읽어주기(Read Aloud) — 메인 뷰어 페이지 내용을 음성으로, 자동 페이지 진행.
머리말/꼬리말·표·수식·그림(텍스트 적은 줄) 생략. 범위·성우·빠르기·반복 옵션.
260603 사용자 요청.
"""
from __future__ import annotations

import re
from viewer.i18n import tr, tr_noop          # 261008: 화면 문구(다국어 SOT §6)
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QToolButton, QMenu

_HANGUL = re.compile(r"[가-힣]")
_LETTER = re.compile(r"[가-힣A-Za-z]")
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+|(?<=다\.)\s*|(?<=요\.)\s*")
RATES = [(tr_noop("느림"), -4), (tr_noop("보통"), 0), (tr_noop("빠름"), 4), (tr_noop("매우 빠름"), 8)]


def clean_lines_for_reading(text: str) -> list[str]:
    """읽을 수 있는 줄만 추출 — 표/수식/페이지번호/머리말 류(글자 비율 낮은 줄) 제외."""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if len(s) < 3:
            continue
        if s.isdigit():                       # 페이지 번호
            continue
        non_space = re.sub(r"\s", "", s)
        if not non_space:
            continue
        letters = len(_LETTER.findall(non_space))
        if letters / len(non_space) < 0.55:   # 표·수식·기호 위주 줄
            continue
        out.append(s)
    return out


def sentences_of(text: str) -> list[str]:
    lines = clean_lines_for_reading(text)
    joined = " ".join(lines)
    sents = [s.strip() for s in _SENT.split(joined) if s and s.strip()]
    # 너무 짧은 조각 병합
    merged: list[str] = []
    for s in sents:
        if merged and len(s) < 6:
            merged[-1] += " " + s
        else:
            merged.append(s)
    return merged



_SENT_END_RE = re.compile(r'[.?!。？！]"?\s*$')
class ReadAloud(QObject):
    """본문 읽기 상태 머신. mw 에서 main_view·study store·tts 접근."""
    stateChanged = pyqtSignal(bool)
    # 261108-26(SOT §1.5): 재생 구간이 바뀌면(메뉴·설정 복원·다른 창 단추) 모든 읽기 단추 글자·체크가 따라온다
    modeChanged = pyqtSignal(str)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self._view = None           # 260606-11: 읽기 대상 메인뷰(2분할 창별). 없으면 활성창
        self._pane = 0
        self._mode = "전체"         # 1회/연속(현재페이지) · 전체/전체연속(현재→끝) — `mode` 속성으로만 바꾼다
        self.repeat = False
        self.rate = 0
        self.voice_name = None      # 성우(빈값=언어 자동). 본화면·단어장 공유
        self._active = False
        self._pages: list[int] = []
        self._pi = 0
        # 261109-6(SOT §1.11 '아직 OCR 이 안 된 쪽'): [OCR 하고 읽기] 뒤 결과가 아직 없는 쪽 · 지금 기다리는 쪽
        self._ocr_wait: set = set()
        self._ocr_waiting = None
        self._sents: list[str] = []
        self._si = 0
        self._owords: list = []      # 현재 페이지 ocr_word (읽기순서, bbox)
        self._owptr = 0              # 카라오케 매칭 포인터
        self._oscale = 1.0
        self._last_span = None
        self._spk_started = 0.0       # 260618-26: 현재 문장 발화 시작 시각
        self._cur_min_dur = 0.0       # 260618-26: 현재 문장 최소 보장 발화시간
        # 260618-29: 읽는 중 사용자가 페이지를 바꾸면 그 페이지부터 다시 읽기.
        #   _reading_page=리더가 현재 읽는 페이지(리더 자신의 페이지 넘김과 사용자 이동 구분).
        self._reading_page = -1
        self._srects: list = []      # 260911: 문장마다의 자리(텍스트 창과 같은 범위)
        self._para_end: list = []    # 261108-25(SOT §1.8 의 1): 문장마다 '그 줄 묶음(문단)의 끝인가'
        self._pause_until = 0.0      # 261108-25: 문장이 끝난 뒤 다음 문장까지 쉬는 끝 시각
        self._home_page = None       # 260911: 읽기를 시작한 쪽(끝나면 여기로)
        self._pending_restart_page = None
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(250)      # 빠른 연속 이동은 멈춘 뒤 1회만 재시작
        self._restart_timer.timeout.connect(self._do_restart)
        self._timer = QTimer(self)
        self._timer.setInterval(120)     # 카라오케 추종 위해 빠르게 폴링
        self._timer.timeout.connect(self._tick)

    @property
    def _v(self):
        """현재 읽기 대상 뷰(설정됐으면 그 창, 아니면 활성 창).
        260618-7: 과거 else 분기가 self._v 자기참조로 무한재귀였음 → 활성 메인뷰 반환으로 수정."""
        if self._view is not None:
            return self._view
        return self.mw.main_view

    def set_target(self, view, pane: int = 0):
        self._view = view
        self._pane = int(pane)

    # --- 엔진 (261108-28, 영상·음성 SOT §1.10) ---
    def _tts(self):
        """지금 읽기 엔진 — 읽는 중에는 시작할 때 고른 것(자연 음성 / SAPI), 아니면 설정대로 고른다."""
        eng = getattr(self, "_eng", None)
        if self._active and eng is not None:
            return eng
        from viewer.study import tts_engine
        return tts_engine.reader_for(self.mw)

    def _engines(self):
        """빠르기·멈춤은 SAPI 와 (만들어 둔) 자연 음성 둘 다에."""
        out = [self.mw._study_get_tts()]
        nr = getattr(self.mw, "_neural_reader", None)
        if nr is not None:
            out.append(nr)
        return out

    # --- 옵션 ---
    def set_rate(self, r: int):
        self.rate = r
        for e in self._engines():
            e.set_rate(r)

    def set_voice(self, name: Optional[str]):
        self.voice_name = name or None
        self.mw._study_get_tts().set_voice_name(name)

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, v: str) -> None:
        """261108-26(사용자 보고 "'전체' 는 전체 페이지를 읽는 건데, 현재 페이지만 읽고 마쳐"):
        설정 복원(`_restore_settings`)은 단추를 만든 **뒤에** 저장된 구간을 넣는다. 종전에는 값만 바뀌고
        단추 글자·메뉴 체크는 만들 때의 기본값('전체')에 남아, 단추엔 '전체' 가 보이는데 '1회' 로 읽었다.
        이제 값이 바뀌면 `modeChanged` 로 모든 단추가 따라온다."""
        v = str(v or "전체")
        changed = (v != getattr(self, "_mode", None))
        self._mode = v
        if changed:
            self.modeChanged.emit(v)

    def is_active(self) -> bool:
        return self._active

    def jump_to_point(self, px: float, py: float) -> bool:
        """현재 페이지에서 (px,py) PDF point 가 속한 문장부터 다시 읽기. 읽는 중에만."""
        if not self._active or not self._owords:
            return False
        s = self._oscale
        # 261108-29(SOT §1.9): 찍은 점이 **상자 안**인 낱말이 먼저, 없으면 상자까지 가장 가까운 낱말.
        #   종전에는 상자 **가운데**까지의 거리라, 한글 OCR 처럼 글자 하나짜리 작은 상자가 촘촘하면
        #   옆 줄의 긴 낱말보다 멀게 재어지기도 했다. 읽는 문장에 맞춘 낱말(`_wsent`)만 고른다.
        wsent = getattr(self, "_wsent", None) or [None] * len(self._owords)
        target, bestd = None, 1e18
        for j, w in enumerate(self._owords):
            if j >= len(wsent) or wsent[j] is None:
                continue
            x0, y0, x1, y1 = w["x0"] * s, w["y0"] * s, w["x1"] * s, w["y1"] * s
            dx = max(x0 - px, 0.0, px - x1)
            dy = max(y0 - py, 0.0, py - y1)
            d = dx * dx + dy * dy
            if d < bestd:
                bestd, target = d, wsent[j]
        if target is None:                # 어느 낱말도 읽는 글에 맞지 않았다
            return False
        self.mw._study_get_tts().stop()
        self._si = target
        self._speak_cur()
        return True

    # --- 제어 ---
    def toggle(self):
        self.stop() if self._active else self.start()

    # --- 261109-6(SOT §1.11): OCR 이 아직 안 된 쪽은 건너뛰지 않고 기다린다 ---
    def wait_for_ocr(self, pages) -> None:
        """[OCR 하고 읽기] 로 시작한 읽기 — `pages` 는 OCR 결과가 아직 오지 않은 쪽들."""
        self._ocr_wait = {int(p) for p in (pages or ())}

    def ocr_page_ready(self, page: int) -> None:
        """그 쪽 OCR 결과가 왔다 — 그 쪽에서 기다리던 중이면 이제 읽는다."""
        self._ocr_wait.discard(int(page))
        self._resume_ocr_wait()

    def ocr_wait_end(self) -> None:
        """OCR 이 끝났다(또는 중단·실패) — 기다림을 모두 풀고 남은 쪽은 있는 글로 읽는다."""
        self._ocr_wait = set()
        self._resume_ocr_wait()

    def _resume_ocr_wait(self) -> None:
        w = self._ocr_waiting
        if w is None or w in self._ocr_wait:
            return
        self._ocr_waiting = None
        if self._active and self._pages and self._pages[self._pi] == w:
            self._load_page()

    def start(self):
        self._eng = None
        self._ocr_wait = set()
        self._ocr_waiting = None
        tts = self._tts()
        if not tts.available():
            self.mw.status.showMessage(tr("음성(SAPI)을 사용할 수 없습니다."), 3000)
            return
        mv = self._v
        if mv.current_file() is None:
            self.mw.status.showMessage(tr("먼저 PDF 를 여세요."), 3000)
            return
        start_page = mv.current_page()
        total = self._page_count()
        self.repeat = self.mode in ("연속", "전체연속")
        # 260911(사용자 지시): 다 읽고 나면 **누른 자리로 돌려놓는다**(SOT §1.1).
        self._home_page = start_page
        self._pages, self._pi = self._page_plan(start_page)
        tts.set_rate(self.rate)
        self._eng = tts                    # 261108-28: 읽는 동안 이 엔진으로(설정을 바꿔도 다음 읽기부터)
        warm = getattr(tts, "warm_up", None)
        if callable(warm):
            warm()                         # 자연 음성 — 모델을 배경에서 미리 싣는다(첫 소리 줄이기)
        self._active = True
        self.stateChanged.emit(True)
        # 읽기 중에는 '본문강조'(단어장 밑줄, 261103-4)를 끄고 카라오케(읽는 단어)만 표시
        try:
            self._v.clear_word_highlights()
            self.mw._clear_vocab_marks()
        except Exception:
            pass
        self._load_page()
        self._timer.start()

    def stop(self):
        self._active = False
        self._timer.stop()
        self._restart_timer.stop()        # 260618-29
        self._pending_restart_page = None
        self._reading_page = -1
        self._ocr_wait = set()               # 261109-6: ■ 면 OCR 기다림도 버린다
        self._ocr_waiting = None
        for e in self._engines():          # 261108-28: SAPI·자연 음성 둘 다 멈춘다(대기열 버리기)
            try:
                e.stop()
            except Exception:
                pass
        self.stateChanged.emit(False)
        # 카라오케 강조 제거 + (옵션이면) 본문강조 복원
        try:
            self._v.clear_word_highlights()
            if self.mw._vocab_marks_on():        # 261103-4: 단어장 창이 보일 때만 밑줄 복원
                self.mw._refresh_study_panel(self._v.current_page())
        except Exception:
            pass

    # --- 내부 ---
    def _page_count(self) -> int:
        try:
            return self._v._doc.page_count
        except Exception:
            return 1

    def _page_plan(self, start: int):
        """모드에 맞는 (읽을 쪽 목록, 시작 자리) (영상·음성 SOT §1.5).

        | 모드 | 첫 바퀴 | 끝나면 |
        | --- | --- | --- |
        | 1회 | 지금 쪽 | 멈춘다 |
        | 연속 | 지금 쪽 | 그 쪽을 다시 |
        | 전체 | 지금 쪽 ~ 마지막 쪽 | 멈추고 시작한 쪽으로 |
        | 전체연속 | 지금 쪽 ~ 마지막 쪽 | 1쪽 ~ 끝을 되풀이(`_wrap_pages`) |

        260911(사용자 지시로 확정): 전체·전체연속의 **첫 바퀴는 지금 쪽부터 끝까지**다.
        누르자마자 1쪽으로 뛰지 않게 — 보던 자리에서 이어 읽는 것이 자연스럽다.
        **전체연속은 한 바퀴를 돈 뒤부터 1쪽~끝을 되풀이**한다(`_wrap_pages`).
        """
        total = max(1, self._page_count())
        start = max(0, min(int(start), total - 1))
        if self.mode in ("전체", "전체연속"):
            return list(range(start, total)), 0
        return [start], 0

    def _wrap_pages(self) -> list:
        """되풀이 두 바퀴째부터의 쪽 목록 (영상·음성 SOT §1.5).

        전체연속은 '지금 쪽~끝' 을 한 번 읽은 뒤에는 **1쪽부터** 되풀이한다 —
        그러지 않으면 시작 쪽 앞은 영영 안 읽힌다. 연속(한 쪽 반복)은 목록이
        한 쪽뿐이라 그대로다.
        """
        if self.mode == "전체연속":
            return list(range(max(1, self._page_count())))
        return list(self._pages)

    def _load_page(self):
        if not self._pages:
            self.stop(); return
        page = self._pages[self._pi]
        self._reading_page = page       # 260618-29: 리더가 읽는 페이지(사용자 이동 구분용)
        self._v.go_to_page(page)        # 읽는 페이지로 화면 자동 이동
        if page in self._ocr_wait:
            # 261109-6(SOT §1.11): 아직 OCR 결과가 없다 — 빈 쪽으로 보고 넘기지 않고 기다린다(`_tick` 은 시각만 본다)
            self._ocr_waiting = page
            self._sents, self._srects, self._para_end = [], [], []
            self._si = 0
            try:
                self.mw.status.showMessage(tr("OCR 이 끝나기를 기다리는 중: {page}쪽").format(page=page + 1), 5000)
            except Exception:
                pass
            return
        self._ocr_waiting = None
        # 260911(SOT §1.3): 글과 **자리**를 함께 얻는다 — 강조 범위를 텍스트 창과 맞추려면
        #   낱말이 아니라 줄의 자리가 필요하다. 자리를 못 얻으면 종전 길로 물러선다.
        units = self._page_units(page)
        if units:
            self._sents = [u[0] for u in units]
            self._srects = [u[1] for u in units]
            self._para_end = [bool(u[2]) if len(u) > 2 else False for u in units]
        else:
            self._sents = sentences_of(self._page_text(page))
            self._srects = []
            self._para_end = []
        self._pause_until = 0.0
        self._si = 0
        self._load_owords(page)
        self._build_spans()
        self._speak_cur()

    def on_page_changed(self, page: int):
        """260618-29: 읽는 중 '읽기 대상 창'의 페이지가 바뀌면 호출. 리더 자신이 넘긴
        페이지면 무시, 사용자가 다른 페이지로 이동했으면 그 페이지부터 다시 읽는다.
        빠른 연속 이동은 디바운스(250ms) 후 1회만 재시작."""
        if not self._active:
            return
        if page == self._reading_page:
            return                              # 리더가 넘긴 페이지 — 무시
        self._pending_restart_page = page
        self._restart_timer.start()

    def _do_restart(self):
        if not self._active:
            return
        page = self._pending_restart_page
        self._pending_restart_page = None
        if page is None or page == self._reading_page:
            return
        self._restart_at_page(page)

    def _restart_at_page(self, page: int):
        """현재 읽기 모드·범위를 유지한 채 page 부터 다시 읽기(기존 발화 중단)."""
        try:
            self._tts().stop()
        except Exception:
            pass
        self._pages, self._pi = self._page_plan(page)
        self._load_page()

    def _load_owords(self, page: int):
        """현재 페이지 단어 좌표(읽기순서) 로드 — 카라오케 하이라이트용."""
        self._owords, self._owptr, self._oscale = [], 0, 1.0
        try:
            from viewer.study.study_store import file_key_for
            cur = self._v.current_file()
            if not cur:
                return
            store = self.mw._study_get_store()
            fk = file_key_for(cur)
            self._owords = store.get_page_words(fk, page)
            dpi = store.get_page_dpi(fk, page)
            self._oscale = (72.0 / dpi) if dpi > 0 else 1.0
            if not self._owords:
                # 260911(사용자 보고 "첫 쪽만 강조되고 둘째 쪽부터는 안 된다",
                #   영상·음성 SOT §1.6): `study.db` 에는 **OCR 한 쪽만** 낱말이 있다.
                #   [OCR 다시 읽기] 는 글자층이 멀쩡한 쪽을 건너뛰므로(텍스트 창
                #   §3.1.2), 디지털 PDF 는 그림이 섞인 쪽만 낱말이 남는다. 그 쪽만
                #   강조되고 나머지는 조용히 안 됐다.
                #   글자층이 있으면 **그 낱말 상자**를 쓰면 된다 — 좌표가 이미 pt 다.
                self._owords = self._layer_words(page)
                self._oscale = 1.0
            # 260911(SOT §3.6.9): 글을 단 차례로 읽으니 **낱말도 같은 차례**여야 한다.
            #   글은 단 차례인데 낱말이 OCR 차례면 강조가 엉뚱한 자리로 튄다.
            try:
                from viewer import text_extract2 as tx
                pg = self._v._doc.doc.load_page(int(page))
                self._owords = tx.words_in_reading_order(
                    self._owords, dpi=int(dpi or 0), page=pg)
            except Exception:
                pass
        except Exception:
            self._owords = []

    def _layer_words(self, page: int) -> list:
        """PDF 글자층의 낱말 상자 (영상·음성 SOT §1.6). 없으면 빈 목록.

        좌표는 이미 pt 라 `_oscale = 1.0` 이다. `study.db` 에 OCR 낱말이 없는 쪽
        (=글자층이 멀쩡해 OCR 을 건너뛴 쪽)의 강조는 이것으로 한다.
        """
        try:
            pg = self._v._doc.doc.load_page(int(page))
        except Exception:
            return []
        out = []
        try:
            for w in pg.get_text("words"):
                t = str(w[4] or "").strip()
                if t:
                    out.append({"surface": t, "x0": float(w[0]), "y0": float(w[1]),
                                "x1": float(w[2]), "y1": float(w[3])})
        except Exception:
            return []
        try:
            from viewer import text_extract2 as tx
            out = tx.words_in_reading_order(out, dpi=0, page=pg)
        except Exception:
            pass
        return out

    _ALIGN_MIN = 2         # 261108-29: 글자 맞춤에서 이보다 짧게 겹친 조각은 우연으로 본다

    @staticmethod
    def _norm(t: str) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "", (t or "").lower())

    def _build_spans(self):
        """문장(읽는 단위)마다 그 문장에 든 낱말 구간 [start, end] 와, 낱말마다 그 문장(`_wsent`).

        261108-29(사용자 보고 "성격심리책은 한글인데, 내가 찍은 곳을 제대로 찾지 못하고, 엉뚱한 곳부터
        읽어", SOT §1.9): 종전에는 **낱말이 글자까지 똑같아야** 맞췄고, 앞으로 10 낱말 안에서만 찾았다.
        한글 OCR 낱말은 글자 조각('성'·'격'·'론')이 많고, 읽는 글은 텍스트 창 글이라 띄어쓰기를
        고쳐 놓았다('성격이론의') — 첫 문장 뒤로 하나도 맞지 않아, 찍은 곳 대부분이 마지막 문장으로 갔다.
        영어는 낱말이 OCR 그대로라 맞았다. 이제 띄어쓰기·문장부호를 뺀 **글자 줄**끼리 맞춘다 —
        조각으로 갈리든 띄어쓰기가 고쳐지든 글자 차례는 같다. 낱말은 그 글자들이 가장 많이 든 문장으로."""
        from difflib import SequenceMatcher
        ow = [self._norm(x.get("surface")) for x in self._owords]
        a_chars, a_word = [], []
        for j, c in enumerate(ow):
            a_chars.append(c)
            a_word.extend([j] * len(c))
        b_chars, b_sent = [], []
        for si, sent in enumerate(self._sents):
            c = self._norm(sent)
            b_chars.append(c)
            b_sent.extend([si] * len(c))
        votes = [dict() for _ in ow]
        sm = SequenceMatcher(None, "".join(a_chars), "".join(b_chars), autojunk=False)
        for ai, bi, n in sm.get_matching_blocks():
            if n < self._ALIGN_MIN:
                continue
            for k in range(n):
                v = votes[a_word[ai + k]]
                si = b_sent[bi + k]
                v[si] = v.get(si, 0) + 1
        self._wsent = [max(v, key=v.get) if v else None for v in votes]
        first, last = {}, {}
        for j, si in enumerate(self._wsent):
            if si is None:
                continue
            first.setdefault(si, j)
            last[si] = j
        self._spans = [(first[si], last[si]) if si in first else (None, None)
                       for si in range(len(self._sents))]

    def _highlight_sentence(self, si: int):
        """현재 문장 구간 전체를 강조(읽는 위치=문장). 단어장 단어는 주황으로 구분,
        그 중 첫 단어를 단어장 상단으로."""
        # 260911(사용자 지시, SOT §1.3): 칠하는 **범위는 줄의 자리** — 텍스트 창에서
        #   그 줄에 커서를 두었을 때와 같다. 낱말 상자는 단어장 낱말을 가려내는 데만 쓴다.
        plain, vocab = [], []
        first_vocab_lemma = None
        if 0 <= si < len(self._srects) and self._srects[si]:
            plain = [tuple(r) for r in self._srects[si] if r]
            for w, rect in self._words_in(plain):
                clean = re.sub(r"[^0-9A-Za-z가-힣]", "", (w.get("surface") or "").lower())
                lem = self._vocab_lemma(clean) if clean else None
                if lem:
                    vocab.append(rect)
                    if first_vocab_lemma is None:
                        first_vocab_lemma = lem
            if not plain:
                self._v.clear_word_highlights(); return
        else:
            if not (0 <= si < len(self._spans)) or not self._owords:
                self._v.clear_word_highlights(); return
            start, last = self._spans[si]
            if start is None or last is None or last < start:
                self._v.clear_word_highlights(); return
            s = self._oscale
            for j in range(start, min(last + 1, len(self._owords))):
                w = self._owords[j]
                rect = (w["x0"] * s, w["y0"] * s, w["x1"] * s, w["y1"] * s)
                clean = re.sub(r"[^0-9A-Za-z가-힣]", "", (w.get("surface") or "").lower())
                lem = self._vocab_lemma(clean) if clean else None
                if lem:
                    vocab.append(rect)
                    if first_vocab_lemma is None:
                        first_vocab_lemma = lem
                else:
                    plain.append(rect)
        self._v.highlight_word_groups(
            [(plain, "read"), (vocab, "read_vocab")], scroll=True)
        if first_vocab_lemma:
            try:
                self.mw.study_panel.select_lemma(first_vocab_lemma, to_top=True)
            except Exception:
                pass

    def _words_in(self, rects) -> list:
        """그 자리들 안에 든 낱말 [(낱말, 사각형)] (SOT §1.3).

        단어장 낱말만 주황으로 구분하려면 어느 낱말이 그 줄에 있는지 알아야 한다.
        """
        out = []
        sc = self._oscale
        for w in (self._owords or []):
            try:
                r = (w["x0"] * sc, w["y0"] * sc, w["x1"] * sc, w["y1"] * sc)
            except Exception:
                continue
            cx, cy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
            for q in rects:
                if q[0] <= cx <= q[2] and q[1] <= cy <= q[3]:
                    out.append((w, r))
                    break
        return out

    def _vocab_lemma(self, clean: str):
        """현재 표시(난이도 필터 반영) 단어장에 있으면 그 표제어, 없으면 None."""
        try:
            lemset = self.mw.study_panel.shown_lemma_set()
            if not lemset:
                return None
            if clean in lemset:
                return clean
            from viewer.study.vocab import lemma_en
            le = lemma_en(clean)
            return le if le in lemset else None
        except Exception:
            return None

    def _estimate_dur(self, s: str) -> float:
        """260618-26: 문장 발화 추정 시간(초). 엔진이 발화상태를 보고하지 않는 환경에서
        문장이 다 읽히기 전에 다음 문장으로 넘어가(PURGE) '무음'이 되는 것을 막는 하한."""
        n = max(1, len(s.strip()))
        cps = 7.0 if _HANGUL.search(s) else 12.0       # 초당 글자수(대략)
        cps *= max(0.4, 1.0 + (self.rate * 0.06))      # 빠르기 반영
        return max(0.5, n / cps)

    def _speak_cur(self):
        self._pause_until = 0.0                         # 261108-25: 자리를 옮겨 읽을 때 남은 쉼은 버린다
        if 0 <= self._si < len(self._sents):
            import time
            s = self._sents[self._si]
            self._highlight_sentence(self._si)         # 읽는 '문장' 전체 강조
            lang = "kor" if _HANGUL.search(s) else "eng"
            self._spk_started = time.time()            # 260618-26: 발화 시작 시각
            self._cur_min_dur = self._estimate_dur(s)  # 260618-26: 최소 보장 시간
            # 260618-25: speak() 실패(False)는 종전엔 무시되어 '무음'으로만 보였음 →
            #   사용자에게 원인을 알려 진단 가능하게 함(엔진은 재초기화 후 재시도까지 수행).
            # 261108-25(SOT §1.8): 표시 글은 그대로, 읽는 글(숫자·단위 풀기·한영 조각)은 엔진 쪽 한 길
            tts = self._tts()
            sr = getattr(tts, "speak_reading", None)
            ok = sr(s) if callable(sr) else tts.speak(s, lang)
            if not ok and tts is not self.mw._study_get_tts():
                # 261108-28(SOT §1.10): 자연 음성이 안 되면 SAPI 로 — 읽기는 멈추지 않는다
                tts = self._fallback_to_sapi()
                sr = getattr(tts, "speak_reading", None)
                ok = sr(s) if callable(sr) else tts.speak(s, lang)
            pf = getattr(tts, "prefetch", None)
            if ok and callable(pf):
                from viewer.study.neural_tts import PREFETCH
                pf(self._sents[self._si + 1:self._si + 1 + PREFETCH])   # 다음 문장 미리 합성
            if not ok:
                try:
                    self.mw.status.showMessage(
                        tr("음성 출력에 실패했습니다(SAPI 음성 확인). 다시 시도해 주세요."), 4000)
                except Exception:
                    pass

    def _fallback_to_sapi(self):
        """261108-28(SOT §1.10): 자연 음성 → SAPI. 이번 읽기의 남은 문장은 SAPI 가 읽는다."""
        self._eng = self.mw._study_get_tts()
        try:
            self._eng.set_rate(self.rate)
            self.mw.status.showMessage(tr("자연 음성을 쓸 수 없어 Windows 기본 음성으로 읽습니다."), 5000)
        except Exception:
            pass
        return self._eng

    def _tick(self):
        if not self._active:
            self._timer.stop(); return
        if self._ocr_waiting is not None:
            return                                      # 261109-6: 그 쪽 OCR 결과를 기다리는 중
        tts = self._tts()
        if getattr(tts, "_failed", False) and tts is not self.mw._study_get_tts():
            # 261108-28: 합성이 배경에서 실패했다 — 그 문장부터 SAPI 로 다시(건너뛰지 않는다)
            self._fallback_to_sapi()
            self._speak_cur()
            return
        if tts.is_speaking():
            return                                      # 문장 단위 강조라 폴링 중 갱신 불필요
        # 260618-26: 엔진이 'speaking' 을 한 번도 보고하지 않은 경우(상태 보고 불가 환경)
        #   추정 발화시간이 지나기 전에는 넘어가지 않음 → 문장이 끊겨 무음되는 것 방지.
        #   (정상 환경은 saw_speaking()=True 라 즉시 다음 문장으로 진행 — 지연 없음.)
        try:
            if not tts.saw_speaking():
                import time
                if (time.time() - getattr(self, "_spk_started", 0.0)
                        ) < getattr(self, "_cur_min_dur", 0.0):
                    return
        except Exception:
            pass
        # 261108-25(SOT §1.8 의 1): 문장 사이 쉼 — 문단(줄 묶음) 끝이면 더 길게. 타이머가 120ms 마다 오므로
        #   기다림은 시각 비교뿐(메인 스레드를 막지 않는다, 응답성 SOT §4.8).
        import time as _t
        if self._pause_until <= 0.0:
            from viewer.study.tts_text import SENT_PAUSE_MS, PARA_PAUSE_MS
            pe = 0 <= self._si < len(self._para_end) and self._para_end[self._si]
            self._pause_until = _t.time() + (PARA_PAUSE_MS if pe else SENT_PAUSE_MS) / 1000.0
            return
        if _t.time() < self._pause_until:
            return
        self._pause_until = 0.0
        # 현재 문장 끝 → 다음
        self._si += 1
        if self._si < len(self._sents):
            self._speak_cur()
            return
        # 페이지 끝 → 다음 페이지
        self._pi += 1
        if self._pi < len(self._pages):
            self.mw.status.showMessage(
                tr('읽는 중: {pages} 페이지').format(pages=self._pages[self._pi] + 1), 2000)
            self._load_page()
        elif self.repeat:
            # 260911(SOT §1.1): 전체연속은 한 바퀴 뒤부터 **1쪽~끝**을 되풀이한다.
            #   연속은 목록이 한 쪽뿐이라 그대로 그 쪽을 되풀이한다.
            self._pages = self._wrap_pages()
            self._pi = 0
            self._load_page()
        else:
            # 260911(사용자 지시, SOT §1.1): 다 읽었으면 멈추고 **시작한 쪽으로**
            #   돌아간다. '전체' 는 1쪽부터 읽으므로, 끝내고 그대로 두면 사용자가
            #   보던 자리를 잃는다.
            self.mw.status.showMessage(tr("읽기 완료"), 3000)
            home = getattr(self, "_home_page", None)
            self.stop()
            if home is not None:
                try:
                    if self._v.current_page() != int(home):
                        self._v.go_to_page(int(home))
                except Exception:
                    pass

    def _page_units(self, page: int) -> list:
        """읽을 단위 [(글, 자리들)] — 자리는 **텍스트 창이 칠하는 그 범위** (SOT §1.3).

        260911(사용자 지시 "읽기시에도 텍스트 창과 연관된 본문 하이라이트 범위와
        일치시켜"): 종전 읽기 강조는 **낱말 상자**로 그 문장만 칠했고, 텍스트 창은
        **줄(이은 줄이면 원래 줄들 전부)** 를 칠했다. 같은 곳을 봐도 범위가 달랐다.

        이제 읽기도 **줄의 자리**를 쓴다. 한 줄에 문장이 여럿이면 그 문장들은 모두 그
        줄의 자리를 갖는다 — 텍스트 창에서 그 줄에 커서를 두었을 때와 같은 범위다.
        줄이 문장부호로 끝나지 않으면 다음 줄과 이어 한 문장으로 보고, 자리도 합친다.
        """
        try:
            from viewer import text_extract2 as tx
            cur = self._v.current_file()
            if not cur:
                return []
            look = None
            try:
                from viewer.study.study_store import file_key_for
                store = self.mw._study_get_store()
                fk = file_key_for(cur)

                def _look(pno, _s=store, _k=fk):
                    try:
                        return (_s.get_page_words(_k, pno),
                                _s.get_page_dpi(_k, pno))
                    except Exception:
                        return (None, 0)
                look = _look
            except Exception:
                look = None
            rows = tx.display_rows(cur, int(page), words_lookup=look)
        except Exception:
            return []
        # 261108-25(SOT §1.8 의 1): 셋째 값 = 그 줄(텍스트 창의 이은 줄 = 문단 꼴)의 마지막 문장인가 — 쉼을 길게
        units, pend_t, pend_r = [], "", []
        for r in rows:
            t = (r.get("text") or "").strip()
            if not t:
                continue
            rcs = list(r.get("rects") or [])
            ss = sentences_of(t) or [t]
            if pend_t:
                # 261108-31(SOT §1.8 의 1): 창이 잇지 않은 줄을 이을 때도 창의 잇는 규칙 그대로(텍스트 창 SOT §3.7.3) —
                #   종전에는 늘 빈칸이라 한글 낱말이 줄 끝에서 갈린 곳(`취사` + `선택`)을 '취사 선택' 으로 읽었다
                ss[0] = tx.join_text(pend_t, ss[0]).strip()
                rcs = pend_r + rcs
                pend_t, pend_r = "", []
            cont = False
            if ss and not _SENT_END_RE.search(ss[-1]):
                pend_t, pend_r = ss[-1], list(rcs)   # 다음 줄로 이어진다
                ss = ss[:-1]
                cont = True
            for k, one in enumerate(ss):
                units.append((one, list(rcs), (k == len(ss) - 1) and not cont))
        if pend_t:
            units.append((pend_t, list(pend_r), True))
        return units

    def _page_text(self, page: int) -> str:
        """읽을 글 — **텍스트 창이 보여 주는 것과 같은 글** (SOT §3.6.9).

        260911(사용자 보고 "OCR 다시 읽기로 텍스트 창은 잘 구성되는데 본문 읽기는
        2단을 그냥 1단처럼 읽는다"): 종전에는 `study.db` 의 **날것 OCR 글**이나 PDF
        글자층을 그대로 읽었다. 둘 다 줄 단위로 쪽을 가로지르므로 2단 쪽에서는 왼쪽
        단 한 줄, 오른쪽 단 한 줄을 번갈아 읽는다.

        이제 `clean_page_texts`(§3.1.5)를 먼저 쓴다 — 단 가르기·표 칸·문장 잇기·
        잡음 거르기를 다 거친 글이다. 실패하면 종전 두 길로 물러선다.
        """
        try:
            from viewer import text_extract2 as tx
            from viewer.study.study_store import file_key_for
            cur = self._v.current_file()
            if cur:
                look = None
                try:
                    store = self.mw._study_get_store()
                    fk = file_key_for(cur)

                    def _look(pno, _s=store, _k=fk):
                        try:
                            return (_s.get_page_words(_k, pno),
                                    _s.get_page_dpi(_k, pno))
                        except Exception:
                            return (None, 0)
                    look = _look
                except Exception:
                    look = None
                got = tx.clean_page_texts(cur, [int(page)], words_lookup=look)
                if got:
                    t = (got[0][1] or "").strip()
                    if len(t) > 20:
                        return t
        except Exception:
            pass
        # 1) 단어장(study.db) OCR 텍스트 우선(스캔본 정확) — 대상 창의 파일 기준
        try:
            from viewer.study.study_store import file_key_for
            cur = self._v.current_file()
            if cur:
                store = self.mw._study_get_store()
                t = store.get_page_text(file_key_for(cur), page)
                if t and len(t.strip()) > 20:
                    return t
        except Exception:
            pass
        # 2) 텍스트 레이어
        try:
            return self._v._doc.extract_text(page)
        except Exception:
            return ""


PAGE_TEXT_CHUNK = 32   # 261109-5: 배경 쪽 글 모으기 — 이만큼씩 한 번에(문서를 한 번 연다)·사이마다 중단 확인


def page_texts_bg(path, pages, *, db_path=None, cancelled=None, progress=None) -> dict:
    """261109-5(영상·음성 SOT §1.1): 여러 쪽의 읽을 글 {쪽: 글} — **배경 스레드**에서 부른다(본문 mp3).

    `ReadAloud._page_text` 와 같은 차례: 텍스트 창 글(`clean_page_texts`) → 보류 포함 OCR 글(study.db) → 글자층.
    종전 mp3 는 메인이 `_page_text` 를 쪽마다 불러 PDF 를 쪽마다 새로 열었다('응답 없음'). 여기서는 study.db 는 자기 연결,
    `clean_page_texts` 는 `PAGE_TEXT_CHUNK` 쪽씩 한 번에."""
    from viewer import text_extract2 as tx
    from viewer.study.study_store import StudyStore, file_key_for
    pages = [int(p) for p in pages]
    out = {}
    try:
        store = StudyStore(db_path)
    except Exception:
        store = None
    fk = file_key_for(str(path))
    doc = None
    try:
        def _look(pno):
            try:
                return (store.get_page_words(fk, pno), store.get_page_dpi(fk, pno))
            except Exception:
                return (None, 0)
        for i in range(0, len(pages), PAGE_TEXT_CHUNK):
            if cancelled is not None and cancelled():
                break
            part = pages[i:i + PAGE_TEXT_CHUNK]
            if progress is not None:
                progress(i, len(pages))
            got = {}
            try:
                got = {int(p): (t or "").strip()
                       for p, t in tx.clean_page_texts(str(path), part, words_lookup=_look if store else None)}
            except Exception:
                got = {}
            for p in part:
                t = got.get(p, "")
                if len(t) > 20:
                    out[p] = t
                    continue
                try:
                    t2 = store.get_page_text(fk, p) if store is not None else ""
                except Exception:
                    t2 = ""
                if t2 and len(t2.strip()) > 20:
                    out[p] = t2
                    continue
                try:
                    if doc is None:
                        import fitz
                        doc = fitz.open(str(path))
                    out[p] = doc.load_page(p).get_text("text")
                except Exception:
                    out[p] = ""
    finally:
        for o in (doc, store):
            try:
                if o is not None:
                    o.close()
            except Exception:
                pass
    return out


PLAY_ICON_PX = 14      # 261025-10(디자인 SOT §2.10): 읽기 ▶/■ 그림 크기


def set_play_state(btn, active: bool, dark=None) -> None:
    """읽기 단추 ▶/■ — 글자는 상태 표시(보이지 않는다), 보이는 것은 색 아이콘(디자인 SOT §4.5).
    종전 글리프 ▶ 는 글꼴 기준선 탓에 아래로 처졌다(261025-10). 테마를 바꾸면 다시 부른다.
    261108-24: 본문 도구 줄의 분할 단추(`splitPlay` 표시)는 글자가 재생 구간 이름이라 아이콘만 바꾼다."""
    from PyQt6.QtCore import QSize
    from viewer.widgets.icons import color_icon
    split = bool(btn.property("splitPlay"))
    btn.setProperty("playing", bool(active))   # 상태(분할 단추는 글자로 알 수 없다 — 검사·접근성)
    if not split:
        btn.setText("■" if active else "▶")
    btn.setIcon(color_icon("stop" if active else "play", dark))
    btn.setIconSize(QSize(PLAY_ICON_PX, PLAY_ICON_PX))
    if not split:
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


def make_read_button(controller: ReadAloud, parent=None):
    """본문 읽기 — 분할 단추 하나(261108-24, 디자인 SOT §2.10, 사용자 결정 '분할 단추'): [▶ 전체 | ▾].
    아이콘·글자를 누르면 읽기/정지(▶/■ 는 아이콘으로), ▾ 칸은 메뉴 — (1회, 연속, 전체, 전체연속) | 빠르기 | 성우.
    글자는 지금 재생 구간. 빠르기·성우는 단어장과 공유. 종전에는 ▶ 단추와 '전체 ▾' 메뉴 단추가 따로였다."""
    btn = QToolButton(parent)
    btn.setProperty("splitPlay", True)
    from viewer.widgets.icons import split_button
    split_button(btn)                           # ▾ 칸 메뉴 · Alt+↓/F4
    set_play_state(btn, False)
    btn.setToolTip(tr("본문 읽기/정지 (머리말·표·수식·그림 제외)") + "\n▾ " + tr("재생 구간 / 빠르기 / 성우"))
    btn.clicked.connect(controller.toggle)
    menu_btn = btn
    menu = QMenu(menu_btn)
    # 재생 구간
    g_mode = QActionGroup(menu); g_mode.setExclusive(True)
    # 재생 구간 이름은 controller.mode 의 **값**(설정 read_aloud.mode 에 저장) — 값은 그대로, 표시만 tr()
    for label in (tr_noop("1회"), tr_noop("연속"), tr_noop("전체"), tr_noop("전체연속")):
        a = QAction(tr(label), menu, checkable=True)
        a.setChecked(controller.mode == label)
        a.triggered.connect(lambda _c, v=label: setattr(controller, "mode", v))
        g_mode.addAction(a); menu.addAction(a)
    menu.addSeparator()
    # 빠르기
    rm = menu.addMenu(tr("빠르기"))
    g_r = QActionGroup(rm); g_r.setExclusive(True)
    for label, rate in RATES:
        a = QAction(tr(label), rm, checkable=True)
        a.setChecked(rate == 0)
        a.triggered.connect(lambda _c, r=rate: controller.set_rate(r))
        g_r.addAction(a); rm.addAction(a)
    # 성우 — 메뉴를 처음 열 때 채운다(261014-26, 마스터 §5 시작 import): 성우 목록은 SAPI(COM)를 띄워야 해서
    #   창을 만들 때 부르면 win32com 싣기·COM 생성이 시작 시간에 들어간다(두 창 단추라 두 번).
    # 261108-33(영상·음성 SOT §1.10 '성우', 사용자 보고 "본문 읽은데서는 성우설정의 변경이 없었고, 환경설정에는 자연어엔진
    #   선택시 성우1 등으로 되어 있었어"): 종전에는 처음 열 때 SAPI 목록을 한 번 채우고 끝이라, 자연 음성을 쓰는 동안에도
    #   Windows 성우만 보였다. 이제 **열 때마다 엔진에 맞게** 다시 채운다 — 자연 음성이면 목소리 1~10(사용자 이름),
    #   고르면 설정 `tts_voice.sid`(환경설정 '목소리' 와 같은 값 하나). SAPI 면 숨기지 않은 Windows 성우.
    holder = {"m": None}

    def build_voices():
        from viewer.study import tts_engine
        mw = controller.mw
        cfg = tts_engine.cfg_of(mw)
        neural = tts_engine.wants_neural(cfg)
        voices = []
        if not neural:
            try:
                voices = mw._study_get_tts().voice_names()
            except Exception:
                voices = []
        vm = holder["m"]
        if not neural and not voices:
            if vm is not None:
                vm.menuAction().setVisible(False)
            return
        if vm is None:
            vm = menu.addMenu(tr("성우"))
            vm.setObjectName("menuReadVoices")
            holder["m"] = vm
        vm.menuAction().setVisible(True)
        vm.clear()
        g_v = QActionGroup(vm); g_v.setExclusive(True)
        if neural:
            for sid in range(tts_engine.SPEAKERS):
                a = QAction(tts_engine.voice_label(cfg, sid), vm, checkable=True)
                a.setData(("neural", sid))
                a.setChecked(sid == cfg["sid"])
                a.triggered.connect(lambda _c, s=sid: tts_engine.set_sid(mw, s))
                g_v.addAction(a); vm.addAction(a)
            return
        a0 = QAction(tr("자동(언어별)"), vm, checkable=True)
        a0.setData(("sapi", None))
        a0.setChecked(not controller.voice_name)
        a0.triggered.connect(lambda: controller.set_voice(None))
        g_v.addAction(a0); vm.addAction(a0)
        for name in voices:
            a = QAction(name, vm, checkable=True)
            a.setData(("sapi", name))
            a.setChecked(controller.voice_name == name)
            a.triggered.connect(lambda _c, n=name: controller.set_voice(n))
            g_v.addAction(a); vm.addAction(a)
    menu.aboutToShow.connect(build_voices)
    menu_btn.setMenu(menu)

    def sync_checks():
        """261108-26: 메뉴 체크를 지금 값으로 — 설정 복원·다른 창 단추가 바꾼 값도 보이게(구간·빠르기·성우)."""
        for a, label in zip(g_mode.actions(), (tr_noop("1회"), tr_noop("연속"), tr_noop("전체"), tr_noop("전체연속"))):
            a.setChecked(controller.mode == label)
        for a, (_l, rate) in zip(g_r.actions(), RATES):
            a.setChecked(controller.rate == rate)
        # 성우 체크는 build_voices 가 열 때마다 엔진에 맞게 다시 채우며 맞춘다(261108-33)
    menu.aboutToShow.connect(sync_checks)

    def on_mode_text(*_):
        try:
            menu_btn.setText(tr(controller.mode))     # 값(한글 키)은 그대로, 표시만 번역
            sync_checks()
        except RuntimeError:                          # 단추가 이미 지워졌다(창 닫힘) — 신호만 남은 것
            pass
    on_mode_text()
    # 261108-26(SOT §1.5): 메뉴에서 고를 때만이 아니라 값이 바뀌면 늘(설정 복원·다른 창 단추)
    controller.modeChanged.connect(on_mode_text)

    def on_state(active):
        set_play_state(btn, active)
    controller.stateChanged.connect(on_state)
    return btn
