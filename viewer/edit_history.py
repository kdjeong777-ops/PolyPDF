# -*- coding: utf-8 -*-
"""편집 모드 되돌리기/다시실행 기록 (261012-7, 마스터 §4.6.8) — Qt 없음.

기록 키(앱은 편집 한 번 동안 'session' 하나)마다 단계 목록. 한 단계(그룹)는 한 사용자 동작이 바꾼 것들 — 같은 이벤트 안에서
연달아 들어온 변경(예: 범위 선택 지우기 = 선 저장 + 사진 저장)을 앱이 `close()` 로 묶는다. 변경 하나 = (종류, 대상, 전, 후) —
대상은 (파일, 쪽)·파일·(책갈피창, 파일) 등 같음 비교만 되면 무엇이든. 종류는 앱이 정한다(§4.6.8 표).
"""
from __future__ import annotations

import copy


class EditHistory:
    LIMIT = 50

    def __init__(self):
        self._undo: dict = {}
        self._redo: dict = {}
        self._open = None                    # (파일 키, [변경, …]) — 아직 닫지 않은 단계

    def record(self, key: str, kind: str, page: int, before, after) -> bool:
        """변경 하나를 지금 단계에 넣는다. 같은 단계에서 같은 (종류, 쪽)이 또 바뀌면 처음 '전' 과 마지막 '후' 만 남긴다."""
        if before == after:
            return False
        if self._open is not None and self._open[0] != key:
            self.close()
        if self._open is None:
            self._open = (key, [])
        changes = self._open[1]
        for i, (k, p, b, _a) in enumerate(changes):
            if k == kind and p == page:
                changes[i] = (k, p, b, copy.deepcopy(after))
                break
        else:
            changes.append((kind, page, copy.deepcopy(before), copy.deepcopy(after)))
        self._redo.pop(key, None)            # 새 편집 — 다시실행 기록은 버린다
        return True

    def close(self) -> None:
        if self._open is None:
            return
        key, changes = self._open
        self._open = None
        changes = [c for c in changes if c[2] != c[3]]
        if not changes:
            return
        st = self._undo.setdefault(key, [])
        st.append(changes)
        if len(st) > self.LIMIT:
            del st[0]

    def can_undo(self, key: str) -> bool:
        return bool(self._undo.get(key)) or bool(self._open and self._open[0] == key and self._open[1])

    def can_redo(self, key: str) -> bool:
        return bool(self._redo.get(key))

    def undo(self, key: str):
        """되돌릴 단계 — [(종류, 쪽, 넣을 값), …](나중 변경부터). 없으면 None."""
        self.close()
        st = self._undo.get(key)
        if not st:
            return None
        changes = st.pop()
        self._redo.setdefault(key, []).append(changes)
        return [(k, p, copy.deepcopy(b)) for (k, p, b, _a) in reversed(changes)]

    def redo(self, key: str):
        self.close()
        st = self._redo.get(key)
        if not st:
            return None
        changes = st.pop()
        self._undo.setdefault(key, []).append(changes)
        return [(k, p, copy.deepcopy(a)) for (k, p, _b, a) in changes]

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._undo.clear()
            self._redo.clear()
            self._open = None
            return
        self._undo.pop(key, None)
        self._redo.pop(key, None)
        if self._open is not None and self._open[0] == key:
            self._open = None
