# -*- coding: utf-8 -*-
"""260908-2: 텍스트 창의 **교정·하이라이트 저장소** (텍스트 창 SOT §5.1 ①·§6).

스캔 PDF 를 OCR 로 읽으면 글자가 틀리게 나온다(사용자 예: `ㅂ1ㅓ` → `배`).
그것을 고친 결과를 여기에 남기고, **본문 복사·검색·단어장이 즉시** 이것을 쓴다.
PDF 텍스트층에 다시 적는 것(§5.2)은 사용자가 [PDF 에 반영] 을 눌렀을 때만 한다 —
저장소는 그 전에도 뒤에도 **되돌릴 수 있는 기록**으로 남는다.

저장 위치는 설정 폴더의 `text_fix.json` 하나다. 자료가 작고(쪽·줄 단위 문자열),
문서마다 흩어 두면 PDF 를 옮길 때 같이 잃는다.

키 규칙: 파일은 `pathutil.norm_key`(SOT §7.0), 쪽은 0-based 정수, 줄은 정수 인덱스.
"""
from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from viewer.pathutil import norm_key

_LOCK = threading.RLock()
_NAME = "text_fix.json"


def _store_path() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / _NAME


class TextFixStore:
    """{파일키: {"fix": {쪽: {줄: 글}}, "hl": {쪽: [[줄, 시작, 끝, 색], …]}}}"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _store_path()
        self._data = {}
        self.load()

    # ---- 입출력 --------------------------------------------------------
    def load(self) -> None:
        with _LOCK:
            try:
                self._data = json.loads(io.open(self.path, encoding="utf-8").read())
            except Exception:
                self._data = {}
            if not isinstance(self._data, dict):
                self._data = {}

    def save(self) -> None:
        with _LOCK:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                io.open(self.path, "w", encoding="utf-8", newline="\n").write(
                    json.dumps(self._data, ensure_ascii=False, indent=1))
            except Exception:
                pass                # 저장 실패가 본 기능을 막지는 않는다

    # ---- 교정 ----------------------------------------------------------
    def _doc(self, file_path, create: bool = False):
        k = norm_key(file_path)
        d = self._data.get(k)
        if d is None and create:
            d = self._data[k] = {"fix": {}, "hl": {}}
        return d

    def get_fixes(self, file_path, page: int) -> dict:
        """{줄번호: 고친 글} — 없으면 빈 dict."""
        d = self._doc(file_path)
        if not d:
            return {}
        raw = (d.get("fix") or {}).get(str(int(page))) or {}
        out = {}
        for k, v in raw.items():
            out[int(k)] = v["t"] if isinstance(v, dict) else v
        return out

    def get_pairs(self, file_path, page: int) -> list:
        """[(원래 글, 고친 글)] — 원래 글을 남겨 둔 것만(복사 치환용)."""
        d = self._doc(file_path)
        if not d:
            return []
        raw = (d.get("fix") or {}).get(str(int(page))) or {}
        out = []
        for v in raw.values():
            if isinstance(v, dict) and v.get("o") and v.get("t"):
                out.append((v["o"], v["t"]))
        return out

    def apply_to_copy(self, file_path, page: int, text: str) -> str:
        """복사한 글에 교정을 반영(SOT §5.3). 긴 원문부터 바꿔 부분 겹침을 피한다."""
        pairs = self.get_pairs(file_path, page)
        if not pairs or not text:
            return text
        for o, t in sorted(pairs, key=lambda x: -len(x[0])):
            if o and o in text:
                text = text.replace(o, t)
        return text

    def set_fix(self, file_path, page: int, line: int, text: str,
                orig: str = None) -> None:
        """고친 글을 남긴다. `orig`(원래 글)도 함께 두면 **복사·검색에서 치환**할 수 있다.

        복사한 글은 줄 번호를 모른 채 오므로(사용자가 아무 데나 긁는다), 원문 조각을
        찾아 바꾸는 방법 말고는 반영할 길이 없다(SOT §5.3)."""
        d = self._doc(file_path, create=True)
        pg = d.setdefault("fix", {}).setdefault(str(int(page)), {})
        if text is None:
            pg.pop(str(int(line)), None)
        else:
            pg[str(int(line))] = ({"o": orig, "t": text} if orig else text)
        if not pg:
            d["fix"].pop(str(int(page)), None)
        self.save()

    def clear_page_fixes(self, file_path, page: int) -> None:
        d = self._doc(file_path)
        if d:
            (d.get("fix") or {}).pop(str(int(page)), None)
            self.save()

    def has_fixes(self, file_path) -> bool:
        d = self._doc(file_path)
        return bool(d and d.get("fix"))

    def apply_to_text(self, file_path, page: int, lines: list) -> list:
        """줄 목록에 교정을 얹은 사본. `lines` 는 문자열 목록."""
        fx = self.get_fixes(file_path, page)
        if not fx:
            return list(lines)
        out = list(lines)
        for i, t in fx.items():
            if 0 <= i < len(out):
                out[i] = t
        return out

    # ---- 하이라이트 ----------------------------------------------------
    def get_highlights(self, file_path, page: int) -> list:
        d = self._doc(file_path)
        if not d:
            return []
        return list((d.get("hl") or {}).get(str(int(page))) or [])

    def add_highlight(self, file_path, page: int, line: int,
                      start: int, end: int, color: str = "#ffe680") -> None:
        d = self._doc(file_path, create=True)
        arr = d.setdefault("hl", {}).setdefault(str(int(page)), [])
        item = [int(line), int(start), int(end), str(color)]
        if item not in arr:
            arr.append(item)
        self.save()

    def clear_highlights(self, file_path, page: int = None) -> None:
        d = self._doc(file_path)
        if not d:
            return
        if page is None:
            d["hl"] = {}
        else:
            (d.get("hl") or {}).pop(str(int(page)), None)
        self.save()


_SINGLETON = None


def store() -> TextFixStore:
    """앱 전역 저장소(1개). 여러 곳(텍스트 창·복사·검색)이 같은 것을 본다."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = TextFixStore()
    return _SINGLETON
