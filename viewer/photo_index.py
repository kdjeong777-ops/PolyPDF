# -*- coding: utf-8 -*-
"""사진 정보 색인 (사진 보기 SOT 4.24, 결정 D19, 261104-4).

사진 모드의 색인 — PDF 색인(`index.db`, 검색창 SOT)과 **따로 된** `photo_index.db`(사용자 데이터 폴더, SQLite FTS5).
PDF 색인의 스키마·G2(PDF 만)는 그대로 둔다.

- 행: 사진마다 경로·폴더·이름·확장자·크기·수정 시각·보이는 크기·촬영일·카메라·태그. 머리만 읽는다(`photo_io.photo_info`).
  zip 안 사진은 `zip`(zip 경로)·`member`(안 이름)를 함께 두고 경로 칸은 `<zip 경로>|<안 이름>`.
- 글(FTS): 이름·촬영일(YYYY-MM-DD)·카메라·태그 + 확정한 OCR 글(`ocr` 칸 — 사진 보기 SOT §4.36, D15).
- 다시 훑기는 **바뀐 것만**(크기·수정 시각) — 폴더에서 사라진 사진의 행은 지운다.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DB_NAME = "photo_index.db"
SCHEMA = 3                       # 2: `ocr` 칸(261104-10 P4-c) · 3: `at_ver`·`kind` 칸(자동 태그 판정 표시, 태그 SOT §5.7, 261105-6)
_LOCK = threading.Lock()


def db_path() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / DB_NAME


def connect(path: Path | None = None, busy_ms: int | None = None) -> sqlite3.Connection:
    """표준 연결(대기 상한·WAL — 응답성 SOT §4 ⑤). 메인 스레드는 `dbutil.BUSY_MS_UI`, 워커는 기본(`BUSY_MS_BG`).
    손상됐으면 지우고 새로 만든다 — 이 DB 는 캐시다(마스터 §8.3.1, `index.db` 와 같은 규칙)."""
    from viewer import dbutil
    p = Path(path) if path else db_path()
    try:
        return _open(p, busy_ms)
    except sqlite3.DatabaseError as e:
        if not dbutil.is_corrupt_error(e):
            raise
        for suf in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(str(p) + suf)
            except OSError:
                pass
        return _open(p, busy_ms)


def connect_read(path: Path | None = None, busy_ms: int | None = None) -> sqlite3.Connection:
    """읽기만 하는 연결 — 스키마 맞추기(`_init` 의 쓰기)를 하지 않는다. 색인 훑기가 쓰기 트랜잭션을 쥐고 있어도 기다리지 않는다(WAL).
    `connect` 는 열 때마다 meta 행을 써서, 읽기만 하는 날짜 작업·검색이 색인 훑기 뒤에 대기 상한까지 섰다(261105-10).
    파일이 없으면 `sqlite3.OperationalError`."""
    from viewer import dbutil
    p = Path(path) if path else db_path()
    return dbutil.connect(p, busy_ms=busy_ms or dbutil.BUSY_MS_BG, row_factory=False, readonly=True)


def _open(p: Path, busy_ms: int | None) -> sqlite3.Connection:
    from viewer import dbutil
    con = dbutil.connect(p, busy_ms=busy_ms or dbutil.BUSY_MS_BG, row_factory=False)
    try:
        _init(con)
    except Exception:
        con.close()                      # 실패한 연결을 놓아야 손상 파일을 지울 수 있다(Windows)
        raise
    return con


def _init(con) -> None:
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
    cols = {r[1] for r in con.execute("PRAGMA table_info(photos)")}
    if "ocr" not in cols:
        con.execute("ALTER TABLE photos ADD COLUMN ocr TEXT")
    if "at_ver" not in cols:                 # 사진 머리 자동 태그(meta)를 만든 규칙 판 — 다르면 다시(태그 SOT §5.7)
        con.execute("ALTER TABLE photos ADD COLUMN at_ver INTEGER")
    if "kind" not in cols:                   # 종류 판정 '판:태그'('1:영수증'·'1:') — NULL 이면 아직(태그 SOT §5.7)
        con.execute("ALTER TABLE photos ADD COLUMN kind TEXT")
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    if not row or row[0] != str(SCHEMA):             # 같으면 쓰지 않는다 — 열 때마다 쓰면 그 연결이 쓰기 잠금을 쥔 채 남는다(261105-10)
        con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('schema', ?)", (str(SCHEMA),))
        con.commit()


def norm_folder(folder) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def _taken_text(taken: str) -> str:
    t = (taken or "").strip()
    if len(t) >= 10 and t[4] == ":" and t[7] == ":":
        return t[:4] + "-" + t[5:7] + "-" + t[8:10]
    return t[:10]


def _body(name, taken, camera, tag_txt, ocr) -> str:
    return " ".join(x for x in (Path(name).stem, taken, camera, tag_txt, ocr) if x)


def upsert(con, key: str, path: str, folder: str, name: str, ext: str, size: int, mtime_ns: int, info: dict,
           tags: list, zip_path: str | None = None, member: str | None = None, ocr: str = "", at_ver=None) -> None:
    """`key` 는 비교용(소문자 경로), `path` 는 원래 글자 그대로의 경로(열 때 쓴다). `ocr` 은 **확정한** 글만(§4.36).
    `at_ver` = 이 행의 머리 자동 태그를 만든 규칙 판(태그 SOT §5.7). 행을 새로 쓰면 종류 판정(`kind`)은 비운다 — 사진이 바뀌었다."""
    taken = _taken_text(info.get("taken", ""))
    camera = info.get("camera", "") or ""
    tag_txt = " ".join("#" + t for t in tags or [])
    con.execute("INSERT OR REPLACE INTO photos(key, path, folder, name, ext, size, mtime_ns, width, height, taken, camera, tags, zip, member, ocr, at_ver) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, path, folder, name, ext, int(size), int(mtime_ns), int(info.get("width") or 0), int(info.get("height") or 0),
                 taken, camera, tag_txt, zip_path, member, ocr or "", at_ver))
    con.execute("DELETE FROM photo_fts WHERE key=?", (key,))
    con.execute("INSERT INTO photo_fts(key, body) VALUES(?, ?)", (key, _body(name, taken, camera, tag_txt, ocr)))


def set_ocr(con, path: str, ocr: str, tags=None) -> bool:
    """OCR 을 확정한 사진 — 그 행의 `ocr`(·태그) 칸과 검색 글을 바꾼다. 행이 없으면 False(다음 색인 훑기가 넣는다, §4.36)."""
    key = os.path.normcase(os.path.abspath(str(path)))
    row = con.execute("SELECT name, taken, camera, tags FROM photos WHERE key=?", (key,)).fetchone()
    if not row:
        return False
    name, taken, camera, tag_txt = row
    if tags is not None:
        tag_txt = " ".join("#" + t for t in tags)
    con.execute("UPDATE photos SET ocr=?, tags=? WHERE key=?", (ocr or "", tag_txt, key))
    con.execute("DELETE FROM photo_fts WHERE key=?", (key,))
    con.execute("INSERT INTO photo_fts(key, body) VALUES(?, ?)", (key, _body(name, taken, camera, tag_txt, ocr)))
    return True


def set_tags(con, key: str, tags, at_ver=None, kind=None) -> bool:
    """자동 태그를 정한 뒤(태그 SOT §5.7) — 그 행의 태그 글·검색 글을 바꾸고, 주면 `at_ver`·`kind` 도. 워커에서. 행이 없으면 False."""
    row = con.execute("SELECT name, taken, camera, ocr FROM photos WHERE key=?", (key,)).fetchone()
    if not row:
        return False
    name, taken, camera, ocr = row
    tag_txt = " ".join("#" + t for t in tags or [])
    con.execute("UPDATE photos SET tags=?, at_ver=COALESCE(?, at_ver), kind=COALESCE(?, kind) WHERE key=?",
                (tag_txt, at_ver, kind, key))
    con.execute("DELETE FROM photo_fts WHERE key=?", (key,))
    con.execute("INSERT INTO photo_fts(key, body) VALUES(?, ?)", (key, _body(name, taken, camera, tag_txt, ocr)))
    return True


def autotag_todo(con, folder: str, ver: int) -> set:
    """폴더(하위 포함)에서 머리 자동 태그가 아직이거나 옛 판인 사진 행의 key — zip 안 사진은 빼고(파일 태그가 없다)."""
    like = folder.rstrip("\\/") + os.sep + "%"
    rows = con.execute("SELECT key FROM photos WHERE (folder=? OR folder LIKE ?) AND zip IS NULL AND (at_ver IS NULL OR at_ver<>?)",
                       (folder, like, int(ver))).fetchall()
    return {r[0] for r in rows}


def kind_todo(con, folder: str, ver: int) -> list:
    """종류 판정이 아직이거나 옛 판인 사진 — [(key, path)]. zip 안 사진·스크린샷은 뺀다(태그 SOT §5.7)."""
    like = folder.rstrip("\\/") + os.sep + "%"
    rows = con.execute("SELECT key, path, kind, tags FROM photos WHERE (folder=? OR folder LIKE ?) AND zip IS NULL ORDER BY taken DESC, name",
                       (folder, like)).fetchall()
    pre = "%d:" % int(ver)
    return [(k, p) for k, p, kd, tg in rows if not (kd or "").startswith(pre) and "#스크린샷" not in (tg or "")]


def known(con, folder: str) -> dict:
    """폴더(하위 포함) 아래 행 — key → (크기, 수정 시각)."""
    like = folder.rstrip("\\/") + os.sep + "%"
    rows = con.execute("SELECT key, size, mtime_ns FROM photos WHERE folder=? OR folder LIKE ?", (folder, like)).fetchall()
    return {k: (s, m) for k, s, m in rows}


def relocate(con, old: str, new: str, copy: bool = False) -> bool:
    """사진을 옮기거나 복사한 뒤(사진 보기 SOT §4.41) — 그 행을 새 경로로(복사면 새 행을 하나 더). OCR 확정 글·태그 글이 그대로 남는다.
    옛 행이 없으면 False(다음 색인 훑기가 넣는다)."""
    ko = os.path.normcase(os.path.abspath(str(old)))
    kn = os.path.normcase(os.path.abspath(str(new)))
    row = con.execute("SELECT name, taken, camera, tags, ocr FROM photos WHERE key=?", (ko,)).fetchone()
    if not row or ko == kn:
        return False
    p = Path(str(new))
    folder, name, ext = norm_folder(p.parent), p.name, p.suffix.lower()
    if copy:
        con.execute("INSERT OR REPLACE INTO photos(key, path, folder, name, ext, size, mtime_ns, width, height, taken, camera, tags, zip, member, ocr) "
                    "SELECT ?, ?, ?, ?, ?, size, mtime_ns, width, height, taken, camera, tags, zip, member, ocr FROM photos WHERE key=?",
                    (kn, str(p), folder, name, ext, ko))
    else:
        con.execute("DELETE FROM photos WHERE key=?", (kn,))
        con.execute("UPDATE photos SET key=?, path=?, folder=?, name=?, ext=? WHERE key=?", (kn, str(p), folder, name, ext, ko))
        con.execute("DELETE FROM photo_fts WHERE key=?", (ko,))
    _n, taken, camera, tag_txt, ocr = row
    con.execute("DELETE FROM photo_fts WHERE key=?", (kn,))
    con.execute("INSERT INTO photo_fts(key, body) VALUES(?, ?)", (kn, _body(name, taken, camera, tag_txt, ocr)))
    return True


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
    from viewer import dbutil
    try:
        con = connect_read(path, busy_ms=dbutil.BUSY_MS_UI)   # 메인에서 부른다 — 읽기만, 오래 기다리지 않는다(못 읽으면 빈 결과)
    except sqlite3.Error:
        return []
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
