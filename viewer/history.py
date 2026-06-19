"""히스토리 스택 모델.

v1.5.0: dedup 키 (file_path, page_index). 미니카드 클릭 시 모델 보존.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal, Optional
import warnings

Origin = Literal["bookmark", "search", "screenshot"]


@dataclass
class HistoryItem:
    file_path: str
    page_index: Optional[int] = None
    query: str = ""
    origin: Origin = "bookmark"
    label: str = ""

    def __post_init__(self):
        if not self.label:
            from pathlib import Path
            self.label = Path(self.file_path).stem

    @property
    def key(self):
        """dedup 키 (file, page)."""
        return (self.file_path, self.page_index or 0)

    def to_dict(self):
        return {
            "file_path": self.file_path,
            "page_index": self.page_index,
            "query": self.query,
            "origin": self.origin,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            file_path=d["file_path"],
            page_index=d.get("page_index"),
            query=d.get("query", ""),
            origin=d.get("origin", "bookmark"),
            label=d.get("label", ""),
        )


class HistoryStack:
    """deque + (file, page) dedup 키."""

    def __init__(self, maxlen: int = 30):
        self.maxlen = maxlen
        self._items: deque = deque(maxlen=maxlen)

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, i):
        return self._items[i]

    def push(self, item: HistoryItem):
        """v1.5.2: 끝에 추가. 같은 (file, page) 가 있으면 제거 후 끝에 추가.

        모델 0번 = 가장 오래된 것, 끝 = 가장 최근.
        한도 초과 시 deque 가 가장 오래된 것(왼쪽)을 자동 제거.
        """
        for it in list(self._items):
            if it.key == item.key:
                self._items.remove(it)
                break
        self._items.append(item)

    def find(self, file_path: str, page_index: int) -> Optional[HistoryItem]:
        """모델 변경 없이 조회만 (v1.5.0: take_from_minicard 대체)."""
        target = (file_path, page_index or 0)
        for it in self._items:
            if it.key == target:
                return it
        return None

    def remove(self, item: HistoryItem):
        try:
            self._items.remove(item)
        except ValueError:
            pass

    def remove_by_key(self, file_path: str, page_index: int):
        target = (file_path, page_index or 0)
        for it in list(self._items):
            if it.key == target:
                self._items.remove(it)
                return

    def remove_by_path(self, file_path: str):
        """v1.4.0 호환 — 같은 file 의 모든 페이지 제거."""
        for it in list(self._items):
            if it.file_path == file_path:
                self._items.remove(it)

    def set_maxlen(self, n: int):
        """v1.5.1: 한도 동적 변경."""
        from collections import deque
        n = max(1, int(n))
        items = list(self._items)[:n]
        self._items = deque(items, maxlen=n)
        self.maxlen = n

    def clear(self):
        self._items.clear()

    def to_list(self):
        return [it.to_dict() for it in self._items]

    def load(self, items: list):
        self._items.clear()
        for d in items[: self.maxlen]:
            self._items.append(HistoryItem.from_dict(d))


class HistoryManager:
    def __init__(self, maxlen: int = 30):
        self.bookmark = HistoryStack(maxlen)
        self.search = HistoryStack(maxlen)

    def push_to(self, stack_name: str, item: Optional[HistoryItem]):
        if item is None or item.origin == "screenshot":
            return
        if stack_name == "bookmark":
            self.bookmark.push(item)
        elif stack_name == "search":
            self.search.push(item)

    def push_to_origin(self, item: Optional[HistoryItem]):
        warnings.warn(
            "push_to_origin is deprecated; use push_to(stack_name, item).",
            DeprecationWarning, stacklevel=2,
        )
        if item is None:
            return
        if item.origin == "bookmark":
            self.bookmark.push(item)
        elif item.origin == "search":
            self.search.push(item)

    def find(self, origin: Origin, file_path: str, page_index: int) -> Optional[HistoryItem]:
        stack = self.bookmark if origin == "bookmark" else self.search
        return stack.find(file_path, page_index)

    def take_from_minicard(self, origin: Origin, file_path: str) -> Optional[HistoryItem]:
        """DEPRECATED (v1.6.0 제거). v1.5.0 부터 미니카드 클릭은 모델을 보존."""
        warnings.warn(
            "take_from_minicard is deprecated (v1.5.0); use find() and don't remove.",
            DeprecationWarning, stacklevel=2,
        )
        stack = self.bookmark if origin == "bookmark" else self.search
        for it in list(stack._items):
            if it.file_path == file_path:
                stack._items.remove(it)
                return it
        return None

    def set_maxlen(self, n: int):
        """v1.5.1: 두 스택의 한도를 동시에 변경."""
        self.bookmark.set_maxlen(n)
        self.search.set_maxlen(n)

    def to_dict(self):
        return {
            "bookmark": self.bookmark.to_list(),
            "search": self.search.to_list(),
        }

    def load(self, d):
        self.bookmark.load(d.get("bookmark", []))
        self.search.load(d.get("search", []))
