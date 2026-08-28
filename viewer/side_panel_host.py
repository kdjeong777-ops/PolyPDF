"""260628(감사 D): 사이드 패널 호스팅 일반화 — 법령·건설기준(KCSC)·특허(KIPRIS) 공통.

배경: `_open_X / _enter_X_layout / _apply_X_embed_sizes / _toggle_X_fullscreen /
_embed_X_from_window / _close_X` 6종이 3벌(약 460줄) 존재했고, **정밀 비교 결과
`_close_X`·`_embed_X_from_window`·`_apply_X_embed_sizes`·`_enter_X_layout` 은 차이 0줄**
(docstring 제외), `_toggle_X_fullscreen` 은 호스트 창 클래스·제목만, `_open_X` 은
키 게터·패널 클래스·형제 패널 닫기 집합만 달랐다. 한 곳만 고치면 세 패널 동작이 갈라진다.
(법령·고시 SOT §10.3 이 권고하던 리팩터.)

설계: **상태는 그대로 MainWindow 속성**(`_law_panel`/`_law_window`/`_law_saved`/
`_law_embed_sizes` …)에 두고, 로직만 이 모듈의 함수로 옮긴다. 기존 18개 메서드는
얇은 위임으로 남으므로 **메뉴·시그널 연결 등 호출부는 하나도 바뀌지 않는다**.

새 API 패널 추가 시: `SPECS` 에 한 항목만 추가하고, MainWindow 에 위임 메서드 6개를
붙이면 된다(각 1줄).
"""
from __future__ import annotations

__all__ = ["SPECS", "PanelSpec", "enter_layout", "apply_embed_sizes",
           "toggle_fullscreen", "embed_from_window", "close_panel"]


class PanelSpec:
    """패널 1종의 차이점만 담는다(나머지 로직은 전부 공통)."""

    def __init__(self, key: str, fullscreen_title: str, module: str,
                 host_cls: str, siblings: tuple):
        self.key = key                          # "law" | "kcsc" | "kipo"
        self.fullscreen_title = fullscreen_title
        self.module = module                    # 패널/호스트창이 정의된 모듈
        self.host_cls = host_cls                # 전체화면 호스트 창 클래스명
        self.siblings = siblings                # 사이드 슬롯을 공유하는 다른 패널 키들

    # MainWindow 속성명 (상태는 종전과 동일한 이름에 그대로 보관 — 호환)
    @property
    def panel_attr(self) -> str:
        return f"_{self.key}_panel"

    @property
    def window_attr(self) -> str:
        return f"_{self.key}_window"

    @property
    def saved_attr(self) -> str:
        return f"_{self.key}_saved"

    @property
    def sizes_attr(self) -> str:
        return f"_{self.key}_embed_sizes"


SPECS = {
    "law": PanelSpec("law", "법령/고시 (전체화면)",
                     "viewer.widgets.law_search_dialog", "LawHostWindow",
                     ("kcsc", "kipo")),
    "kcsc": PanelSpec("kcsc", "건설기준(KCSC) (전체화면)",
                      "viewer.widgets.kcsc_search_dialog", "KcscHostWindow",
                      ("law", "kipo")),
    "kipo": PanelSpec("kipo", "특허(KIPRIS) (전체화면)",
                      "viewer.widgets.kipo_search_dialog", "KipoHostWindow",
                      ("law", "kcsc")),
}


def _panel(win, spec):
    return getattr(win, spec.panel_attr, None)


def enter_layout(win, spec: PanelSpec) -> None:
    """패널을 메인 splitter 오른쪽 끝에 임베드(2단). 썸네일/우측패널은 슬라이드 숨김,
    책갈피는 유지. 닫을 때 복원하도록 상태 저장."""
    panel = _panel(win, spec)
    if panel is None:
        return
    try:
        setattr(win, spec.saved_attr, {
            "splitter": win.splitter.saveState(),
            "search": win.act_toggle_search.isChecked(),
            "shot": win.act_toggle_shot.isChecked(),
            "split": win.act_split.isChecked(),      # 260618-8: 2단(PDF) 상태 복원용
            "handle": win.splitter.handleWidth(),
        })
        win.act_toggle_search.setChecked(False)
        win.act_toggle_shot.setChecked(False)
        # 260618-18: 책갈피·썸네일·뷰어(1단)·패널 표시 — 2단(PDF 분할)만 끔(뷰어 1단)
        if win.act_split.isChecked():
            win.act_split.setChecked(False)
        win._sync_right_layout()           # 우측 검색/스크린샷 패널 → 드로어(숨김)
        win.splitter.addWidget(panel)      # 오른쪽 끝(2단)
        win.splitter.setHandleWidth(8)
        for i in range(win.splitter.count()):
            win.splitter.setCollapsible(i, True)
        # 패널은 접힘 방지(수직선을 끝까지 끌어도 버튼이 사라지지 않게)
        il = win.splitter.indexOf(panel)
        if 0 <= il < win.splitter.count():
            win.splitter.setCollapsible(il, False)
        panel.set_fullscreen(False)
        apply_embed_sizes(win, spec)
    except Exception:
        pass


