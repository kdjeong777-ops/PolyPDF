# -*- coding: utf-8 -*-
"""사진 정보 색인 (사진 보기 SOT 4.24, 결정 D19, 261104-4).

사진 모드의 색인 — PDF 색인(`index.db`, 검색창 SOT)과 **따로 된** `photo_index.db`(사용자 데이터 폴더, SQLite FTS5).
PDF 색인의 스키마·G2(PDF 만)는 그대로 둔다.

- 행: 사진마다 경로·폴더·이름·확장자·크기·수정 시각·보이는 크기·촬영일·카메라·태그. 머리만 읽는다(`photo_io.photo_info`).
  zip 안 사진은 `zip`(zip 경로)·`member`(안 이름)를 함께 두고 경로 칸은 `<zip 경로>|<안 이름>`.
- 글(FTS): 이름·촬영일(YYYY-MM-DD)·카메라·태그. OCR 글자는 D15 그대로(확정한 사진만 — 여기에는 넣지 않는다).
- 다시 훑기는 **바뀐 것만**(크기·수정 시각) — 폴더에서 사라진 사진의 행은 지운다.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DB_NAME = "photo_index.db"
SCHEMA = 1
_LOCK = threading.Lock()


def db_path() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / DB_NAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    from viewer import dbutil
    p = Path(path) if path else db_path()
    con = dbutil.connect(p, row_factory=False)         # 표준 연결(대기 상한·WAL — 응답성 SOT §4 ⑤)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS photos(
            key TEXT PRIMARY KEY, path TEXT NOT NULL, folder TEXT NOT NULL, name TEXT NOT NULL, ext TEXT,
            size INTEGER, mtime_ns INTEGER, width INTEGER, height INTEGER,
            taken TEXT, camera TEXT, tags TEXT, zip TEXT, member TEXT);
        CREATE INDEX IF NOT EXISTS photos_folder ON photos(folder);
        CREATE VIRTUAL TABLE IF NOT EXISTS photo_fts USING fts5(key UNINDEXED, body, tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)
    con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('schema', ?)", (str(SCHEMA),))
    return con


def norm_folder(folder) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def _taken_text(taken: str) -> str:
    t = (taken or "").strip()
    if len(t) >= 10 and t[4] == ":" and t[7] == ":":
        return t[:4] + "-" + t[5:7] + "-" + t[8:10]
    return t[:10]


def upsert(con, key: str, path: str, folder: str, name: str, ext: str, size: int, mtime_ns: int, info: dict,
           tags: list, zip_path: str | None = None, member: str | None = None) -> None:
    """`key` 는 비교용(소문자 경로), `path` 는 원래 글자 그대로의 경로(열 때 쓴다)."""
    taken = _taken_text(info.get("taken", ""))
    camera = info.get("camera", "") or ""
    tag_txt = " ".join("#" + t for t in tags or [])
    con.execute("INSERT OR REPLACE INTO photos(key, path, folder, name, ext, size, mtime_ns, width, height, taken, camera, tags, zip, member) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, path, folder, name, ext, int(size), int(mtime_ns), int(info.get("width") or 0), int(info.get("height") or 0),
                 taken, camera, tag_txt, zip_path, member))
    con.execute("DELETE FROM photo_fts WHERE key=?", (key,))
    con.execute("INSERT INTO photo_fts(key, body) VALUES(?, ?)",
                (key, " ".join(x for x in (Path(name).stem, taken, camera, tag_txt) if x)))


def known(con, folder: str) -> dict:
    """폴더(하위 포함) 아래 행 — key → (크기, 수정 시각)."""
    like = folder.rstrip("\\/") + os.sep + "%"
    rows = con.execute("SELECT key, size, mtime_ns FROM photos WHERE folder=? OR folder LIKE ?", (folder, like)).fetchall()
    return {k: (s, m) for k, s, m in rows}


def remove(con, keys) -> None:
    for k in keys:
        con.execute("DELETE FROM photos WHERE key=?", (k,))
        con.execute("DELETE FROM photo_fts WHERE key=?", (k,))


def search(query: str, folder=None, limit: int = 500, path: Path | None = None) -> list:
    """사진 모드 검색 — 이름·촬영일·카메라·태그. 낱말마다 앞부분 일치(AND). 결과: dict(key, path, name, folder, taken, camera, width, height, zip, member)."""
    words = [w for w in (query or "").replace('"', " ").split() if w]
    if not words:
        return []
    fts = " ".join('"%s"*' % w.lstrip("#") for w in words)
    con = connect(path)
    try:
        sql = ("SELECT p.key, p.path, p.name, p.folder, p.taken, p.camera, p.width, p.height, p.zip, p.member "
               "FROM photo_fts f JOIN photos p ON p.key=f.key WHERE photo_fts MATCH ?")
        args = [fts]
        if folder:
            nf = norm_folder(folder)
            sql += " AND (p.folder=? OR p.folder LIKE ?)"
            args += [nf, nf.rstrip("\\/") + os.sep + "%"]
        sql += " ORDER BY p.taken DESC, p.name LIMIT ?"
        args.append(int(limit))
        try:
            rows = con.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
        keys = ("key", "path", "name", "folder", "taken", "camera", "width", "height", "zip", "member")
        return [dict(zip(keys, r)) for r in rows]
    finally:
        con.close()
