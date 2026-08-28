"""SQLite FTS5 기반 PDF 텍스트 인덱서.

증분 인덱싱: 파일 mtime 이 DB 의 기록과 다르면 재인덱싱.
"""
from __future__ import annotations

import os
import re
import sqlite3
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


class PdfIndex:
    """PDF 폴더에 대한 FTS5 인덱스를 관리.

    스키마:
        files(id INTEGER PK, path TEXT UNIQUE, mtime REAL, page_count INTEGER)
        pages(file_id INTEGER, page_index INTEGER, text TEXT)
        pages_fts(text, file_id UNINDEXED, page_index UNINDEXED) - FTS5 가상 테이블
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrated = False
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
        except sqlite3.DatabaseError:
            # 260827: index.db 손상(malformed) → 파일 삭제 후 새로 생성(캐시라 안전).
            #   다음 인덱싱이 다시 채운다. PdfIndex 생성이 실패해 검색/인덱싱이 통째로
            #   깨지던 문제 방지.
            self._recreate_corrupt_db()

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
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self.migrated = True

    # --- 스키마 ------------------------------------------------------------

    # 260825: FTS 토크나이저 스키마 버전. 2=trigram(파괴적, 폐기), 3=trigram(내용 보존 복사).
    SCHEMA_VERSION = 3
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

    def needs_reindex(self, file_path: Path) -> bool:
        """260618-3: 기록된 수정날짜(mtime)+용량(size) 모두 변화 없으면 재인덱싱 생략.
        size 가 NULL(구버전 DB 기록)인 경우는 mtime 만으로 판단(업그레이드 시 불필요한
        전체 재인덱싱 방지)."""
        cur = self.conn.execute(
            "SELECT mtime, size FROM files WHERE path = ?", (str(file_path),)
        )
        row = cur.fetchone()
        if row is None:
            return True
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
        cur = self.conn.execute("SELECT id FROM files WHERE path = ?", (str(file_path),))
        row = cur.fetchone()
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
            with self.conn:
                _st = file_path.stat()
                cur = self.conn.execute(
                    "INSERT INTO files(path, mtime, page_count, size) VALUES(?, ?, ?, ?)",
                    (str(file_path), _st.st_mtime, doc.page_count, int(_st.st_size)),
                )
                file_id = cur.lastrowid
                rows = []
                for i in range(doc.page_count):
                    try:
                        text = doc.load_page(i).get_text("text")
                    except Exception:
                        text = ""
                    rows.append((text, file_id, i))
                self.conn.executemany(
                    "INSERT INTO pages_fts(text, file_id, page_index) VALUES(?, ?, ?)",
                    rows,
                )
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
        pdfs = sorted(folder.rglob("*.pdf"))
        # 사라진 파일 정리 — **이 폴더 하위**만 (다른 폴더 캐시는 보존)
        import os as _os
        from viewer.pathutil import norm_key          # 260628: 경로 키 표준(SOT §7.0)
        prefix = norm_key(folder)
        if not prefix.endswith(_os.sep):
            prefix += _os.sep
        existing_paths = {row["path"] for row in self.conn.execute("SELECT path FROM files")}
        live_paths = {str(p) for p in pdfs}
        for stale in existing_paths - live_paths:
            if should_cancel and should_cancel():
                return
            if norm_key(stale).startswith(prefix):
                self.remove_file(Path(stale))

        total = len(pdfs)
        for idx, pdf in enumerate(pdfs, 1):
            if should_cancel and should_cancel():
                return
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

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
