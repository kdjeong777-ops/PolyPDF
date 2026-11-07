"""kaikki.org Wiktionary JSONL(.gz) → 영영·영한 일반 사전 (단어장 SOT §5.1, 261107-27).

사용자가 내려받은 wiktextract 형식 파일(영어판·한국어판·전체 원자료)을 줄 단위로 읽어 영어 한 낱말만 사전 항목으로 넣는다.
무거운 일이라 **배경**에서 부른다(`import_file` — 자기 `DictStore` 연결, 진행·취소). 메인 스레드에서 부르지 않는다.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import re
from pathlib import Path
from typing import Callable, Iterator, Optional

WIKTIONARY_REFERENCE = ("Wiktionary (CC BY-SA 4.0, Wiktionary contributors) — "
                        "kaikki.org · wiktextract (Tatu Ylönen, LREC 2022)")
SOURCE_EN = "wiktionary_en"          # 영어판·전체 원자료 — 영어 풀이 + 한국어 번역
SOURCE_KO = "wiktionary_ko"          # 한국어판 — 한글 풀이
PRIORITY = 70                        # 동봉 전문사전(50·60) 뒤
# 261107-27(단어장 SOT §5.1): [Wiktionary 받기] — 주소는 여기 한 곳(kaikki 경로가 바뀌면 여기만). 한국어판만
KO_EDITION_URL = "https://kaikki.org/dictionary/downloads/ko/ko-extract.jsonl.gz"
KO_EDITION_FILE = "ko-extract.jsonl.gz"
KO_EDITION_APPROX_MB = 26
MIN_DOWNLOAD_BYTES = 1_000_000
_CHUNK = 256 * 1024
BATCH = 5000
MAX_GLOSSES = 6
MAX_EXAMPLES = 2
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{0,39}$")
_HANGUL_RE = re.compile(r"[가-힣]")


class ImportCancelled(Exception):
    pass


def _open_text(path) -> io.TextIOBase:
    p = str(path)
    with open(p, "rb") as fh:
        gz = fh.read(2) == b"\x1f\x8b"
    if gz:
        return io.TextIOWrapper(gzip.open(p, "rb"), encoding="utf-8", errors="replace")
    return open(p, "r", encoding="utf-8", errors="replace")


def is_wiktextract(path) -> bool:
    """앞 몇 줄에 wiktextract 항목(`word` + `senses`)이 있으면 True."""
    try:
        with _open_text(path) as f:
            for _i, line in zip(range(20), f):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    return False
                if isinstance(o, dict) and "word" in o and ("senses" in o or "redirect" in o):
                    return True
    except Exception:
        return False
    return False


def _ko_translations(obj: dict) -> list:
    out = []
    pools = [obj.get("translations") or []]
    for s in obj.get("senses") or []:
        pools.append(s.get("translations") or [])
    for pool in pools:
        for t in pool:
            if isinstance(t, dict) and t.get("lang_code") == "ko":
                w = (t.get("word") or "").strip()
                if w and w not in out:
                    out.append(w)
    return out


def entry_from_obj(obj: dict) -> Optional[dict]:
    """wiktextract 한 줄 → 사전 항목(없으면 None). 영어 한 낱말·고유명사 아님만."""
    if not isinstance(obj, dict) or obj.get("lang_code") != "en":
        return None
    word = (obj.get("word") or "").strip()
    pos = (obj.get("pos") or "").strip()
    if not _WORD_RE.match(word) or pos == "name":
        return None
    en_defs, ko_defs, examples = [], [], []
    for s in obj.get("senses") or []:
        glosses = s.get("glosses") or s.get("raw_glosses") or []
        g = (glosses[-1] if glosses else "").strip()       # 가장 구체적인 풀이(앞은 상위 뜻)
        if g:
            (ko_defs if _HANGUL_RE.search(g) else en_defs).append(g)
        for ex in s.get("examples") or []:
            t = (ex.get("text") if isinstance(ex, dict) else str(ex or "")).strip()
            if t and len(examples) < MAX_EXAMPLES and not _HANGUL_RE.search(t):
                examples.append(t)
    trans = _ko_translations(obj)
    if not (en_defs or ko_defs or trans):
        return None
    tag = f"({pos}) " if pos and pos != "unknown" else ""
    def_en = "\n".join(tag + d for d in en_defs[:MAX_GLOSSES])
    ko_lines = [tag + d for d in ko_defs[:MAX_GLOSSES]]
    if trans:
        ko_lines.append("번역: " + ", ".join(trans[:8]))
    return {"term_en": word, "term_ko": "", "def_en": def_en, "def_ko": "\n".join(ko_lines),
            "examples": "\n".join(examples), "reference": "", "level": ""}


def iter_entries(path, progress: Callable[[int, int], bool] = None) -> Iterator[dict]:
    """파일을 줄 단위로 — progress(읽은 바이트, 전체 바이트) 가 False 면 ImportCancelled."""
    total = max(1, os.path.getsize(str(path)))
    raw = open(str(path), "rb")
    try:
        gz = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        stream = io.TextIOWrapper(gzip.GzipFile(fileobj=raw) if gz else raw,
                                  encoding="utf-8", errors="replace")
        for n, line in enumerate(stream):
            if progress is not None and n % 2000 == 0 and not progress(raw.tell(), total):
                raise ImportCancelled()
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            e = entry_from_obj(obj)
            if e is not None:
                yield e
    finally:
        raw.close()


def import_file(db_path, path, progress: Callable[[int, int], bool] = None) -> dict:
    """배경에서 — 새 사전 연결로 넣는다. 반환 {source_id, words, with_ko, with_en}. 취소면 출처를 지우고 ImportCancelled."""
    from viewer.study.dict_store import DictStore
    store = DictStore(db_path)
    sid = None
    stats = {"source_id": None, "words": 0, "with_ko": 0, "with_en": 0}
    try:
        batch: list = []

        def _flush():
            if batch:
                store.add_entries(sid, batch)
                batch.clear()

        for e in iter_entries(path, progress):
            if sid is None:                     # 첫 항목으로 판(영어판·한국어판)을 가린다
                ko_ed = bool(e["def_ko"]) and not e["def_en"] and not e["def_ko"].startswith("번역:")
                sid = SOURCE_KO if ko_ed else SOURCE_EN
                stats["source_id"] = sid
                name = "Wiktionary 영한 (한국어판)" if ko_ed else "Wiktionary 영영·영한"
                store.add_source(sid, name, kind="base", reference=WIKTIONARY_REFERENCE,
                                 priority=PRIORITY, is_termbase=False, category="일반")
                store.replace_source_entries(sid, [])
                store.forget_deleted([sid])
            stats["words"] += 1
            stats["with_ko"] += 1 if e["def_ko"] else 0
            stats["with_en"] += 1 if e["def_en"] else 0
            batch.append(e)
            if len(batch) >= BATCH:
                _flush()
        _flush()
        return stats
    except ImportCancelled:
        if sid is not None:
            store.delete_source(sid)            # 반쯤 들어간 사전을 남기지 않는다
        raise
    finally:
        store.close()


class DownloadError(Exception):
    """받기 실패 — offline=True 면 인터넷 연결 없음."""
    def __init__(self, msg: str, offline: bool = False):
        super().__init__(msg)
        self.offline = offline


def _urlopen(url, timeout=30):                 # 검사가 바꿔 끼운다(가짜 네트워크)
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "PolyPDF dictionary import"})
    return urllib.request.urlopen(req, timeout=timeout)


def download(url: str, dest_dir, progress: Callable[[int, int], bool] = None) -> Path:
    """배경에서 — `dest_dir/<파일>.part` 로 받고 크기·gzip·형식을 확인한 뒤에만 이름을 바꾼다.
    취소·끊김·크기 다름이면 .part 를 지우고 ImportCancelled / DownloadError. 반환: 받은 파일 경로."""
    import urllib.error
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1] or KO_EDITION_FILE
    part = dest_dir / (name + ".part")
    final = dest_dir / name
    got = 0
    try:
        try:
            resp = _urlopen(url)
        except urllib.error.HTTPError as e:
            raise DownloadError(f"받기 실패: HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise DownloadError(f"인터넷에 연결할 수 없습니다 ({e})", offline=True)
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        with resp, open(part, "wb") as out:
            while True:
                if progress is not None and not progress(got, total or max(got, 1)):
                    raise ImportCancelled()
                try:
                    buf = resp.read(_CHUNK)
                except OSError as e:
                    raise DownloadError(f"받는 중에 연결이 끊겼습니다 ({e})", offline=True)
                if not buf:
                    break
                out.write(buf)
                got += len(buf)
        if total and got != total:
            raise DownloadError(f"받은 크기가 맞지 않습니다({got:,} / {total:,} 바이트) — 넣지 않았습니다")
        if got < MIN_DOWNLOAD_BYTES:
            raise DownloadError(f"받은 파일이 너무 작습니다({got:,} 바이트) — 넣지 않았습니다")
        with open(part, "rb") as fh:
            if name.endswith(".gz") and fh.read(2) != b"\x1f\x8b":
                raise DownloadError("받은 파일이 gzip 이 아닙니다 — 넣지 않았습니다")
        if not is_wiktextract(part):
            raise DownloadError("받은 파일이 Wiktionary(wiktextract) 형식이 아닙니다 — 넣지 않았습니다")
        os.replace(part, final)
        return final
    finally:
        try:
            if part.exists():
                part.unlink()               # 반쯤 받은 파일은 남기지 않는다
        except OSError:
            pass


def scan_stats(path, limit_bytes: int = 0) -> dict:
    """한국어 번역 비율 재기(넣지 않음) — limit_bytes 가 있으면 그만큼만 읽는다."""
    st = {"words": 0, "with_ko": 0, "with_en": 0, "bytes": 0}

    def _p(done, total):
        st["bytes"] = done
        return not (limit_bytes and done >= limit_bytes)
    try:
        for e in iter_entries(path, _p):
            st["words"] += 1
            st["with_ko"] += 1 if e["def_ko"] else 0
            st["with_en"] += 1 if e["def_en"] else 0
    except ImportCancelled:
        pass
    return st
