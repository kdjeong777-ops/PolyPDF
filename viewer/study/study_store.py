"""study.db — OCR/어휘 캐시 (기존 index.db 와 분리, 계획서 §4).

저장 위치: settings_store.settings_dir() / 'study.db' (= %APPDATA%\\LocalTools\\PolyPDF).
file_key = 파일 절대경로의 sha1(앞 16자) — 동일 파일 재오픈 시 캐시 적중.
재개(resume): ocr_page PK(file_key,page) 로 이미 처리한 페이지를 스킵.

261019-1(단어학습 SOT §14.21, 사용자 지시 'OCR·책갈피·단어장은 [저장]하지 않으면 저장되지 않게'):
**보류 저장소**. `enable_pending(True)`(앱이 켠다) 뒤에는 OCR 쪽·어휘가 study.db 가 아니라 이 프로세스의
보류 DB(`study_pending_<pid>.db`)에 쓰인다. 읽기는 같은 이름의 TEMP VIEW 가 '보류 ▶ 저장본' 순으로 겹쳐
보여 주므로 텍스트 창·단어장·책갈피 생성은 저장 전에도 그 결과를 그대로 쓴다(이어하기 포함).
[저장]이면 `commit_pending(file_key)` 가 study.db 로 옮기고, 저장하지 않고 끝내면 `discard_pending` 으로 버린다.
뜻·예문(`vocab_def`·`vocab_example`)은 파일과 무관한 사전 캐시라 보류하지 않는다.
"""
from __future__ import annotations

import hashlib
import sqlite3

from viewer import dbutil as _dbutil
import time
from pathlib import Path
from typing import Iterable, Optional


_KEY_PATHS: dict = {}          # file_key → 경로(보류 목록을 사람이 읽게 — 이 프로세스에서 본 것)


def file_key_for(path: str | Path) -> str:
    """파일 절대경로 기반 안정 키."""
    p = str(Path(path).resolve()).lower()
    k = hashlib.sha1(p.encode("utf-8")).hexdigest()[:16]
    _KEY_PATHS.setdefault(k, str(path))
    return k


def path_for_key(file_key: str) -> str:
    return _KEY_PATHS.get(file_key, "")


# ── 261019-1: 보류 저장소 ─────────────────────────────────────────────
_PENDING = {"on": False, "path": None}
_PENDING_TABLES = ("ocr_page", "ocr_word", "vocab", "vocab_page", "study_meta")


def pending_db_path() -> Path:
    if _PENDING["path"] is None:
        import os
        _PENDING["path"] = default_db_path().parent / "pending" / f"study_pending_{os.getpid()}.db"
    return Path(_PENDING["path"])


def enable_pending(on: bool = True, path=None) -> None:
    """보류 저장 켜기(앱 시작 때). `path` 는 시험용."""
    _PENDING["on"] = bool(on)
    if path is not None:
        _PENDING["path"] = Path(path)


def pending_enabled() -> bool:
    return bool(_PENDING["on"])


