"""SQLite FTS5 기반 PDF 텍스트 인덱서.

증분 인덱싱: 파일 mtime 이 DB 의 기록과 다르면 재인덱싱.
"""
from __future__ import annotations

import os
import time
import re
import sqlite3

from viewer import dbutil as _dbutil
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

    def __init__(self, db_path: str | Path, busy_ms: int = BUSY_MS_BG):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrated = False
        self.busy_ms = int(busy_ms)
        try:
            self.conn = _dbutil.connect(self.db_path, self.busy_ms)
            self._init_schema()
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
            self._recreate_corrupt_db()

    _is_corrupt_error = staticmethod(_dbutil.is_corrupt_error)

    def _recreate_corrupt_db(self):
        try:
            self.conn.close()
        except Exception:
            pass
        import os as _os
        for suf in ("", "-wal", "-shm", "-journal"):
            try:
                _os.remove(str(self.db_path) + suf)
            except OSError:
                pass
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
    SCHEMA_VERSION = 3
    YIELD_S = 0.005          # 260906-5: 배경 작업의 GIL 양보 간격(응답성 SOT §4 ②)
    WRITE_CHUNK = 128        # 260906-6: 쓰기 트랜잭션 한 번에 담는 쪽 수(잠금 시간 상한)
    PAGES_PENDING = -1       # 260906-6: '본문을 아직 다 적지 못했다' 표식
    _FTS_TRIGRAM = ("CREATE VIRTUAL TABLE {name} USING fts5("
                    "text, file_id UNINDEXED, page_index UNINDEXED, tokenize='trigram')")

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
                auth TEXT
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

        # 일관성: 색인이 비었는데 files 기록만 남아있으면(구 파괴적 마이그레이션 잔재 등)
        #   needs_reindex 가 계속 False → 검색 0 이던 상태 → files 비워 재인덱싱 유도.
        if uv < self.SCHEMA_VERSION:
            try:
                fts_n = self.conn.execute("SELECT count(*) FROM pages_fts").fetchone()[0]
                files_n = self.conn.execute("SELECT count(*) FROM files").fetchone()[0]
                if fts_n == 0 and files_n > 0:
                    self.conn.execute("DELETE FROM files")
                    self.migrated = True
            except Exception:
                pass
            self.conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        self.conn.commit()

    # --- 인덱싱 ------------------------------------------------------------

    # --- 260906-4: 목록 조사(표식) 캐시 -------------------------------------
    def probe_get(self, file_path, size: int, mtime: float):
        """저장해 둔 (암호화, 책갈피유무, 인증상태). 모르거나 파일이 바뀌었으면 None.

        `size`/`mtime` 는 **호출측이 지금 디스크에서 본 값** — 기록과 다르면 내용이
        바뀐 것이므로 쓰지 않는다(재인덱싱 판정과 같은 기준)."""
        from viewer.pathutil import norm_key
        row = self.conn.execute(
            "SELECT size, mtime, encrypted, has_toc, auth FROM probe_cache WHERE key=?",
            (norm_key(file_path),)).fetchone()
        if row is None:
            return None
        try:
            if int(row["size"]) != int(size) or abs(float(row["mtime"]) - float(mtime)) > 1:
                return None
        except Exception:
            return None
        has_toc = None if row["has_toc"] is None else bool(row["has_toc"])
        return (bool(row["encrypted"]), has_toc, row["auth"])

    def probe_set(self, file_path, size: int, mtime: float,
                  enc: bool, has_toc, auth) -> None:
        """조사 결과 기록(같은 파일은 덮어쓴다). 인덱싱 여부와 무관하게 남는다."""
        from viewer.pathutil import norm_key
        self.conn.execute(
            "INSERT OR REPLACE INTO probe_cache(key, size, mtime, encrypted, has_toc, auth)"
            " VALUES(?, ?, ?, ?, ?, ?)",
            (norm_key(file_path), int(size), float(mtime), 1 if enc else 0,
             None if has_toc is None else (1 if has_toc else 0), auth))
        self.conn.commit()

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
            self.conn.execute("DELETE FROM files WHERE id = ?", (fid,))
            self.conn.commit()

    def index_file(self, file_path: Path):
        """단일 PDF 인덱싱(또는 재인덱싱)."""
        self.remove_file(file_path)
        try:
            doc = fitz.open(file_path)
        except Exception:
            return  # 손상된 파일은 건너뜀
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
                        "INSERT INTO pages_fts(text, file_id, page_index) VALUES(?, ?, ?)",
                        rows)
                rows.clear()

            for i in range(doc.page_count):
                try:
                    text = doc.load_page(i).get_text("text")
                except Exception:
                    text = ""
                # 260908-3(감사, 검색창 SOT §3 · 텍스트 창 SOT §5.3): 텍스트 창에서
                #   고친 글을 **색인에도** 넣는다. 안 그러면 화면·복사는 고쳐졌는데
                #   검색만 옛 글자로 남아, 찾은 것이 안 찾아지는 일이 생긴다.
                text = _apply_text_fixes(file_path, i, text)
                rows.append((text, file_id, i))
                # 260906-5(응답성 SOT §4 ②): 쪽 묶음마다 GIL 양보 — 쪽이 많은 파일 하나가
                #   메인을 통째로 굶기지 않게. 비용은 파일당 수 ms.
                if (i & 0x1F) == 0x1F:
                    time.sleep(self.YIELD_S)
                if len(rows) >= self.WRITE_CHUNK:
                    _flush()
                    time.sleep(self.YIELD_S)
            _flush()
            # ★ 쪽을 다 적은 **뒤에야** 진짜 쪽수를 넣는다 — 중간에 끊기면 `page_count` 가
            #   `PAGES_PENDING` 으로 남아 `needs_reindex` 가 다시 읽게 한다(검색이 조용히
            #   비는 것을 막는 표식).
            with self.conn:
                self.conn.execute("UPDATE files SET page_count=? WHERE id=?",
                                  (doc.page_count, file_id))
            # 조사 캐시도 같이 채운다 — 목록이 이 파일을 다시 열지 않게(260906-4).
            try:
                self.probe_set(file_path, int(_st.st_size), _st.st_mtime,
                               _enc, (None if _enc else _toc), "locked" if _enc else None)
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
            time.sleep(self.YIELD_S)          # 260906-5(응답성 SOT §4 ②): 파일마다 GIL 양보
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

    def search(self, query: str, limit: int = 1000, paths: list | None = None) -> list:
        """부분일치(substring) 검색. 페이지 단위 결과를 SearchResult 리스트로 반환.

        260616-3: FTS5 MATCH(토큰 단위)는 한글 합성어를 분리하지 못해
        '스크린'으로 '스크린망'·'핫스크린'을 찾지 못했다. 저장된 페이지 텍스트에
        대해 LIKE '%query%' 부분일치 스캔으로 변경하여 어느 위치에 포함되든 검색한다.
        """
        q = query.strip()
        if not q:
            return []
        # LIKE 와일드카드(%, _, \) 이스케이프 후 부분일치 패턴 구성
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        # 260825: trigram FTS — `p.text LIKE ?`(컬럼 직접, lower() 미사용)면 3자↑ 질의는
        #   트라이그램 색인을 사용해 빠름(대소문자 무시=토크나이저 기본). 함수로 감싸면 색인
        #   최적화가 깨지므로 lower() 를 쓰지 않는다(LIKE 자체가 대소문자 무시).
        # 260828: 영구(다중 폴더) 캐시에서 검색 범위를 SQL 로 한정 — LIMIT 이
        #   다른 폴더 결과로 채워지지 않게. paths=None 이면 전체.
        args: list = [like]
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
            SELECT f.path AS path, p.page_index AS page_index, p.text AS text
            FROM pages_fts AS p
            JOIN files AS f ON f.id = p.file_id
            WHERE p.text LIKE ? ESCAPE '\\'{scope_sql}
            ORDER BY f.path, p.page_index
            LIMIT ?
        """
        cur = self.conn.execute(sql, args)

        results: list = []
        pat = re.compile(re.escape(q), re.IGNORECASE)
        for row in cur:
            text = row["text"] or ""
            cnt = len(pat.findall(text)) or 1
            results.append(
                SearchResult(
                    file_path=row["path"],
                    file_name=Path(row["path"]).name,
                    page_index=row["page_index"],
                    match_count=cnt,
                    snippet=self._make_snippet(text, q),
                )
            )
        return results

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
            SELECT p.text FROM pages_fts AS p
            JOIN files AS f ON f.id = p.file_id
            WHERE f.path = ? AND p.page_index = ?
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
                "SELECT text FROM pages_fts WHERE file_id=? ORDER BY page_index",
                (row["id"],))
            return [r[0] or "" for r in cur]
        except Exception:
            return []

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
