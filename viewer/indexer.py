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
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # --- 스키마 ------------------------------------------------------------

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS files(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                mtime REAL NOT NULL,
                page_count INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                text,
                file_id UNINDEXED,
                page_index UNINDEXED,
                tokenize='unicode61 remove_diacritics 0'
            );
            """
        )
        # 260618-3: 파일 용량(size) 컬럼 추가 — 수정날짜+용량 변화 없으면 재인덱싱 생략.
        #   기존 DB(컬럼 없음)는 한 번에 추가하되, 기존 행 size=NULL 은 'mtime 만으로 판단'
        #   하여 업그레이드 시 전체 재인덱싱(시간 낭비)이 일어나지 않도록 한다.
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "size" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN size INTEGER")
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
        260611-89: should_cancel() 가 True 면 즉시 중단(다른 폴더/파일 열 때)."""
        if should_cancel and should_cancel():
            return
        pdfs = sorted(folder.rglob("*.pdf"))
        # 사라진 파일 정리
        existing_paths = {row["path"] for row in self.conn.execute("SELECT path FROM files")}
        live_paths = {str(p) for p in pdfs}
        for stale in existing_paths - live_paths:
            if should_cancel and should_cancel():
                return
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

    def search(self, query: str, limit: int = 1000) -> list:
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
        sql = """
            SELECT f.path AS path, p.page_index AS page_index, p.text AS text
            FROM pages_fts AS p
            JOIN files AS f ON f.id = p.file_id
            WHERE lower(p.text) LIKE lower(?) ESCAPE '\\'
            ORDER BY f.path, p.page_index
            LIMIT ?
        """
        cur = self.conn.execute(sql, (like, limit))

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
