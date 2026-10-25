"""SQLite FTS5 기반 PDF 텍스트 인덱서.

증분 인덱싱: 파일 mtime 이 DB 의 기록과 다르면 재인덱싱.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

from viewer import dbutil as _dbutil
from viewer import pacing as _pacing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import fitz


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    file_path: str
    file_name: str
    page_index: int      # 0-based
    match_count: int     # 페이지 안에서의 매치 개수
    snippet: str         # 미리보기


# ---------------------------------------------------------------------------
# 인덱서
# ---------------------------------------------------------------------------

# FTS5 가 사용 가능한지 확인하기 위한 SQL
_HAS_FTS5_SQL = """
SELECT EXISTS(SELECT 1 FROM pragma_compile_options WHERE compile_options = 'ENABLE_FTS5');
"""


_WS = re.compile(r"\s+")


def flat_text(s: str) -> str:
    """261019-4(검색창 SOT §3.1): 빈칸·줄바꿈을 모두 뺀 글 — 색인과 질의를 같은 모양으로 맞춘다.
    글자층은 줄 끝마다 줄바꿈이 들어 있어(문단 안에서도) '아스팔트 포장' 이 '아스팔트\n포장' 으로 남는다."""
    return _WS.sub("", s or "")


def flat_pattern(q: str):
    """질의 글자 사이에 빈칸·줄바꿈이 얼마든 있어도 맞는 정규식 — 개수·미리보기용(색인 비교와 같은 뜻)."""
    qf = flat_text(q)
    return re.compile(r"\s*".join(re.escape(c) for c in qf), re.IGNORECASE) if qf else None


def _apply_text_fixes(file_path, page: int, text: str) -> str:
    """260908-3: 텍스트 창 교정을 색인 본문에 반영(텍스트 창 SOT §5.3).

    저장소가 없거나 교정이 없으면 원문 그대로 — 인덱싱은 이것 때문에 실패하지 않는다."""
    try:
        from viewer.text_fix_store import store
        return store().apply_to_copy(file_path, page, text)
    except Exception:
        return text


class PdfIndex:
    """PDF 폴더에 대한 FTS5 인덱스를 관리.

    스키마:
        files(id INTEGER PK, path TEXT UNIQUE, mtime REAL, page_count INTEGER)
        pages(file_id INTEGER, page_index INTEGER, text TEXT)
        pages_fts(text, file_id UNINDEXED, page_index UNINDEXED) - FTS5 가상 테이블
    """

    # 260906-6(응답성 SOT §4 ⑤ 'DB 잠금 의무'): 대기 상한을 **부르는 쪽이 정한다**.
    #   sqlite3 의 기본 대기는 5.0초인데, 이는 Windows 가 창을 '응답 없음' 으로 표시하는
    #   시간과 **정확히 같다** — 배경 인덱싱이 쓰기를 쥔 사이 UI 스레드가 조회 하나만 해도
    #   그대로 5초를 기다려 창이 죽은 것처럼 보인다(실측 단일 조회 2.49초 정지).
    #   260906-9: 값·거는 방법은 `viewer.dbutil` 이 소유한다(어느 DB든 같은 규칙).
    #   여기 이름은 기존 호출부·검사 호환을 위해 남긴 별칭이다.
    BUSY_MS_UI = _dbutil.BUSY_MS_UI     # UI 스레드: 기다리지 않는다(못 읽으면 '모름')
    BUSY_MS_BG = _dbutil.BUSY_MS_BG     # 워커: 얼마든 기다려도 좋다

    def __init__(self, db_path: str | Path, busy_ms: int = BUSY_MS_BG, verify: bool = False):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrated = False
        self.busy_ms = int(busy_ms)
        # 261009-14(응답성 SOT §4 ⑤ 손상 복구): 손상 표식이 있으면 열기 전에 새로 만든다 —
        #   쿼리 도중에야 드러나는 손상('malformed')은 여는 순간에는 잡히지 않는다(설치본 실측).
        #   다른 연결이 파일을 쥐고 있어 지우지 못하면 표식을 남겨 두고 다음 열기에서 다시 한다.
        mark = self._corrupt_mark(self.db_path)
        if mark.exists():
            size = self._db_size(self.db_path)
            if self._remove_db_files(self.db_path):
                self.log_reset(self.db_path, "손상 표식을 보고 지움", size)
                try:
                    mark.unlink()
                except OSError:
                    pass
                self.migrated = True
        try:
            self.conn = _dbutil.connect(self.db_path, self.busy_ms)
            self._init_schema()
            # 사용자가 '인덱스 재구축' 을 고르면 배경에서 무결성까지 본다(큰 색인은 수 초 — 워커 전용)
            if verify:
                if self.conn.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("database disk image is malformed (quick_check)")
                self._stamp_checked(self.db_path)
        except sqlite3.DatabaseError as e:
            # 260827: index.db 손상(malformed) → 파일 삭제 후 새로 생성(캐시라 안전).
            #   다음 인덱싱이 다시 채운다. PdfIndex 생성이 실패해 검색/인덱싱이 통째로
            #   깨지던 문제 방지.
            # ★ 260906-6: '손상' 만 재생성한다. `OperationalError`("database is locked")도
            #   `DatabaseError` 의 하위라, 종전 코드는 **잠깐 잠긴 것만으로 100MB 색인을
            #   통째로 지웠다**(대기 상한을 200ms 로 줄이면서 현실이 된 위험). 잠금·권한
            #   등은 그대로 올려 보내고, 부르는 쪽이 '이번엔 못 읽었다'로 넘긴다.
            if not self._is_corrupt_error(e):
                raise
            self._recreate_corrupt_db(str(e))

    _is_corrupt_error = staticmethod(_dbutil.is_corrupt_error)

    ERROR_LOG_NAME = "error.log"        # main.ERROR_LOG_NAME 과 같은 파일(마스터 §14.7.3 안전망)
    ERROR_LOG_MAX = 1_000_000           # main.ERROR_LOG_MAX 와 같은 규칙 — 넘으면 비우고 새로

    @staticmethod
    def _db_size(db_path) -> int:
        try:
            return os.path.getsize(db_path)
        except OSError:
            return -1

    @classmethod
    def log_reset(cls, db_path, reason: str, size: int | None = None) -> None:
        """261025-7(검색창 SOT §3 '색인을 지우면 까닭을 남긴다'): 색인을 지우거나 비울 때 `index.db` 옆
        `error.log` 에 한 줄 — 시각·까닭·경로·크기·프로세스. 10-25 에 사용자 색인이 946MB → 16MB 로 새로
        만들어졌는데 기록이 없어 어느 길이었는지 알 수 없었다. 기록이 실패해도 색인은 계속한다."""
        import time
        try:
            if size is None:
                size = cls._db_size(db_path)
            log = Path(db_path).parent / cls.ERROR_LOG_NAME
            mode = "w" if log.exists() and log.stat().st_size > cls.ERROR_LOG_MAX else "a"
            exe = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else sys.executable
            reason = " ".join(str(reason).split())          # 한 줄로(오류 문구에 줄바꿈이 있을 수 있다)
            with open(log, mode, encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n[색인 초기화] 까닭={reason} "
                        f"경로={db_path} 크기={size} pid={os.getpid()} 실행={exe}\n\n")
        except Exception:
            pass

    INTEGRITY_DAYS = 7                  # 261025-8: 배경 색인이 이 날수마다 quick_check(응답성 SOT §4 ⑤)

    @staticmethod
    def _checked_stamp(db_path) -> Path:
        return Path(str(db_path) + ".checked")

    @classmethod
    def integrity_due(cls, db_path) -> bool:
        """261025-8(응답성 SOT §4 ⑤ '정기 점검'): 마지막 무결성 점검이 `INTEGRITY_DAYS` 보다 오래됐으면 True.

        쿼리에 걸리지 않는 손상(`Rowid out of order` 등)은 '손상 복구' 가 보지 못한다 — 10-25 에 사용자 색인이
        6일 넘게 손상된 채였다. **배경 색인(자식 프로세스·워커)만** 부른다 — 큰 색인은 수 초 읽는다(UI 스레드 금지).
        색인이 아직 없으면 False(새로 만든다), 표식이 없으면 True(처음 한 번)."""
        import time
        try:
            if not os.path.exists(db_path):
                return False
            stamp = cls._checked_stamp(db_path)
            if not stamp.exists():
                return True
            return time.time() - stamp.stat().st_mtime > cls.INTEGRITY_DAYS * 86400
        except OSError:
            return False

    @classmethod
    def _stamp_checked(cls, db_path) -> None:
        try:
            cls._checked_stamp(db_path).write_text("ok", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _corrupt_mark(db_path) -> Path:
        return Path(str(db_path) + ".corrupt")

    @classmethod
    def mark_corrupt(cls, db_path, reason: str = "") -> None:
        """261009-14: 쿼리 도중 손상을 만난 쪽이 부른다 — 다음에 여는 연결이 새로 만든다."""
        try:
            cls._corrupt_mark(db_path).write_text("1", encoding="utf-8")
        except OSError:
            pass
        cls.log_reset(db_path, "손상 표식을 남김" + (f": {reason}" if reason else ""))

    @staticmethod
    def _remove_db_files(db_path) -> bool:
        """본파일과 짝 파일(-wal·-shm·-journal)을 지운다. 본파일을 못 지우면 False(다른 연결이 쥐고 있다)."""
        import os as _os
        ok = True
        for suf in ("", "-wal", "-shm", "-journal"):
            try:
                _os.remove(str(db_path) + suf)
            except FileNotFoundError:
                pass
            except OSError:
                ok = ok and suf != ""
        return ok

    def _recreate_corrupt_db(self, reason: str = ""):
        try:
            self.conn.close()
        except Exception:
            pass
        size = self._db_size(self.db_path)
        if self._remove_db_files(self.db_path):
            self.log_reset(self.db_path, "손상을 만나 새로 만듦" + (f": {reason}" if reason else ""), size)
        else:
            self.mark_corrupt(self.db_path, f"지우지 못함(다음 열기에서) {reason}".strip())   # 261009-14
        self.conn = _dbutil.connect(self.db_path, self.busy_ms)
        self._init_schema()
        self.migrated = True

    def _tune(self):
        """260906-6/9: 연결 하나에 거는 잠금 규칙 — **WAL + 대기 상한**.

        본문은 `viewer.dbutil.tune` 이 소유한다(응답성 SOT §4 ⑤ '어느 DB든' —
        `index.db` 만 고쳐 두면 `dict.db`·`study.db` 에 같은 사고가 남는다).
        종전 `index.db` 는 SQLite 기본인 롤백 저널 모드였고, 그 모드는 **쓰는 쪽이 읽는
        쪽을 막는다** — 배경 인덱싱 중 UI 조회 하나가 **2.49초** 멈추는 것을 실측했다."""
        _dbutil.tune(self.conn, self.busy_ms)

    # --- 스키마 ------------------------------------------------------------

    # 260825: FTS 토크나이저 스키마 버전. 2=trigram(파괴적, 폐기), 3=trigram(내용 보존 복사).
    # 261014-19: 4 = 표 캐시(`page_tables`)를 한 번 비운다 — 공유 pdfplumber 문서를 여러 스레드가 동시에 써
    #   깨진 표가 저장돼 있을 수 있다(텍스트 창 SOT §3 규칙 8). 캐시라 지워도 안전하다(다시 판다).
    # 261019-4(검색창 SOT §3.1): 5 = 새 표 `pages2`(빈칸 없는 `flat` 에 트라이그램, 원문 `text` 는 보관만).
    #   옛 `pages_fts` 는 지우지 않는다 — 파일마다 다시 색인될 때 옮겨 간다(`size=-1` 표식, 배경 색인).
    #   그동안 검색은 두 표를 함께 본다(검색이 비는 구간 없음 — §3 '파괴적 재생성 금지').
    SCHEMA_VERSION = 5
    YIELD_S = 0.005          # 260906-5: 배경 작업의 GIL 양보 간격(응답성 SOT §4 ②)
    # 260908-5(응답성 SOT §4 ⑦): 간격이 아니라 **점유율**로 조절한다.
    #   5ms 간격만으로는 쪽 하나가 무거울 때 배경이 벽시계를 거의 다 쓴다 —
    #   실측 100초 인덱싱 동안 UI 하트비트가 기대의 47% 였다.
    BG_DUTY = _pacing.BG_DUTY
    WRITE_CHUNK = 128        # 260906-6: 쓰기 트랜잭션 한 번에 담는 쪽 수(잠금 시간 상한)
    PAGES_PENDING = -1       # 260906-6: '본문을 아직 다 적지 못했다' 표식
    _FTS_TRIGRAM = ("CREATE VIRTUAL TABLE {name} USING fts5("
                    "text, file_id UNINDEXED, page_index UNINDEXED, tokenize='trigram')")
    _FTS_FLAT = ("CREATE VIRTUAL TABLE IF NOT EXISTS pages2 USING fts5("
                 "flat, text UNINDEXED, file_id UNINDEXED, page_index UNINDEXED, tokenize='trigram')")

    def _init_schema(self):
        self.migrated = False
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS files(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                mtime REAL NOT NULL,
                page_count INTEGER NOT NULL
            );
            """
        )
        # 260618-3: 파일 용량(size) 컬럼 — 수정날짜+용량 변화 없으면 재인덱싱 생략.
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "size" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN size INTEGER")
        # 260906-4: 책갈피창 '목록 조사'(암호화·내부 책갈피 유무) 결과의 영구 캐시.
        #   ★ `files` 와 **별도 테이블**이다 — files 에 얹으면 인덱싱되지 않은 폴더에서는
        #   적을 자리가 없고, 조사만 하고 행을 만들면 `needs_reindex` 가 False 가 되어
        #   그 파일이 영영 인덱싱되지 않는다(검색이 조용히 비는 함정).
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS probe_cache(
                key TEXT PRIMARY KEY,      -- pathutil.norm_key(경로)
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                encrypted INTEGER NOT NULL,
                has_toc INTEGER,           -- NULL = 잠겨서 모름
                auth TEXT,
                signed INTEGER             -- 261010-27(보안 SOT §4): NULL = 모름(열이 없던 옛 행)
            );
            """
        )
        # 261010-27: 옛 index.db 에는 signed 열이 없다 — 더한다(값은 NULL → 다음 조사 때 채움)
        try:
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(probe_cache)").fetchall()}
            if "signed" not in cols:
                self.conn.execute("ALTER TABLE probe_cache ADD COLUMN signed INTEGER")
                self.conn.commit()
        except Exception:
            pass

        # 260908-5(성능): 표 인식 결과의 **영구 캐시**. pdfplumber 의 표 찾기는 쪽당
        #   150ms~7초로 비싸고, 같은 문서를 다시 열면 처음부터 다시 판다. 크기·수정시각이
        #   같으면 결과도 같으므로 여기에 남겨 **다음 실행에서도 그대로 쓴다**
        #   (`probe_cache` 와 같은 생각 — 텍스트 창 SOT §3.0).
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS page_tables(
                key TEXT NOT NULL,         -- pathutil.norm_key(경로)
                page INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                data TEXT NOT NULL,        -- JSON: [[bbox, rows], …]
                PRIMARY KEY(key, page)
            );
            """
        )

        # 260825: FTS5 tokenizer 를 trigram 으로 — LIKE '%…%' 부분일치(한글 포함)를 **색인**으로.
        #   ★ 기존 인덱스 텍스트를 **보존 복사**(재인덱싱 없이) → 검색이 비는 구간 없음.
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='pages_fts'"
        ).fetchone()
        exists = row is not None
        is_trigram = exists and ("trigram" in (row["sql"] or ""))
        uv = int(self.conn.execute("PRAGMA user_version").fetchone()[0] or 0)

        if not exists:
            self.conn.execute(self._FTS_TRIGRAM.format(name="pages_fts"))
        elif not is_trigram:
            # 구 unicode61 → trigram 으로 **내용 보존 복사**(pages_fts 의 텍스트 재사용).
            #   손상(malformed) 등으로 실패하면 예외가 __init__ 으로 전파되어 index.db 를
            #   삭제·재생성(캐시라 안전) → 재인덱싱으로 복구.
            self.conn.execute("DROP TABLE IF EXISTS pages_fts_new")
            self.conn.execute(self._FTS_TRIGRAM.format(name="pages_fts_new"))
            self.conn.execute(
                "INSERT INTO pages_fts_new(text, file_id, page_index) "
                "SELECT text, file_id, page_index FROM pages_fts")
            self.conn.execute("DROP TABLE pages_fts")
            self.conn.execute("ALTER TABLE pages_fts_new RENAME TO pages_fts")
            self.migrated = True

        self.conn.execute(self._FTS_FLAT)                  # 261019-4

        # 일관성: 색인이 비었는데 files 기록만 남아있으면(구 파괴적 마이그레이션 잔재 등)
        #   needs_reindex 가 계속 False → 검색 0 이던 상태 → files 비워 재인덱싱 유도.
        if uv < self.SCHEMA_VERSION:
            try:
                # 261016-8: 0 인지만 본다 — count(*) 는 색인 전체를 읽는다(`is_empty`)
                fts_empty = self.is_empty()
                files_any = self.conn.execute("SELECT 1 FROM files LIMIT 1").fetchone() is not None
                if fts_empty and files_any:
                    n = self.conn.execute("SELECT count(*) FROM files").fetchone()[0]
                    self.conn.execute("DELETE FROM files")
                    self.migrated = True
                    self.log_reset(self.db_path, f"스키마 정리 — 본문 색인이 비어 files {n}행을 비움(v{uv}→v{self.SCHEMA_VERSION})")
            except Exception:
                pass
            if uv < 4:
                try:
                    self.conn.execute("DELETE FROM page_tables")
                except Exception:
                    pass
            if uv < 5:
                # 261019-4: 옛 표의 파일은 다음 배경 색인 때 새 표로 다시 읽는다(옛 글은 그때까지 그대로 검색된다)
                try:
                    self.conn.execute("UPDATE files SET size = -1")
                except Exception:
                    pass
            self.conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        self.conn.commit()

    # --- 인덱싱 ------------------------------------------------------------

    # --- 260906-4: 목록 조사(표식) 캐시 -------------------------------------
    def probe_get(self, file_path, size: int, mtime: float):
        """저장해 둔 (암호화, 책갈피유무, 인증상태, 서명). 모르거나 파일이 바뀌었으면 None.
        서명 열이 비어 있으면(옛 행) 모르는 것으로 본다 — 한 번 다시 조사한다(261010-27).

        `size`/`mtime` 는 **호출측이 지금 디스크에서 본 값** — 기록과 다르면 내용이
        바뀐 것이므로 쓰지 않는다(재인덱싱 판정과 같은 기준)."""
        from viewer.pathutil import norm_key
        row = self.conn.execute(
            "SELECT size, mtime, encrypted, has_toc, auth, signed FROM probe_cache WHERE key=?",
            (norm_key(file_path),)).fetchone()
        if row is None:
            return None
        try:
            if int(row["size"]) != int(size) or abs(float(row["mtime"]) - float(mtime)) > 1:
                return None
        except Exception:
            return None
        if row["signed"] is None:
            return None
        has_toc = None if row["has_toc"] is None else bool(row["has_toc"])
        return (bool(row["encrypted"]), has_toc, row["auth"], bool(row["signed"]))

    def probe_set(self, file_path, size: int, mtime: float,
                  enc: bool, has_toc, auth, signed: bool = False) -> None:
        """조사 결과 기록(같은 파일은 덮어쓴다). 인덱싱 여부와 무관하게 남는다."""
        from viewer.pathutil import norm_key
        self.conn.execute(
            "INSERT OR REPLACE INTO probe_cache(key, size, mtime, encrypted, has_toc, auth, signed)"
            " VALUES(?, ?, ?, ?, ?, ?, ?)",
            (norm_key(file_path), int(size), float(mtime), 1 if enc else 0,
             None if has_toc is None else (1 if has_toc else 0), auth, 1 if signed else 0))
        self.conn.commit()

    # --- 260908-5: 표 인식 캐시 -------------------------------------------
    def tables_get(self, file_path, page: int, size: int, mtime: float):
        """저장해 둔 표 결과. 모르거나 파일이 바뀌었으면 None."""
        import json as _json
        from viewer.pathutil import norm_key
        try:
            row = self.conn.execute(
                "SELECT size, mtime, data FROM page_tables WHERE key=? AND page=?",
                (norm_key(file_path), int(page))).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        try:
            if int(row["size"]) != int(size)                     or abs(float(row["mtime"]) - float(mtime)) > 1:
                return None
            return _json.loads(row["data"])
        except Exception:
            return None

    def tables_set(self, file_path, page: int, size: int, mtime: float, data) -> None:
        """표 결과 기록(같은 쪽은 덮어쓴다)."""
        import json as _json
        from viewer.pathutil import norm_key
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO page_tables(key, page, size, mtime, data)"
                " VALUES(?, ?, ?, ?, ?)",
                (norm_key(file_path), int(page), int(size), float(mtime),
                 _json.dumps(data, ensure_ascii=False)))
            self.conn.commit()
        except Exception:
            pass

    def _find_file_row(self, file_path, cols: str = "id, mtime, size"):
        """260905(검색 SOT §3): 경로로 `files` 행 찾기 — **정확 일치 먼저, 없으면 정규화 키**.

        ★ 같은 폴더를 대소문자만 다른 경로로 열면(`…\\sub` vs `…\\SUB`) 정확 일치가 빗나가
        멀쩡한 파일을 다시 읽었다(실측 재현). SQL 변환은 검색 범위와 **같은 식**을 쓴다(§7.0).
        정확 일치를 먼저 두는 것은 비용 때문 — 정규화 조회는 UNIQUE 색인을 못 타 전체 훑기다."""
        row = self.conn.execute(
            f"SELECT {cols} FROM files WHERE path = ?", (str(file_path),)
        ).fetchone()
        if row is not None:
            return row
        from viewer.pathutil import norm_key
        return self.conn.execute(
            f"SELECT {cols} FROM files WHERE lower(replace(path,'/','\\')) = ?",
            (norm_key(file_path),),
        ).fetchone()

    def needs_reindex(self, file_path: Path) -> bool:
        """260618-3: 기록된 수정날짜(mtime)+용량(size) 모두 변화 없으면 재인덱싱 생략.
        size 가 NULL(구버전 DB 기록)인 경우는 mtime 만으로 판단(업그레이드 시 불필요한
        전체 재인덱싱 방지)."""
        row = self._find_file_row(file_path, "mtime, size, page_count")
        if row is None:
            return True
        try:
            # 260906-6: 본문을 다 적기 전에 끊긴 행은 다시 읽는다(§5 ⑤).
            if int(row["page_count"]) < 0:
                return True
        except Exception:
            pass
        try:
            st = file_path.stat()
            if abs(row["mtime"] - st.st_mtime) > 1e-3:
                return True
            if row["size"] is not None and int(row["size"]) != int(st.st_size):
                return True
            return False
        except OSError:
            return False  # 파일이 사라진 경우는 재인덱싱 안 함

    def remove_file(self, file_path: Path):
        row = self._find_file_row(file_path, "id")      # 260905: 철자가 달라도 찾는다
        if row:
            fid = row["id"]
            self.conn.execute("DELETE FROM pages_fts WHERE file_id = ?", (fid,))
            self.conn.execute("DELETE FROM pages2 WHERE file_id = ?", (fid,))
            self.conn.execute("DELETE FROM files WHERE id = ?", (fid,))
            self.conn.commit()

    def invalidate(self, file_path) -> bool:
        """261019-4: 이 파일을 다음 색인 때 다시 읽게 표시한다(내용은 그대로 — 검색은 계속 된다).
        OCR 결과를 [저장]해 스캔 쪽 글이 바뀌었을 때 부른다(파일 자체는 그대로라 mtime·size 로는 모른다)."""
        row = self._find_file_row(file_path, "id")
        if not row:
            return False
        with self.conn:
            self.conn.execute("UPDATE files SET size = -1 WHERE id = ?", (row["id"],))
        return True

    def rename_file(self, old_path: Path, new_path: Path) -> bool:
        """261008-1(마스터 §4.7.14): 이름만 바뀐 파일 — 본문은 그대로이니 **경로만** 고친다.

        다시 색인하면 그 사이 검색에서 빠지고, 새 색인 작업이 진행 중인 다른 색인(예: 방금 더한
        파일들)을 취소한다(`_start_index_worker` 는 한 번에 하나). 목록 조사·표 캐시 키도 옮긴다.
        새 경로에 옛 행이 남아 있으면(같은 이름을 지웠다 다시 쓴 경우) 그 행을 먼저 지운다.
        색인에 없던 파일이면 False — 부른 쪽이 색인을 건다."""
        row = self._find_file_row(old_path, "id")
        if not row:
            return False
        from viewer.pathutil import norm_key
        ok, nk = norm_key(str(old_path)), norm_key(str(new_path))
        with self.conn:
            stale = self.conn.execute(
                "SELECT id FROM files WHERE path = ?", (str(new_path),)).fetchone()
            if stale and stale["id"] != row["id"]:
                self.conn.execute("DELETE FROM pages_fts WHERE file_id = ?", (stale["id"],))
                self.conn.execute("DELETE FROM pages2 WHERE file_id = ?", (stale["id"],))
                self.conn.execute("DELETE FROM files WHERE id = ?", (stale["id"],))
            self.conn.execute("UPDATE files SET path = ? WHERE id = ?", (str(new_path), row["id"]))
            if ok != nk:
                for tbl in ("probe_cache", "page_tables"):
                    self.conn.execute(f"DELETE FROM {tbl} WHERE key = ?", (nk,))
                    self.conn.execute(f"UPDATE {tbl} SET key = ? WHERE key = ?", (nk, ok))
        return True

    def _pace(self):
        """응답성 SOT §4 ⑦ — 방금 일한 만큼 비례해 쉰다(폴더 전체가 한 박자를 공유)."""
        return _pacing.pace(self)

    PREFETCH_CHUNK = 4 * 1024 * 1024

    def _prefetch(self, file_path: Path) -> None:
        """261009-14(응답성 SOT §4 ③·§12): 파일을 **파이썬 `read()` 로 한 번 훑어** OS 캐시에 올린다(내용은 버린다).

        PyMuPDF 는 C 호출 동안 GIL 을 놓지 않는다 — 디스크를 기다리는 동안에도(찬 파일·백신 검사). 그래서 색인이
        `fz_open_file`·`fz_load_outline` 에서 디스크를 기다리면 메인이 함께 섰다(설치본 빈 색인 1,124개에서 1.0~2.75초 9회).
        파이썬의 `read()` 는 기다리는 동안 GIL 을 놓으므로, 먼저 훑어 두면 뒤의 `fitz.open` 은 캐시에서 금방 읽는다."""
        try:
            with open(file_path, "rb", buffering=0) as f:
                while f.read(self.PREFETCH_CHUNK):
                    pass
        except OSError:
            pass

    def _study_for(self, file_path):
        """(study.db 읽기 연결, file_key) — study.db 는 색인과 같은 폴더(설정 폴더)에 있다. 없으면 (None, None).
        **저장한 것만**(main 표) 읽는다 — [저장] 전 OCR 은 보류 저장소에 있고 색인하지 않는다(단어학습 SOT §14.21)."""
        sp = self.db_path.parent / "study.db"
        if not sp.exists():
            return None, None
        try:
            if getattr(self, "_study_conn", None) is None:
                self._study_conn = _dbutil.connect(sp, self.busy_ms, readonly=True)
            from viewer.study.study_store import file_key_for
            return self._study_conn, file_key_for(file_path)
        except Exception:
            return None, None

    @staticmethod
    def _scan_text(page, text, study, fkey, i) -> str:
        """스캔 쪽이면 저장한 우리 OCR 글, 아니면 글자층 그대로. 글자가 충분하고 그림이 없으면 판정도 건너뛴다(값싸게)."""
        try:
            if len((text or "").strip()) >= 30 and not page.get_images():
                return text
            from viewer.study.ocr import decide_source
            if decide_source(page)[0] != "ocr":
                return text
            row = study.execute("SELECT text FROM ocr_page WHERE file_key=? AND page=?", (fkey, i)).fetchone()
            return (row[0] if row and row[0] else text)
        except Exception:
            return text

    def index_file(self, file_path: Path):
        """단일 PDF 인덱싱(또는 재인덱싱)."""
        self.remove_file(file_path)
        self._prefetch(file_path)
        try:
            doc = fitz.open(file_path)
        except Exception:
            return  # 손상된 파일은 건너뜀
        # 261011-5(마스터 §4.7.16): '저장' 이 넣은 'PolyPDF' 레이어(꾸밈 글상자 글)는 추출에서 뺀다 — 본문 화면처럼
        try:
            from viewer import pdf_mirror as _pm
            _pm.hide_for_view(doc)
        except Exception:
            pass
        try:
            # 260906-4: 어차피 연 김에 목록 조사 값(암호화·내부 책갈피)도 같이 기록한다 —
            #   책갈피창이 같은 파일을 다시 열지 않아도 되게(응답성 SOT §4).
            try:
                _enc = bool(doc.needs_pass)
                _toc = (False if _enc else bool(doc.get_toc()))
            except Exception:
                _enc, _toc = False, False
            # 260906-6(응답성 SOT §4 ⑤): 본문 읽기(느림)를 **쓰기 트랜잭션 밖**에서 한다.
            #   종전에는 파일 하나를 통째로 한 트랜잭션에 담아, 719쪽짜리 78MB PDF 하나가
            #   쓰기 잠금을 수십 초 쥐었다. 그 사이 UI 스레드의 조회는 그대로 대기한다.
            #   이제 쪽 묶음마다 짧게 끊어 적으므로 잠금을 쥐는 시간이 수십 ms 로 준다.
            _st = file_path.stat()
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO files(path, mtime, page_count, size) VALUES(?, ?, ?, ?)",
                    (str(file_path), _st.st_mtime, self.PAGES_PENDING, int(_st.st_size)),
                )
                file_id = cur.lastrowid
            rows = []

            def _flush():
                if not rows:
                    return
                with self.conn:
                    self.conn.executemany(
                        "INSERT INTO pages2(flat, text, file_id, page_index) VALUES(?, ?, ?, ?)",
                        rows)
                rows.clear()

            # 261019-4(검색창 SOT §3.2): 스캔 쪽은 **저장한 우리 OCR** 을 색인한다 — 텍스트 창과 같은 원천 규칙
            #   (쓸 만한 글자층 = 글자층, 스캔·스캐너 OCR 층만 있는 쪽 = 우리 OCR 이 있으면 그것)
            study, fkey = self._study_for(file_path)
            # 저장한 OCR 이 있는 쪽만 스캔 판정을 한다 — 판정(`decide_source`)은 글 추출·그림 점유율·숨은 글자층을
            #   다시 보는 무거운 일이라, 쪽마다 하면 첫 색인이 3~10배 느려졌다(빌드 시험 T5·T6 실측, 261019 점검)
            ocr_pages = set()
            if study is not None:
                try:
                    ocr_pages = {r[0] for r in study.execute(
                        "SELECT page FROM ocr_page WHERE file_key=?", (fkey,))}
                except Exception:
                    ocr_pages = set()
            for i in range(doc.page_count):
                try:
                    page = doc.load_page(i)
                    text = page.get_text("text")
                    if i in ocr_pages:
                        text = self._scan_text(page, text, study, fkey, i)
                except Exception:
                    text = ""
                # 260908-3(감사, 검색창 SOT §3 · 텍스트 창 SOT §5.3): 텍스트 창에서
                #   고친 글을 **색인에도** 넣는다. 안 그러면 화면·복사는 고쳐졌는데
                #   검색만 옛 글자로 남아, 찾은 것이 안 찾아지는 일이 생긴다.
                text = _apply_text_fixes(file_path, i, text)
                rows.append((flat_text(text), text, file_id, i))
                # 260906-5(응답성 SOT §4 ②): 쪽 묶음마다 GIL 양보 — 쪽이 많은 파일 하나가
                #   메인을 통째로 굶기지 않게. 비용은 파일당 수 ms.
                if (i & 0x1F) == 0x1F:
                    self._pace()
                if len(rows) >= self.WRITE_CHUNK:
                    _flush()
                    self._pace()
            _flush()
            # ★ 쪽을 다 적은 **뒤에야** 진짜 쪽수를 넣는다 — 중간에 끊기면 `page_count` 가
            #   `PAGES_PENDING` 으로 남아 `needs_reindex` 가 다시 읽게 한다(검색이 조용히
            #   비는 것을 막는 표식).
            with self.conn:
                self.conn.execute("UPDATE files SET page_count=? WHERE id=?",
                                  (doc.page_count, file_id))
            # 조사 캐시도 같이 채운다 — 목록이 이 파일을 다시 열지 않게(260906-4).
            try:
                from viewer.sign_core import probe_signed      # 261010-27(보안 SOT §4): 서명 표식도 같이
                self.probe_set(file_path, int(_st.st_size), _st.st_mtime,
                               _enc, (None if _enc else _toc), "locked" if _enc else None,
                               probe_signed(doc))
            except Exception:
                pass
        finally:
            doc.close()

    def index_folder(
        self,
        folder: Path,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """폴더 내 모든 PDF 인덱싱. progress(완료수, 전체수, 현재파일명).
        260611-89: should_cancel() 가 True 면 즉시 중단(다른 폴더/파일 열 때).

        260828: **영구 캐시** — 사라진 파일 정리를 '이 폴더 하위 경로'로 한정.
        (종전: DB 전체에서 현재 폴더에 없는 경로를 모두 삭제 → 다른 폴더로 전환할 때마다
        이전 폴더 인덱스가 통째로 사라져 재방문 시 전체 재인덱싱. 이제 폴더별 인덱스가
        보존되어, 이미 연 적 있는 폴더/파일은 변경분(mtime+size)만 재인덱싱.)"""
        if should_cancel and should_cancel():
            return
        # 260906-7(SOT §7.0·§5): `rglob` 대신 표준 `iter_pdfs` — **중간에 멈출 수 있다**.
        #   `rglob` 은 끝까지 돌아야 첫 결과가 나와, 파일이 많은 폴더에서는 취소 요청을
        #   받고도 계속 돌며 GIL 을 나눠 가진다(그동안 메인의 렌더가 몇 배로 느려진다).
        from viewer.pathutil import iter_pdfs
        pdfs = sorted(iter_pdfs(folder, should_cancel=should_cancel))
        if should_cancel and should_cancel():
            return
        # 사라진 파일 정리 — **이 폴더 하위**만 (다른 폴더 캐시는 보존)
        import os as _os
        from viewer.pathutil import norm_key          # 260628: 경로 키 표준(SOT §7.0)
        prefix = norm_key(folder)
        if not prefix.endswith(_os.sep):
            prefix += _os.sep
        existing_paths = {row["path"] for row in self.conn.execute("SELECT path FROM files")}
        # 260905: '살아 있는 파일' 비교도 **정규화 키**로 — 대소문자만 다른 경로로 열었을 때
        #   멀쩡한 행을 '사라진 파일'로 지우고 다시 읽던 결함(실측 재현).
        live_keys = {norm_key(p) for p in pdfs}
        for stale in existing_paths:
            if should_cancel and should_cancel():
                return
            k = norm_key(stale)
            if k not in live_keys and k.startswith(prefix):
                self.remove_file(Path(stale))

        total = len(pdfs)
        for idx, pdf in enumerate(pdfs, 1):
            self._pace()                      # 260906-5/260908-5(SOT §4 ②·⑦): 파일마다
            if should_cancel and should_cancel():
                return
            # 260905(§4.4): 시작도 알린다 — 완료 때만 알리면 첫 파일이 끝날 때까지 진행 창이
            #   총 개수도 파일명도 없이 '준비 중...' 만 띄워 멈춘 것처럼 보인다(사용자 보고).
            if progress:
                progress(idx - 1, total, pdf.name)
            if self.needs_reindex(pdf):
                self.index_file(pdf)
            if progress:
                progress(idx, total, pdf.name)

    # --- 검색 --------------------------------------------------------------

    def search(self, query: str, limit: int = 1000, paths: list | None = None, mode=None) -> list:
        """부분일치(substring) 검색. 페이지 단위 결과를 SearchResult 리스트로 반환.

        260616-3: FTS5 MATCH(토큰 단위)는 한글 합성어를 분리하지 못해
        '스크린'으로 '스크린망'·'핫스크린'을 찾지 못했다. 저장된 페이지 텍스트에
        대해 LIKE '%query%' 부분일치 스캔으로 변경하여 어느 위치에 포함되든 검색한다.
        """
        q = query.strip()
        if not q:
            return []
        if mode and any(mode):
            # 261014-18(검색창 SOT §4.1): 대소문자·정규식 — 색인 형식은 그대로, 후보를 추린 뒤 `Matcher` 로 거른다
            return self._search_matcher(q, limit, paths, mode)
        # 261019-4(검색창 SOT §4): **빈칸·줄바꿈을 무시**한다 — 새 표는 `flat` 으로, 옛 표(아직 옮기지 않은 파일)는 원문으로
        qf = flat_text(q)
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        escf = qf.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_f = f"%{escf}%"
        # 260825: trigram FTS — `p.text LIKE ?`(컬럼 직접, lower() 미사용)면 3자↑ 질의는
        #   트라이그램 색인을 사용해 빠름(대소문자 무시=토크나이저 기본). 함수로 감싸면 색인
        #   최적화가 깨지므로 lower() 를 쓰지 않는다(LIKE 자체가 대소문자 무시).
        # 260828: 영구(다중 폴더) 캐시에서 검색 범위를 SQL 로 한정 — LIMIT 이
        #   다른 폴더 결과로 채워지지 않게. paths=None 이면 전체.
        args: list = [like_f, like]
        scope_sql = ""
        if paths:
            # 260628: 표준 키(pathutil.norm_key)로 통일. ★ 아래 SQL 변환
            #   `lower(replace(f.path,'/','\'))` 과 **같은 문자열**을 만들어야 한다(SOT §7.0).
            from viewer.pathutil import norm_key
            keys = sorted({norm_key(p) for p in paths})
            scope_sql = (" AND lower(replace(f.path,'/','\\')) IN (%s)"
                         % ",".join("?" for _ in keys))
            args.extend(keys)
        args.append(limit)
        sql = f"""
            SELECT f.path AS path, x.page_index AS page_index, x.text AS text
            FROM (SELECT file_id, page_index, text FROM pages2 WHERE flat LIKE ? ESCAPE '\\'
                  UNION ALL
                  SELECT file_id, page_index, text FROM pages_fts WHERE text LIKE ? ESCAPE '\\') AS x
            JOIN files AS f ON f.id = x.file_id
            WHERE 1=1{scope_sql}
            ORDER BY f.path, x.page_index
            LIMIT ?
        """
        cur = self.conn.execute(sql, args)

        results: list = []
        pat = flat_pattern(q) or re.compile(re.escape(q), re.IGNORECASE)
        for row in cur:
            text = row["text"] or ""
            cnt = len(pat.findall(text)) or 1
            results.append(
                SearchResult(
                    file_path=row["path"],
                    file_name=Path(row["path"]).name,
                    page_index=row["page_index"],
                    match_count=cnt,
                    snippet=self._snippet_flat(text, pat),
                )
            )
        return results

    def _search_matcher(self, q: str, limit: int, paths, mode) -> list:
        """§4.1 — LIKE 힌트가 있으면 그것으로 후보를 추리고, 없으면 범위 안 쪽을 모두 훑어 `Matcher` 로 거른다."""
        from viewer.search_match import Matcher
        m = Matcher(q, case=mode[0], regex=mode[1])          # 틀린 정규식은 re.error 로 올린다(부르는 쪽이 알린다)
        hint = m.like_hint()
        args: list = []
        where = []
        w2, w1 = "", ""
        if hint:
            esc = hint.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            hf = flat_text(hint)
            escf = hf.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            w2, w1 = " WHERE flat LIKE ? ESCAPE '\\'", " WHERE text LIKE ? ESCAPE '\\'"
            args.extend([f"%{escf}%", f"%{esc}%"])
        if paths:
            from viewer.pathutil import norm_key
            keys = sorted({norm_key(p) for p in paths})
            where.append("lower(replace(f.path,'/','\\')) IN (%s)" % ",".join("?" for _ in keys))   # §7.0 키와 같은 문자열
            args.extend(keys)
        # 261019-4: 새 표(pages2)와 아직 옮기지 않은 옛 표를 함께 본다
        sql = ("SELECT f.path AS path, x.page_index AS page_index, x.text AS text FROM ("
               "SELECT file_id, page_index, text FROM pages2" + w2 + " UNION ALL "
               "SELECT file_id, page_index, text FROM pages_fts" + w1 + ") AS x JOIN files AS f ON f.id = x.file_id"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY f.path, x.page_index")
        results: list = []
        for row in self.conn.execute(sql, args):
            text = row["text"] or ""
            cnt = m.count(text)
            if not cnt:
                continue
            results.append(SearchResult(file_path=row["path"], file_name=Path(row["path"]).name,
                                        page_index=row["page_index"], match_count=cnt,
                                        snippet=self._snippet_by(text, m)))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _snippet_by(text: str, m, ctx: int = 16) -> str:
        """§4.1 — `Matcher` 의 첫 일치 둘레 ±ctx 글자, 일치를 `<...>` 로(`_make_snippet` 과 같은 모양)."""
        flat = re.sub(r"\s+", " ", text).strip()
        sp = m.first(flat)
        if sp is None:
            return flat[:40]
        i, j = sp
        start, end = max(0, i - ctx), min(len(flat), j + ctx)
        return (("..." if start > 0 else "") + flat[start:i] + "<" + flat[i:j] + ">"
                + flat[j:end] + ("..." if end < len(flat) else ""))

    @staticmethod
    def _snippet_flat(text: str, pat, ctx: int = 16) -> str:
        """261019-4: 빈칸 무시 일치의 미리보기 — 줄바꿈을 빈칸 하나로 바꾼 글에서 같은 정규식으로 찾는다."""
        flat = re.sub(r"\s+", " ", text).strip()
        m = pat.search(flat)
        if not m:
            return flat[:40]
        i, j = m.span()
        start, end = max(0, i - ctx), min(len(flat), j + ctx)
        return (("..." if start > 0 else "") + flat[start:i] + "<" + flat[i:j] + ">"
                + flat[j:end] + ("..." if end < len(flat) else ""))

    @staticmethod
    def _make_snippet(text: str, q: str, ctx: int = 16) -> str:
        """첫 매치 주변 ±ctx 글자로 스니펫 구성. 매치를 <...> 로 감싼다
        (SearchResults 가 < > → [ ] 로 치환해 표시)."""
        flat = re.sub(r"\s+", " ", text).strip()
        low = flat.lower()
        i = low.find(q.lower())
        if i < 0:
            return flat[:40]
        start = max(0, i - ctx)
        end = min(len(flat), i + len(q) + ctx)
        pre = ("..." if start > 0 else "") + flat[start:i]
        mid = flat[i:i + len(q)]
        post = flat[i + len(q):end] + ("..." if end < len(flat) else "")
        return f"{pre}<{mid}>{post}"

    def _page_text(self, path: str, page_index: int) -> str:
        cur = self.conn.execute(
            """
            SELECT x.text FROM (SELECT file_id, page_index, text FROM pages2
                                UNION ALL SELECT file_id, page_index, text FROM pages_fts) AS x
            JOIN files AS f ON f.id = x.file_id
            WHERE f.path = ? AND x.page_index = ?
            """,
            (path, page_index),
        )
        row = cur.fetchone()
        return row["text"] if row else ""

    # --- 정리 --------------------------------------------------------------

    def page_texts(self, file_path: str | Path) -> list:
        """260829(태그 SOT §4.1): 읽기 전용 헬퍼 — 색인된 페이지 텍스트(페이지 순).
        태그·키워드 자동 생성(auto_tag)이 본문 재파싱 없이 쓰는 입구. 미색인이면 [].
        스키마·prune 규칙 소유는 검색 SOT(§13) — 여기서는 조회만 한다."""
        try:
            row = self._find_file_row(file_path, "id")   # 260905: 철자가 달라도 찾는다
            if not row:
                return []
            cur = self.conn.execute(
                "SELECT text, page_index FROM pages2 WHERE file_id=? UNION ALL "
                "SELECT text, page_index FROM pages_fts WHERE file_id=? ORDER BY 2",
                (row["id"], row["id"]))
            return [r[0] or "" for r in cur]
        except Exception:
            return []

    def is_empty(self) -> bool:
        """색인에 글이 하나도 없는가. 261016-8(응답성 SOT §4, 설치 시험 T1 6.86초 정지): `count(*)` 는 FTS 색인 **전체를** 읽는다 —
        파일 2천여 개 색인을 설치 직후(디스크·백신 캐시가 차가울 때) 메인 스레드에서 세다 창이 6.9초 섰다. 비었는지는 한 행으로 안다."""
        return (self.conn.execute("SELECT 1 FROM pages2 LIMIT 1").fetchone() is None
                and self.conn.execute("SELECT 1 FROM pages_fts LIMIT 1").fetchone() is None)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            if getattr(self, "_study_conn", None) is not None:
                self._study_conn.close()
        except Exception:
            pass
