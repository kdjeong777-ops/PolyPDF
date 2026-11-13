# -*- coding: utf-8 -*-
"""한영 쌍 태그 — 균열 ⇄ crack (태그 SOT §8.9, 261113-9).

사용자 결정: **쌍 표 + 태그 하나만** — 파일에는 붙인 태그 하나만 남고, `#태그` 거르기가 짝을 함께 찾는다.
저장은 `settings_dir()/tag_pairs.json` `{"pairs": [[한쪽, 다른쪽], …]}` — 태그 하나에 짝 하나(대소문자 무시).
쓰기는 `bg_write` 줄(응답성 SOT §4.8 — 메인은 파일을 쓰지 않는다), 읽기는 `bg_write.read_text`(쓰기 전 내용도 보인다).
추천(`suggest`)은 오프라인 — 사용자 단어장 → 단어장 → 내장 영한 사전(§3.4 LLM 없음). 배경에서 부른다(`PairSuggestWorker`).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

_KO = re.compile(r"[가-힣]")
SUGGEST_MAX = 8


def pairs_path() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / "tag_pairs.json"


def is_korean(t: str) -> bool:
    return bool(_KO.search(t or ""))


class PairTable:
    """쌍 표 — 메인에서 쓴다(읽기·고치기는 메모리, 저장은 bg_write)."""

    def __init__(self, path=None):
        self.path = Path(path) if path else pairs_path()
        self.pairs: list = []
        self.reload()

    def reload(self):
        from viewer import bg_write
        try:
            d = json.loads(bg_write.read_text(self.path) or "{}")
        except Exception:
            d = {}
        out, seen = [], set()
        for pr in d.get("pairs") or ():
            if not isinstance(pr, (list, tuple)) or len(pr) != 2:
                continue
            a, b = (str(x or "").strip().lstrip("#").strip() for x in pr)
            if a and b and a.lower() != b.lower() and a.lower() not in seen and b.lower() not in seen:
                seen |= {a.lower(), b.lower()}
                out.append([a, b])
        self.pairs = out

    def partner(self, tag: str):
        tl = (tag or "").strip().lstrip("#").lower()
        for a, b in self.pairs:
            if a.lower() == tl:
                return b
            if b.lower() == tl:
                return a
        return None

    def link(self, a: str, b: str) -> bool:
        a, b = (str(x or "").strip().lstrip("#").strip() for x in (a, b))
        if not a or not b or a.lower() == b.lower():
            return False
        low = {a.lower(), b.lower()}
        self.pairs = [p for p in self.pairs if not ({p[0].lower(), p[1].lower()} & low)] + [[a, b]]
        self.save()
        return True

    def unlink(self, tag: str) -> bool:
        tl = (tag or "").strip().lstrip("#").lower()
        n = len(self.pairs)
        self.pairs = [p for p in self.pairs if tl not in (p[0].lower(), p[1].lower())]
        if len(self.pairs) != n:
            self.save()
            return True
        return False

    def expand(self, q: str) -> list:
        """`#q` 거르기 — q 와 그 짝(소문자). 짝은 q 가 태그 이름 그대로일 때만(앞부분 일치는 쓴 낱말에만 — §8.9)."""
        q = (q or "").lower()
        p = self.partner(q)
        return [q] + ([p.lower()] if p else [])

    def save(self):
        from viewer import bg_write
        bg_write.submit(self.path, json.dumps({"pairs": self.pairs}, ensure_ascii=False, indent=0))


_shared = None


def shared() -> PairTable:
    """앱 하나에 표 하나 — 창과 책갈피창 거르기가 같은 것을 본다."""
    global _shared
    if _shared is None or _shared.path != pairs_path():
        _shared = PairTable()
    return _shared


# ── 추천(배경) ─────────────────────────────────────────────
_csv_cache = None


def _en_ko_rows():
    """내장 영한 사전(영어, '뜻1, 뜻2') — 처음 한 번 읽어 둔다."""
    global _csv_cache
    if _csv_cache is None:
        rows = []
        try:
            from viewer.resources_path import resource_path      # study/vocab.py 와 같은 길
            p = Path(resource_path("en_ko_dict.csv"))
        except Exception:
            p = Path(__file__).resolve().parent.parent / "resources" / "en_ko_dict.csv"
        if not p.exists():
            p = Path(__file__).resolve().parent.parent / "resources" / "en_ko_dict.csv"
        try:
            with open(p, encoding="utf-8", newline="") as fh:
                for r in csv.reader(fh):
                    if len(r) >= 2 and r[0].strip():
                        rows.append((r[0].strip(), [m.strip() for m in re.split(r"[,;/]", r[1]) if m.strip()]))
        except Exception:
            pass
        _csv_cache = rows
    return _csv_cache


def _dict_dbs():
    from viewer.settings_store import settings_dir
    d = Path(settings_dir())
    return [p for p in (d / "user_dict.db", d / "dict.db") if p.exists()]


def suggest(tag: str, limit: int = SUGGEST_MAX) -> list:
    """한글이면 영어, 영어면 한글 낱말 — 사용자 단어장 → 단어장 → 내장 영한 사전 차례, 같은 낱말은 한 번."""
    t = (tag or "").strip().lstrip("#").strip()
    if not t:
        return []
    ko = is_korean(t)
    out, seen = [], set()

    def add(w):
        w = (w or "").strip()
        if w and w.lower() not in seen and w.lower() != t.lower() and is_korean(w) != ko and len(out) < limit:
            seen.add(w.lower())
            out.append(w)
    try:
        from viewer import dbutil as _db
        from viewer.study.dict_store import normalize_key
        key = normalize_key(t)
        for p in _dict_dbs():
            con = _db.connect(p, _db.BUSY_MS_BG, row_factory=False, readonly=True)
            try:
                if ko:
                    rows = con.execute("SELECT term_en FROM dict_entry WHERE enabled=1 AND (norm_ko=? OR term_ko=?) "
                                       "AND term_en<>'' LIMIT 20", (key, t)).fetchall()
                else:
                    rows = con.execute("SELECT term_ko FROM dict_entry WHERE enabled=1 AND (norm_en=? OR lower(term_en)=?) "
                                       "AND term_ko<>'' LIMIT 20", (key, t.lower())).fetchall()
                for (w,) in rows:
                    for part in re.split(r"[,;/]", w or ""):
                        add(part)
            finally:
                con.close()
    except Exception:
        pass
    rows = _en_ko_rows()
    if ko:
        for en, means in rows:
            if t in means:
                add(en)
                if len(out) >= limit:
                    break
    else:
        tl = t.lower()
        for en, means in rows:
            if en.lower() == tl:
                for m in means:
                    add(m)
                break
    return out


class PairSuggestWorker(QObject):
    """추천을 배경에서(응답성 SOT §4 ① — 사전 csv 4만 줄·SQLite 읽기). 결과만 메인으로."""
    found = pyqtSignal(str, list)
    finished = pyqtSignal()

    def __init__(self, tag: str):
        super().__init__()
        self.tag = tag

    def request_cancel(self):
        pass

    def run(self):
        try:
            self.found.emit(self.tag, suggest(self.tag))
        except Exception:
            self.found.emit(self.tag, [])
        finally:
            self.finished.emit()