# 보류 DB 의 표 — `{p}` 는 붙인 DB 이름(`p.`) 또는 빈 글자(배경에서 파일을 바로 만들 때)
_PENDING_SCHEMA = """
    CREATE TABLE IF NOT EXISTS {p}ocr_page(
        file_key TEXT, page INTEGER, text TEXT, dpi INTEGER,
        engine TEXT, source TEXT, conf REAL, done_at TEXT,
        PRIMARY KEY(file_key, page));
    CREATE TABLE IF NOT EXISTS {p}ocr_word(
        file_key TEXT, page INTEGER, lemma TEXT, surface TEXT, lang TEXT,
        x0 REAL, y0 REAL, x1 REAL, y1 REAL, conf REAL);
    CREATE INDEX IF NOT EXISTS {p}ix_pword_page ON ocr_word(file_key, page);
    CREATE TABLE IF NOT EXISTS {p}vocab(
        file_key TEXT, lemma TEXT, lang TEXT, level TEXT,
        zipf REAL, freq_in_book INTEGER,
        PRIMARY KEY(file_key, lemma, lang));
    CREATE TABLE IF NOT EXISTS {p}vocab_page(
        file_key TEXT, page INTEGER, lemma TEXT, lang TEXT, count INTEGER,
        pos INTEGER DEFAULT 0,
        PRIMARY KEY(file_key, page, lemma, lang));
    CREATE INDEX IF NOT EXISTS {p}ix_pvpage ON vocab_page(file_key, page);
    CREATE TABLE IF NOT EXISTS {p}study_meta(
        file_key TEXT PRIMARY KEY, path TEXT, page_count INTEGER,
        lang TEXT, updated_at TEXT);
    -- 이 파일의 어휘는 보류 쪽이 통째로 대신한다(다시 만들기)
    CREATE TABLE IF NOT EXISTS {p}vocab_files(file_key TEXT PRIMARY KEY);
    -- 이 파일의 저장본은 지운 것으로 본다('단어장 다시 만들기')
    CREATE TABLE IF NOT EXISTS {p}cleared(file_key TEXT PRIMARY KEY);
"""

# 261026-6(응답성 SOT §6 '메인은 새 파일을 만들지 않는다', 사용자 결정): 보류 DB 는 프로세스마다 **새 파일**이다. 종전에는 본문 첫 쪽을
#   그리는 메인 스레드의 첫 `StudyStore()` 가 그 파일을 만들었는데, 새 exe(업데이트 직후)가 만드는 새 파일을 백신이 붙들어 1.37초 섰다
#   (1.0.1 빌드 시험 T1, 정지 스택 `_attach_pending`). 이제 앱 시작 때 배경 스레드가 먼저 만든다(`startup_pending`). 메인의 첫 붙이기는
#   그것이 끝났으면 바로, 아직이면 `PENDING_READY_WAIT_S` 까지 기다린다 — 기다리지 않고 함께 만들면 잠금 경합으로 '보류 없이 바로 저장' 으로
#   떨어질 수 있다(이 저장소의 약속을 깬다).
PENDING_READY_WAIT_S = 3.0
_PEND_PREP = {"started": False, "ready": None}


def prepare_pending() -> None:
    """보류 DB 파일과 표를 만든다(배경 스레드에서 — WAL). 실패해도 메인의 첫 붙이기가 종전처럼 만든다."""
    import threading
    if _PEND_PREP["ready"] is None:
        _PEND_PREP["ready"] = threading.Event()
    try:
        pp = pending_db_path()
        pp.parent.mkdir(parents=True, exist_ok=True)
        con = _dbutil.connect(pp, _dbutil.BUSY_MS_BG)          # 표준 연결 — WAL·대기 상한(응답성 SOT §4 ⑤)
        try:
            con.executescript(_PENDING_SCHEMA.format(p=""))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
    finally:
        _PEND_PREP["ready"].set()


def startup_pending() -> None:
    """앱 시작 때 배경 스레드 하나로: 이 프로세스의 보류 DB 를 먼저 만들고(첫 쪽이 곧 쓴다) 옛 보류 파일을 지운다."""
    prepare_pending()
    cleanup_stale_pending()


def start_pending_prep() -> None:
    """앱 진입점이 부른다 — 배경 스레드를 띄우기 **전에** 표식을 세워, 메인의 첫 붙이기가 기다릴지 알게 한다."""
    import threading
    _PEND_PREP["started"] = True
    _PEND_PREP["ready"] = threading.Event()
    threading.Thread(target=startup_pending, name="study-pending-prep", daemon=True).start()


def wait_pending_ready() -> bool:
    """배경 준비가 시작됐으면 끝나기를 기다린다(상한 `PENDING_READY_WAIT_S`). 준비를 띄우지 않은 실행(검사·도구)은 바로 True."""
    ev = _PEND_PREP["ready"]
    if not _PEND_PREP["started"] or ev is None:
        return True
    return ev.wait(PENDING_READY_WAIT_S)


