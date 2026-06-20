"""본문 읽어주기(Read Aloud) — 메인 뷰어 페이지 내용을 음성으로, 자동 페이지 진행.
머리말/꼬리말·표·수식·그림(텍스트 적은 줄) 생략. 범위·성우·빠르기·반복 옵션.
260603 사용자 요청.
"""
from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QToolButton, QMenu

_HANGUL = re.compile(r"[가-힣]")
_LETTER = re.compile(r"[가-힣A-Za-z]")
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+|(?<=다\.)\s*|(?<=요\.)\s*")
RATES = [("느림", -4), ("보통", 0), ("빠름", 4), ("매우 빠름", 8)]


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


class ReadAloud(QObject):
    """본문 읽기 상태 머신. mw 에서 main_view·study store·tts 접근."""
    stateChanged = pyqtSignal(bool)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self._view = None           # 260606-11: 읽기 대상 메인뷰(2분할 창별). 없으면 활성창
        self._pane = 0
        self.mode = "전체"          # 1회/연속(현재페이지) · 전체/전체연속(현재→끝)
        self.repeat = False
        self.rate = 0
        self.voice_name = None      # 성우(빈값=언어 자동). 본화면·단어장 공유
        self._active = False
        self._pages: list[int] = []
        self._pi = 0
        self._sents: list[str] = []
        self._si = 0
        self._owords: list = []      # 현재 페이지 ocr_word (읽기순서, bbox)
        self._owptr = 0              # 카라오케 매칭 포인터
        self._oscale = 1.0
        self._last_span = None
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

    # --- 옵션 ---
    def set_rate(self, r: int):
        self.rate = r
        self.mw._study_get_tts().set_rate(r)

    def set_voice(self, name: Optional[str]):
        self.voice_name = name or None
        self.mw._study_get_tts().set_voice_name(name)

    def is_active(self) -> bool:
        return self._active

    def jump_to_point(self, px: float, py: float) -> bool:
        """현재 페이지에서 (px,py) PDF point 가 속한 문장부터 다시 읽기. 읽는 중에만."""
        if not self._active or not self._owords:
            return False
        s = self._oscale
        # 클릭 지점에 가장 가까운 ocr_word 인덱스
        best, bestd = None, 1e18
        for j, w in enumerate(self._owords):
            cx = (w["x0"] + w["x1"]) / 2 * s
            cy = (w["y0"] + w["y1"]) / 2 * s
            d = (cx - px) ** 2 + (cy - py) ** 2
            if d < bestd:
                bestd, best = d, j
        if best is None:
            return False
        # 그 단어를 포함하는 문장(없으면 시작이 best 이하인 가장 가까운 문장)
        spans = getattr(self, "_spans", [])
        target = None
        for si, (a, b) in enumerate(spans):
            if a is None or b is None:
                continue
            if a <= best <= b:
                target = si
                break
            if a <= best:
                target = si               # best 를 지난 마지막 문장(폴백)
        if target is None:
            for si, (a, b) in enumerate(spans):
                if a is not None:
                    target = si           # 첫 유효 문장
                    break
        if target is None:
            return False
        self.mw._study_get_tts().stop()
        self._si = target
        self._speak_cur()
        return True

    # --- 제어 ---
    def toggle(self):
        self.stop() if self._active else self.start()

    def start(self):
        tts = self.mw._study_get_tts()
        if not tts.available():
            self.mw.status.showMessage("음성(SAPI)을 사용할 수 없습니다.", 3000)
            return
        mv = self._v
        if mv.current_file() is None:
            self.mw.status.showMessage("먼저 PDF 를 여세요.", 3000)
            return
        start_page = mv.current_page()
        total = self._page_count()
        all_pages = self.mode in ("전체", "전체연속")
        self.repeat = self.mode in ("연속", "전체연속")
        self._pages = list(range(start_page, total)) if all_pages else [start_page]
        self._pi = 0
        tts.set_rate(self.rate)
        self._active = True
        self.stateChanged.emit(True)
        # 읽기 중에는 '본문강조'(전체 단어 배경)를 끄고 카라오케(읽는 단어)만 표시
        try:
            self._v.clear_word_highlights()
        except Exception:
            pass
        self._load_page()
        self._timer.start()

    def stop(self):
        self._active = False
        self._timer.stop()
        try:
            self.mw._study_get_tts().stop()
        except Exception:
            pass
        self.stateChanged.emit(False)
        # 카라오케 강조 제거 + (옵션이면) 본문강조 복원
        try:
            self._v.clear_word_highlights()
            if self.mw.study_panel.is_auto_highlight():
                self.mw._refresh_study_panel(self._v.current_page())
        except Exception:
            pass

    # --- 내부 ---
    def _page_count(self) -> int:
        try:
            return self._v._doc.page_count
        except Exception:
            return 1

    def _load_page(self):
        if not self._pages:
            self.stop(); return
        page = self._pages[self._pi]
        self._v.go_to_page(page)        # 읽는 페이지로 화면 자동 이동
        self._sents = sentences_of(self._page_text(page))
        self._si = 0
        self._load_owords(page)
        self._build_spans()
        self._speak_cur()

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
        except Exception:
            self._owords = []

    _ALIGN_WINDOW = 10     # 문장 정렬 시 ocr_word 전방 탐색 폭

    def _build_spans(self):
        """문장(speak 단위)을 ocr_word 구간 [start, end] 으로 한 번에 정렬.
        OCR 페이지는 text=단어surface 공백조인이라 1:1 정렬이 잘 맞음.
        문장 단위 강조라 단어 매칭 표류에 강함(엉뚱한 단어 점프 없음)."""
        self._spans = []
        ow = [re.sub(r"[^0-9A-Za-z가-힣]", "", (x.get("surface") or "").lower())
              for x in self._owords]
        N = len(ow)
        p = 0
        for sent in self._sents:
            words = [re.sub(r"[^0-9A-Za-z가-힣]", "", t.lower())
                     for t in re.findall(r"[0-9A-Za-z가-힣]+", sent)]
            words = [w for w in words if w]
            start = last = None
            for w in words:
                for j in range(p, min(N, p + self._ALIGN_WINDOW)):
                    if ow[j] == w:
                        if start is None:
                            start = j
                        last = j
                        p = j + 1
                        break
            self._spans.append((start, last) if start is not None else (p, p - 1))

    def _highlight_sentence(self, si: int):
        """현재 문장 구간 전체를 강조(읽는 위치=문장). 단어장 단어는 주황으로 구분,
        그 중 첫 단어를 단어장 상단으로."""
        if not (0 <= si < len(self._spans)) or not self._owords:
            self._v.clear_word_highlights(); return
        start, last = self._spans[si]
        if start is None or last is None or last < start:
            self._v.clear_word_highlights(); return
        s = self._oscale
        plain, vocab = [], []
        first_vocab_lemma = None
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

    def _speak_cur(self):
        if 0 <= self._si < len(self._sents):
            s = self._sents[self._si]
            self._highlight_sentence(self._si)         # 읽는 '문장' 전체 강조
            lang = "kor" if _HANGUL.search(s) else "eng"
            # 260618-25: speak() 실패(False)는 종전엔 무시되어 '무음'으로만 보였음 →
            #   사용자에게 원인을 알려 진단 가능하게 함(엔진은 재초기화 후 재시도까지 수행).
            ok = self.mw._study_get_tts().speak(s, lang)
            if not ok:
                try:
                    self.mw.status.showMessage(
                        "음성 출력에 실패했습니다(SAPI 음성 확인). 다시 시도해 주세요.", 4000)
                except Exception:
                    pass

    def _tick(self):
        if not self._active:
            self._timer.stop(); return
        tts = self.mw._study_get_tts()
        if tts.is_speaking():
            return                                      # 문장 단위 강조라 폴링 중 갱신 불필요
        # 현재 문장 끝 → 다음
        self._si += 1
        if self._si < len(self._sents):
            self._speak_cur()
            return
        # 페이지 끝 → 다음 페이지
        self._pi += 1
        if self._pi < len(self._pages):
            self.mw.status.showMessage(
                f"읽는 중: {self._pages[self._pi]+1} 페이지", 2000)
            self._load_page()
        elif self.repeat:
            self._pi = 0
            self._load_page()
        else:
            self.mw.status.showMessage("읽기 완료", 3000)
            self.stop()

    def _page_text(self, page: int) -> str:
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