def apply_embed_sizes(win, spec: PanelSpec) -> None:
    """260618-18: 책갈피 | 썸네일 | 뷰어(1단) | 패널 순으로 표시.
    (우측 검색/스크린샷 패널만 숨김 — 책갈피·썸네일은 보이게.)"""
    panel = _panel(win, spec)
    if panel is None:
        return
    try:
        n = win.splitter.count()
        total = sum(win.splitter.sizes()) or max(1100, win.width())
        bk, th = 170, 120
        im = win.splitter.indexOf(win.main_split)
        il = win.splitter.indexOf(panel)
        ith = win.splitter.indexOf(win.page_thumbs)
        rest = max(420, total - bk - th)
        vw = rest // 2
        lw = rest - vw
        sizes = [0] * n
        sizes[0] = bk                              # 책갈피
        if 0 <= ith < n:
            sizes[ith] = th                        # 썸네일
        if 0 <= im < n:
            sizes[im] = vw                         # 뷰어(1단)
        if 0 <= il < n:
            sizes[il] = lw                         # 패널
        win.splitter.setSizes(sizes)
    except Exception:
        pass


def toggle_fullscreen(win, spec: PanelSpec) -> None:
    """임베드 ↔ 전체화면(별도 창) 전환."""
    panel = _panel(win, spec)
    if panel is None:
        return
    import importlib
    host_cls = getattr(importlib.import_module(spec.module), spec.host_cls)
    if getattr(win, spec.window_attr, None) is None:
        # 임베드 → 전체화면 팝아웃 (현재 임베드 크기 기억해 복귀 시 복원)
        setattr(win, spec.sizes_attr, win.splitter.sizes())
        w = host_cls()
        setattr(win, spec.window_attr, w)
        w.setWindowTitle(spec.fullscreen_title)
        from PyQt6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)               # splitter 에서 분리·재부모화
        w.closed.connect(lambda: embed_from_window(win, spec))
        panel.set_fullscreen(True)
        w.showMaximized()
    else:
        embed_from_window(win, spec)       # 전체화면 → 임베드 복귀


def embed_from_window(win, spec: PanelSpec) -> None:
    """전체화면 창의 패널을 메인 오른쪽 2단으로 복귀."""
    panel = _panel(win, spec)
    if panel is None:
        return
    w = getattr(win, spec.window_attr, None)
    setattr(win, spec.window_attr, None)
    try:
        win.splitter.addWidget(panel)      # 재부모화(임베드)
        panel.set_fullscreen(False)
        # 전체화면 전 임베드 크기 복원(원래 화면 크기 유지)
        saved = getattr(win, spec.sizes_attr, None)
        if saved and len(saved) == win.splitter.count():
            win.splitter.setSizes(saved)
        else:
            apply_embed_sizes(win, spec)
        panel.show()
    except Exception:
        pass
    if w is not None:
        try:
            w.closed.disconnect()
        except Exception:
            pass
        w.deleteLater()


def close_panel(win, spec: PanelSpec) -> None:
    """패널을 닫고 메인 레이아웃 복원."""
    panel = _panel(win, spec)
    w = getattr(win, spec.window_attr, None)
    setattr(win, spec.panel_attr, None)
    setattr(win, spec.window_attr, None)
    win._set_content_search(None)          # 검색바 → PDF 내용 검색 복귀
    try:
        if panel is not None:
            panel.setParent(None)          # splitter/창에서 제거
            panel.deleteLater()
        if w is not None:
            try:
                w.closed.disconnect()
            except Exception:
                pass
            w.close()
            w.deleteLater()
    except Exception:
        pass
    # 메인 레이아웃 복원
    s = getattr(win, spec.saved_attr, None) or {}
    try:
        if "handle" in s:
            win.splitter.setHandleWidth(s["handle"])
        if "search" in s:
            win.act_toggle_search.setChecked(s["search"])
        if "shot" in s:
            win.act_toggle_shot.setChecked(s["shot"])
        if "split" in s:                          # 260618-8: 2단(PDF) 상태 복원
            win.act_split.setChecked(s["split"])
        win._sync_right_layout()
        if s.get("splitter"):
            win.splitter.restoreState(s["splitter"])
    except Exception:
        pass


def close_siblings(win, spec: PanelSpec) -> None:
    """사이드 슬롯을 공유하는 다른 패널을 먼저 닫는다(슬롯은 하나뿐)."""
    for k in spec.siblings:
        other = SPECS.get(k)
        if other is not None and getattr(win, other.panel_attr, None) is not None:
            close_panel(win, other)