def cleanup_stale_pending() -> int:
    """끝난(또는 죽은) 프로세스가 남긴 보류 DB 를 지운다 — 저장하지 않은 결과는 버리는 것이 규칙.
    다른 PolyPDF 창이 쓰고 있는 파일은 열려 있어 지워지지 않는다(그대로 둔다). 지운 수."""
    import os
    d = pending_db_path().parent
    mine = pending_db_path().name
    n = 0
    try:
        for f in d.glob("study_pending_*.db*"):
            if f.name.startswith(mine):
                continue
            try:
                os.remove(f); n += 1
            except OSError:
                pass
    except Exception:
        pass
    return n


def default_db_path() -> Path:
    """기존 settings/index 와 동일 폴더의 study.db."""
    try:
        from viewer.settings_store import settings_dir
        return settings_dir() / "study.db"
    except Exception:
        # GUI 밖(테스트) 폴백
        return Path.home() / ".polypdf_study.db"


class StudyStore:
    def __init__(self, db_path: str | Path | None = None,
                 busy_ms: int = _dbutil.BUSY_MS_BG):
        # 260906-9(응답성 SOT §4 ⑤ '어느 DB든'): 표준 연결 — WAL + 대기 상한.
        #   단어장 만들기 워커가 이 DB 를 적는 동안 UI 가 읽으면, 종전 저널 모드에서는
        #   최대 5초(= '응답 없음' 시간) 멈췄다. UI 쪽은 `busy_ms=_dbutil.BUSY_MS_UI`.
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.conn = _dbutil.connect(self.db_path, busy_ms)
        self._init_schema()
        self._pend = False
        if pending_enabled():
            try:
                self._attach_pending()
                self._pend = True
            except Exception:
                self._pend = False             # 못 붙이면 종전대로(바로 저장) — 동작은 잃지 않는다

    # --- 261019-1: 보류 저장소 ---------------------------------------------
    def _attach_pending(self) -> None:
        pp = pending_db_path()
        wait_pending_ready()                   # 261025-8 보완(261026-6): 배경이 만드는 중이면 끝나기를 짧게 — 메인이 새 파일을 만들지 않게
        pp.parent.mkdir(parents=True, exist_ok=True)
        self.conn.execute("ATTACH DATABASE ? AS p", (str(pp),))
        try:
            self.conn.execute("PRAGMA p.journal_mode = WAL")
        except Exception:
            pass
        self.conn.executescript(_PENDING_SCHEMA.format(p="p."))
        # 읽기는 TEMP VIEW(이름이 같아 main 표를 가린다) — 보류 ▶ 저장본
        hide_main = "m.file_key NOT IN (SELECT file_key FROM p.cleared)"
        self.conn.executescript(f"""
            CREATE TEMP VIEW IF NOT EXISTS ocr_page AS
              SELECT * FROM p.ocr_page UNION ALL
              SELECT m.* FROM main.ocr_page m WHERE {hide_main} AND NOT EXISTS
                (SELECT 1 FROM p.ocr_page q WHERE q.file_key=m.file_key AND q.page=m.page);
            CREATE TEMP VIEW IF NOT EXISTS ocr_word AS
              SELECT * FROM p.ocr_word UNION ALL
              SELECT m.* FROM main.ocr_word m WHERE {hide_main} AND NOT EXISTS
                (SELECT 1 FROM p.ocr_page q WHERE q.file_key=m.file_key AND q.page=m.page);
            CREATE TEMP VIEW IF NOT EXISTS vocab AS
              SELECT * FROM p.vocab UNION ALL
              SELECT m.* FROM main.vocab m WHERE {hide_main}
                AND m.file_key NOT IN (SELECT file_key FROM p.vocab_files);
            CREATE TEMP VIEW IF NOT EXISTS vocab_page AS
              SELECT * FROM p.vocab_page UNION ALL
              SELECT m.* FROM main.vocab_page m WHERE {hide_main}
                AND m.file_key NOT IN (SELECT file_key FROM p.vocab_files);
            CREATE TEMP VIEW IF NOT EXISTS study_meta AS
              SELECT * FROM p.study_meta UNION ALL
              SELECT m.* FROM main.study_meta m WHERE NOT EXISTS
                (SELECT 1 FROM p.study_meta q WHERE q.file_key=m.file_key);
            """)
        self.conn.commit()

    def _w(self, table: str) -> str:
        """쓰기 대상 표 이름 — 보류 중이면 p.표."""
        return f"p.{table}" if self._pend else f"main.{table}"

    def pending_keys(self) -> list:
        """보류 중인 결과가 있는 file_key 목록."""
        if not self._pend:
            return []
        keys = set()
        for t in ("ocr_page", "vocab", "vocab_page", "vocab_files", "cleared"):
            keys.update(r[0] for r in self.conn.execute(f"SELECT DISTINCT file_key FROM p.{t}"))
        return sorted(keys)

    def pending_summary(self, file_key: str) -> dict:
        """{'pages': OCR 쪽 수, 'vocab': 어휘 수} — 확인 창 문구용."""
        if not self._pend:
            return {"pages": 0, "vocab": 0}
        pg = self.conn.execute("SELECT COUNT(*) FROM p.ocr_page WHERE file_key=?", (file_key,)).fetchone()[0]
        vc = self.conn.execute("SELECT COUNT(*) FROM p.vocab WHERE file_key=?", (file_key,)).fetchone()[0]
        return {"pages": int(pg), "vocab": int(vc)}

    def commit_pending(self, file_key: str) -> bool:
        """[저장] — 그 파일의 보류 결과를 study.db 로 옮기고 보류에서 지운다. 옮긴 것이 있으면 True."""
        if not self._pend or file_key not in self.pending_keys():
            return False
        c = self.conn
        k = (file_key,)
        with c:
            if c.execute("SELECT 1 FROM p.cleared WHERE file_key=?", k).fetchone():
                for t in ("ocr_page", "ocr_word", "vocab", "vocab_page"):
                    c.execute(f"DELETE FROM main.{t} WHERE file_key=?", k)
            c.execute("DELETE FROM main.ocr_word WHERE file_key=? AND page IN"
                      " (SELECT page FROM p.ocr_page WHERE file_key=?)", (file_key, file_key))
            c.execute("INSERT OR REPLACE INTO main.ocr_page SELECT * FROM p.ocr_page WHERE file_key=?", k)
            c.execute("INSERT INTO main.ocr_word SELECT * FROM p.ocr_word WHERE file_key=?", k)
            if c.execute("SELECT 1 FROM p.vocab_files WHERE file_key=?", k).fetchone():
                c.execute("DELETE FROM main.vocab WHERE file_key=?", k)
                c.execute("DELETE FROM main.vocab_page WHERE file_key=?", k)
            c.execute("INSERT OR REPLACE INTO main.vocab SELECT * FROM p.vocab WHERE file_key=?", k)
            c.execute("INSERT OR REPLACE INTO main.vocab_page SELECT * FROM p.vocab_page WHERE file_key=?", k)
            c.execute("INSERT OR REPLACE INTO main.study_meta SELECT * FROM p.study_meta WHERE file_key=?", k)
            self._drop_pending(file_key)
        return True

    def discard_pending(self, file_key: str) -> None:
        """저장하지 않음 — 그 파일의 보류 결과를 버린다(저장본은 그대로)."""
        if self._pend:
            with self.conn:
                self._drop_pending(file_key)

    def _drop_pending(self, file_key: str) -> None:
        for t in _PENDING_TABLES + ("vocab_files", "cleared"):
            self.conn.execute(f"DELETE FROM p.{t} WHERE file_key=?", (file_key,))

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            -- OCR 결과(페이지 단위, 1회성 캐시)
            CREATE TABLE IF NOT EXISTS ocr_page(
                file_key TEXT, page INTEGER, text TEXT, dpi INTEGER,
                engine TEXT, source TEXT, conf REAL, done_at TEXT,
                PRIMARY KEY(file_key, page));
            -- 단어 좌표(페이지 내 하이라이트·페이지별 단어 조회)
            CREATE TABLE IF NOT EXISTS ocr_word(
                file_key TEXT, page INTEGER, lemma TEXT, surface TEXT, lang TEXT,
                x0 REAL, y0 REAL, x1 REAL, y1 REAL, conf REAL);
            CREATE INDEX IF NOT EXISTS ix_word_page  ON ocr_word(file_key, page);
            CREATE INDEX IF NOT EXISTS ix_word_lemma ON ocr_word(file_key, lemma);
            -- 어휘(표제어 단위, 난이도·빈도) — P2 에서 채움
            CREATE TABLE IF NOT EXISTS vocab(
                file_key TEXT, lemma TEXT, lang TEXT, level TEXT,
                zipf REAL, freq_in_book INTEGER,
                PRIMARY KEY(file_key, lemma, lang));
            -- 페이지↔표제어 매핑 (P3 UI: 현재 페이지 단어 조회) — P2
            CREATE TABLE IF NOT EXISTS vocab_page(
                file_key TEXT, page INTEGER, lemma TEXT, lang TEXT, count INTEGER,
                pos INTEGER DEFAULT 0,
                PRIMARY KEY(file_key, page, lemma, lang));
            CREATE INDEX IF NOT EXISTS ix_vpage ON vocab_page(file_key, page);
            -- 뜻·예문(전역 캐시 — 파일 간 공유) — P2
            CREATE TABLE IF NOT EXISTS vocab_def(
                lemma TEXT, lang TEXT, sense INTEGER, definition TEXT, source TEXT,
                PRIMARY KEY(lemma, lang, sense));
            CREATE TABLE IF NOT EXISTS vocab_example(
                lemma TEXT, lang TEXT, example TEXT, source TEXT,
                PRIMARY KEY(lemma, lang, source, example));
            -- 빌드 메타(진행 상태 요약)
            CREATE TABLE IF NOT EXISTS study_meta(
                file_key TEXT PRIMARY KEY, path TEXT, page_count INTEGER,
                lang TEXT, updated_at TEXT);
            """
        )
        # 260603: 구 study.db 에 vocab_page.pos 컬럼 추가(있으면 무시)
        try:
            self.conn.execute("ALTER TABLE vocab_page ADD COLUMN pos INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    # --- 재개(resume) ------------------------------------------------------
    def is_page_done(self, file_key: str, page: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM ocr_page WHERE file_key=? AND page=?", (file_key, page)
        ).fetchone()
        return row is not None

    def done_pages(self, file_key: str) -> set[int]:
        return {r["page"] for r in self.conn.execute(
            "SELECT page FROM ocr_page WHERE file_key=?", (file_key,))}

    # --- 저장 --------------------------------------------------------------
    def save_page(self, file_key: str, page: int, text: str, *,
                  dpi: int, engine: str, source: str, conf: float,
                  words: Iterable[dict], lang: str) -> None:
        """한 페이지의 OCR 결과(텍스트+단어좌표)를 트랜잭션으로 저장. 재저장 시 교체."""
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {self._w('ocr_page')} WHERE file_key=? AND page=?", (file_key, page))
        cur.execute(f"DELETE FROM {self._w('ocr_word')} WHERE file_key=? AND page=?", (file_key, page))
        cur.execute(
            f"INSERT INTO {self._w('ocr_page')}(file_key,page,text,dpi,engine,source,conf,done_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (file_key, page, text, dpi, engine, source, conf,
             time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        cur.executemany(
            f"INSERT INTO {self._w('ocr_word')}(file_key,page,lemma,surface,lang,x0,y0,x1,y1,conf)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(file_key, page, w.get("lemma", ""), w["surface"], lang,
              w["x0"], w["y0"], w["x1"], w["y1"], w.get("conf", 0.0))
             for w in words],
        )
        self.conn.commit()

    def set_meta(self, file_key: str, path: str, page_count: int, lang: str) -> None:
        self.conn.execute(
            f"INSERT INTO {self._w('study_meta')}(file_key,path,page_count,lang,updated_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(file_key) DO UPDATE SET"
            " path=excluded.path, page_count=excluded.page_count,"
            " lang=excluded.lang, updated_at=excluded.updated_at",
            (file_key, path, page_count, lang, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        self.conn.commit()

    # --- 조회 --------------------------------------------------------------
    def get_page_text(self, file_key: str, page: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT text FROM ocr_page WHERE file_key=? AND page=?", (file_key, page)
        ).fetchone()
        return row["text"] if row else None

    def get_page_dpi(self, file_key: str, page: int) -> int:
        """OCR 페이지의 렌더 DPI (좌표 단위 판별: >0 이면 픽셀@dpi, 0 이면 PDF point)."""
        row = self.conn.execute(
            "SELECT dpi FROM ocr_page WHERE file_key=? AND page=?", (file_key, page)
        ).fetchone()
        return int(row["dpi"]) if row else 0

    def get_page_words(self, file_key: str, page: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT surface,lemma,lang,x0,y0,x1,y1,conf FROM ocr_word"
            " WHERE file_key=? AND page=? ORDER BY y0,x0", (file_key, page))]

    def page_progress(self, file_key: str) -> tuple[int, int]:
        """(완료 페이지 수, 전체 페이지 수). 전체는 study_meta 기준."""
        done = self.conn.execute(
            "SELECT COUNT(*) c FROM ocr_page WHERE file_key=?", (file_key,)
        ).fetchone()["c"]
        row = self.conn.execute(
            "SELECT page_count FROM study_meta WHERE file_key=?", (file_key,)
        ).fetchone()
        return done, (row["page_count"] if row else 0)

    def iter_all_text(self, file_key: str) -> Iterable[tuple[int, str]]:
        for r in self.conn.execute(
            "SELECT page,text FROM ocr_page WHERE file_key=? ORDER BY page", (file_key,)):
            yield r["page"], r["text"]

    # --- 어휘(P2) ----------------------------------------------------------
    def clear_vocab(self, file_key: str) -> None:
        for tbl in ("vocab", "vocab_page"):
            self.conn.execute(f"DELETE FROM {self._w(tbl)} WHERE file_key=?", (file_key,))
        if self._pend:                     # 저장본 어휘는 가린다(저장할 때 바뀐다)
            self.conn.execute("INSERT OR IGNORE INTO p.vocab_files(file_key) VALUES(?)", (file_key,))
        self.conn.commit()

    def clear_file(self, file_key: str) -> None:
        """260615-6: 해당 파일의 OCR·어휘 캐시 전체 삭제 → '단어장 다시 만들기'용."""
        for tbl in ("ocr_page", "ocr_word", "vocab", "vocab_page"):
            self.conn.execute(f"DELETE FROM {self._w(tbl)} WHERE file_key=?", (file_key,))
        if self._pend:                     # 저장본은 [저장]할 때 지운다 — 그 전까지는 가리기만
            self.conn.execute("INSERT OR IGNORE INTO p.cleared(file_key) VALUES(?)", (file_key,))
            self.conn.execute("INSERT OR IGNORE INTO p.vocab_files(file_key) VALUES(?)", (file_key,))
        self.conn.commit()

    def save_vocab(self, file_key: str, rows: Iterable[dict]) -> None:
        if self._pend:
            self.conn.execute("INSERT OR IGNORE INTO p.vocab_files(file_key) VALUES(?)", (file_key,))
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {self._w('vocab')}(file_key,lemma,lang,level,zipf,freq_in_book)"
            " VALUES(?,?,?,?,?,?)",
            [(file_key, r["lemma"], r["lang"], r["level"], r.get("zipf"),
              r.get("freq_in_book", 0)) for r in rows])
        self.conn.commit()

    def save_page_lemmas(self, file_key: str, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {self._w('vocab_page')}(file_key,page,lemma,lang,count,pos)"
            " VALUES(?,?,?,?,?,?)",
            [(file_key, r["page"], r["lemma"], r["lang"], r.get("count", 1),
              r.get("pos", 0)) for r in rows])
        self.conn.commit()

    def save_defs(self, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vocab_def(lemma,lang,sense,definition,source)"
            " VALUES(?,?,?,?,?)",
            [(r["lemma"], r["lang"], r["sense"], r["definition"], r["source"])
             for r in rows])
        self.conn.commit()

    def save_examples(self, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vocab_example(lemma,lang,example,source)"
            " VALUES(?,?,?,?)",
            [(r["lemma"], r["lang"], r["example"], r["source"]) for r in rows])
        self.conn.commit()

    def get_page_study(self, file_key: str, page: int,
                       levels: Optional[Iterable[str]] = None,
                       user_overrides: Optional[dict] = None) -> list[dict]:
        """P3 UI — 현재 페이지의 학습 단어(난이도·뜻·예문 포함). 등장 빈도순.
        user_overrides: {(lemma,lang): {definition, example}} 가 있으면 우선 적용."""
        sql = (
            "SELECT vp.lemma, v.lang, v.level, v.zipf, vp.count, vp.pos "
            "FROM vocab_page vp JOIN vocab v"
            "  ON v.file_key=vp.file_key AND v.lemma=vp.lemma AND v.lang=vp.lang "
            "WHERE vp.file_key=? AND vp.page=?")
        args: list = [file_key, page]
        lv = list(levels) if levels else None
        if lv:
            sql += " AND v.level IN (%s)" % ",".join("?" * len(lv))
            args += lv
        sql += " ORDER BY vp.count DESC, v.zipf ASC"
        out = []
        for r in self.conn.execute(sql, args):
            d = dict(r)
            d["definitions"] = [dict(x) for x in self.conn.execute(
                "SELECT sense,definition,source FROM vocab_def"
                " WHERE lemma=? AND lang=? ORDER BY sense", (r["lemma"], r["lang"]))]
            d["examples"] = [dict(x) for x in self.conn.execute(
                "SELECT example,source FROM vocab_example"
                " WHERE lemma=? AND lang=? LIMIT 3", (r["lemma"], r["lang"]))]
            # 사용자 편집 우선 적용
            if user_overrides:
                ov = user_overrides.get((r["lemma"], r["lang"]))
                if ov:
                    if ov.get("definition"):
                        d["definitions"] = [{"sense": 0, "definition": ov["definition"],
                                             "source": "user"}]
                        d["user_edited"] = True
                    if ov.get("example"):
                        d["examples"] = [{"example": ov["example"], "source": "user"}]
                        d["user_edited"] = True
            out.append(d)
        return out

    def vocab_count(self, file_key: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM vocab WHERE file_key=?", (file_key,)
        ).fetchone()["c"]

    def vocab_pages(self, file_key: str) -> list:
        """어휘가 있는 페이지 번호(오름차순)."""
        return [r["page"] for r in self.conn.execute(
            "SELECT DISTINCT page FROM vocab_page WHERE file_key=? ORDER BY page",
            (file_key,))]

    def close(self) -> None:
        self.conn.close()


class UserStore:
    """사용자 편집(뜻·예시) 전용 별도 DB. study.db 재생성과 무관하게 보존.
    조회 시 study.db 의 자동 뜻/예시보다 **우선** 적용."""

    def __init__(self, db_path: str | Path | None = None,
                 busy_ms: int = _dbutil.BUSY_MS_BG):
        if db_path is None:
            try:
                from viewer.settings_store import settings_dir
                db_path = settings_dir() / "user_study.db"
            except Exception:
                db_path = Path.home() / ".polypdf_user_study.db"
        self.db_path = Path(db_path)
        self.conn = _dbutil.connect(self.db_path, busy_ms)   # 260906-9(§4 ⑤)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS user_word("
            " lemma TEXT, lang TEXT, definition TEXT, example TEXT, updated_at TEXT,"
            " PRIMARY KEY(lemma, lang))")
        # 260606: 선택단어/삭제 이벤트(날짜별 누적). action: 'select' | 'delete'
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS sel_event("
            " file_key TEXT, lemma TEXT, date TEXT, action TEXT, ts TEXT)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sel ON sel_event(file_key, lemma)")
        self.conn.commit()

    # --- 선택단어/삭제 (260606) -------------------------------------------
    def add_event(self, file_key: str, lemma: str, action: str,
                  date: Optional[str] = None) -> None:
        date = date or time.strftime("%Y.%m.%d")
        self.conn.execute(
            "INSERT INTO sel_event(file_key,lemma,date,action,ts) VALUES(?,?,?,?,?)",
            (file_key, lemma, date, action, time.strftime("%Y-%m-%dT%H:%M:%S")))
        self.conn.commit()

    def _latest_actions(self, file_key: str, upto_date: Optional[str] = None) -> dict:
        """lemma -> 최신 action (upto_date 지정 시 그 날짜까지만 반영)."""
        q = "SELECT lemma, action, date, ts FROM sel_event WHERE file_key=?"
        args = [file_key]
        if upto_date:
            q += " AND date<=?"
            args.append(upto_date)
        q += " ORDER BY ts"
        latest = {}
        for r in self.conn.execute(q, args):
            latest[r["lemma"]] = r["action"]
        return latest

    def deleted_set(self, file_key: str, upto_date: Optional[str] = None) -> set:
        return {lm for lm, a in self._latest_actions(file_key, upto_date).items()
                if a == "delete"}

    def selected_set(self, file_key: str, upto_date: Optional[str] = None) -> set:
        return {lm for lm, a in self._latest_actions(file_key, upto_date).items()
                if a == "select"}

    def event_dates(self, file_key: str) -> list:
        """이벤트가 있는 날짜(역순)."""
        return [r["date"] for r in self.conn.execute(
            "SELECT DISTINCT date FROM sel_event WHERE file_key=? ORDER BY date DESC",
            (file_key,))]

    def delete_date(self, file_key: str, date: str) -> None:
        self.conn.execute("DELETE FROM sel_event WHERE file_key=? AND date=?",
                          (file_key, date))
        self.conn.commit()

    def set_word(self, lemma: str, lang: str,
                 definition: str = "", example: str = "") -> None:
        self.conn.execute(
            "INSERT INTO user_word(lemma,lang,definition,example,updated_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(lemma,lang) DO UPDATE SET"
            " definition=excluded.definition, example=excluded.example,"
            " updated_at=excluded.updated_at",
            (lemma, lang, definition or "", example or "",
             time.strftime("%Y-%m-%dT%H:%M:%S")))
        self.conn.commit()

    def get_word(self, lemma: str, lang: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT definition,example FROM user_word WHERE lemma=? AND lang=?",
            (lemma, lang)).fetchone()
        return dict(row) if row else None

    def all_words(self) -> dict:
        return {(r["lemma"], r["lang"]): {"definition": r["definition"],
                                          "example": r["example"]}
                for r in self.conn.execute(
                    "SELECT lemma,lang,definition,example FROM user_word")}

    def close(self) -> None:
        self.conn.close()