def make_read_buttons(controller: ReadAloud, parent=None):
    """본문 읽기 — (1) 파란 ▶/■ 토글 버튼  (2) 별도 풀다운 메뉴 버튼.
    메뉴: (1회, 연속, 전체, 전체연속) | 빠르기 | 성우. 빠르기·성우는 단어장과 공유."""
    btn = QToolButton(parent)
    btn.setText("▶")
    btn.setStyleSheet("QToolButton{color:#1565c0;font-size:16px;font-weight:bold;}")
    btn.setToolTip("본문 읽기/정지 (머리말·표·수식·그림 제외)")
    btn.clicked.connect(controller.toggle)

    menu_btn = QToolButton(parent)
    menu_btn.setText("재생구간 ▾")
    menu_btn.setToolTip("재생 구간 / 빠르기 / 성우")
    menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(menu_btn)
    # 재생 구간
    g_mode = QActionGroup(menu); g_mode.setExclusive(True)
    for label in ("1회", "연속", "전체", "전체연속"):
        a = QAction(label, menu, checkable=True)
        a.setChecked(controller.mode == label)
        a.triggered.connect(lambda _c, v=label: setattr(controller, "mode", v))
        g_mode.addAction(a); menu.addAction(a)
    menu.addSeparator()
    # 빠르기
    rm = menu.addMenu("빠르기")
    g_r = QActionGroup(rm); g_r.setExclusive(True)
    for label, rate in RATES:
        a = QAction(label, rm, checkable=True)
        a.setChecked(rate == 0)
        a.triggered.connect(lambda _c, r=rate: controller.set_rate(r))
        g_r.addAction(a); rm.addAction(a)
    # 성우
    voices = []
    try:
        voices = controller.mw._study_get_tts().voice_names()
    except Exception:
        pass
    if voices:
        vm = menu.addMenu("성우")
        g_v = QActionGroup(vm); g_v.setExclusive(True)
        a0 = QAction("자동(언어별)", vm, checkable=True); a0.setChecked(True)
        a0.triggered.connect(lambda: controller.set_voice(None))
        g_v.addAction(a0); vm.addAction(a0)
        for name in voices:
            a = QAction(name, vm, checkable=True)
            a.triggered.connect(lambda _c, n=name: controller.set_voice(n))
            g_v.addAction(a); vm.addAction(a)
    menu_btn.setMenu(menu)

    def on_mode_text():
        menu_btn.setText(controller.mode + " ▾")
    on_mode_text()
    for a in g_mode.actions():
        a.triggered.connect(lambda *_: on_mode_text())

    def on_state(active):
        btn.setText("■" if active else "▶")
        btn.setStyleSheet("QToolButton{color:%s;font-size:16px;font-weight:bold;}"
                          % ("#c0392b" if active else "#1565c0"))
    controller.stateChanged.connect(on_state)
    return btn, menu_btn
