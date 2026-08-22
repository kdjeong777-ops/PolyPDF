"""우측 패널(건설기준/법령·고시/특허) 본문 찾기 — 전체 매치 하이라이트 + 이동.

SOT: `검색창 작업 계획서.md`. 메인 검색바가 패널 본문(QTextBrowser)을 검색할 때 공통 사용.
- 모든 매치를 노란색으로 하이라이트, 현재 매치는 주황색 + 스크롤.
- (현재 1-based, 전체) 반환 → 메인 검색바 'N / M' 표시.
- 문서(revision)나 검색어가 바뀌면 매치를 다시 계산.
"""
from __future__ import annotations

from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor
from PyQt6.QtWidgets import QTextEdit

_CUR = QColor("#ff9632")     # 현재 매치(주황)
_ALL = QColor("#fff34d")     # 전체 매치(노랑)


def _find_all(viewer, query):
    doc = viewer.document()
    out = []
    cur = QTextCursor(doc)
    while True:
        cur = doc.find(query, cur)
        if cur.isNull():
            break
        out.append((cur.selectionStart(), cur.selectionEnd()))
    return out


def _apply(viewer, positions, idx):
    doc = viewer.document()
    sels = []
    for i, (s, e) in enumerate(positions):
        c = QTextCursor(doc)
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = c
        fmt = QTextCharFormat()
        fmt.setBackground(_CUR if i == idx else _ALL)
        sel.format = fmt
        sels.append(sel)
    viewer.setExtraSelections(sels)
    if 0 <= idx < len(positions):
        s, e = positions[idx]
        c = QTextCursor(doc)
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        viewer.setTextCursor(c)
        viewer.ensureCursorVisible()


def _ret(state):
    tot = len(state.get("positions") or [])
    return (state.get("idx", -1) + 1 if state.get("idx", -1) >= 0 else 0, tot)


def search(viewer, query, backward, state):
    """(현재 1-based, 전체). state(dict)에 query/rev/positions/idx 유지."""
    if viewer is None or not query:
        if viewer is not None:
            viewer.setExtraSelections([])
        state.clear()
        return (0, 0)
    rev = viewer.document().revision()
    if query != state.get("query") or rev != state.get("rev"):
        state["query"] = query
        state["rev"] = rev
        state["positions"] = _find_all(viewer, query)
        state["idx"] = 0 if state["positions"] else -1
    else:
        n = len(state["positions"])
        if n:
            state["idx"] = (state.get("idx", -1) + (-1 if backward else 1)) % n
    _apply(viewer, state["positions"], state["idx"])
    return _ret(state)


def goto(viewer, state, idx):
    """특정 매치(idx, 0-based)로 이동(하이라이트·스크롤). (현재, 전체)."""
    pos = state.get("positions") or []
    if viewer is None or not pos or not (0 <= idx < len(pos)):
        return _ret(state)
    state["idx"] = idx
    _apply(viewer, pos, idx)
    return _ret(state)


def snippets(viewer, state, radius: int = 30):
    """각 매치 주변 문맥 문자열 리스트(검색 결과 목록 표시용)."""
    if viewer is None:
        return []
    text = viewer.toPlainText()
    out = []
    for (s, e) in (state.get("positions") or []):
        a = max(0, s - radius)
        b = min(len(text), e + radius)
        frag = text[a:b].replace("\n", " ").strip()
        out.append(("…" if a > 0 else "") + frag + ("…" if b < len(text) else ""))
    return out


def clear(viewer, state):
    state.clear()
    if viewer is not None:
        viewer.setExtraSelections([])
