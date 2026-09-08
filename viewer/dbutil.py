# -*- coding: utf-8 -*-
"""260906-9: SQLite 연결의 **단일 표준** (응답성 SOT §4 ⑤ '어느 DB든').

배경(감사 260906-9): `index.db` 만 WAL 로 바꿔 두고 `dict.db`(21MB)·`study.db`(61MB)·
`user_study.db` 는 **SQLite 기본인 롤백 저널 모드 그대로**였다. 그 모드는 쓰는 쪽이 읽는
쪽을 막고, 파이썬 `sqlite3` 의 기본 대기 상한 **5.0초는 Windows 가 창을 '응답 없음' 으로
칠하는 시간과 같다**. 즉 `index.db` 에서 네 번 겪은 것과 **똑같은 사고**가 단어장·OCR
쪽에 그대로 남아 있었다(단어장 만들기 워커가 study.db 를 적는 동안 UI 가 읽으면 정지).

규칙 (응답성 SOT §4 ⑤)
  - **연결은 이 모듈로만 연다.** `sqlite3.connect` 를 직접 부르지 않는다.
  - **WAL** — 읽는 쪽이 쓰는 쪽을 기다리지 않는다. 저널 모드는 DB 파일에 새겨져 유지되고,
    못 바꾸는 위치(네트워크 드라이브 등)에서는 조용히 종전 모드로 남는다(동작 동일).
  - **대기 상한은 부르는 쪽이 정한다.** UI 스레드는 `BUSY_MS_UI`, 워커는 `BUSY_MS_BG`.
  - **손상만 재생성한다.** `OperationalError`("database is locked")도 `DatabaseError` 의
    하위라, 문구를 보지 않고 지우면 **잠깐 잠긴 것만으로 색인·사전을 통째로 잃는다**.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["BUSY_MS_UI", "BUSY_MS_BG", "connect", "tune", "is_corrupt_error"]

BUSY_MS_UI = 200        # UI 스레드: 잠깐이라도 기다리지 않는다(못 읽으면 '모름')
BUSY_MS_BG = 30000      # 워커: 얼마든 기다려도 좋다(사용자를 막지 않는다)


def tune(conn: sqlite3.Connection, busy_ms: int = BUSY_MS_BG) -> None:
    """연결 하나에 거는 잠금 규칙 — WAL + 대기 상한 + 커밋 비용 완화.

    각 PRAGMA 는 **따로** 감싼다. 하나가 안 먹는 환경(네트워크 드라이브 등)에서
    나머지까지 건너뛰지 않게."""
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass                      # 못 바꿔도 동작에는 지장 없다(느려질 뿐)
    try:
        # 이 DB 들은 모두 **다시 만들 수 있는 자료**다 — 매 커밋 fsync 는 과하다.
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA wal_autocheckpoint = 512")
    except Exception:
        pass


def connect(db_path, busy_ms: int = BUSY_MS_BG,
            row_factory: bool = True,
            readonly: bool = False) -> sqlite3.Connection:
    """표준 연결 — 부모 폴더 생성 + `timeout` + `tune()`.

    `busy_ms` 는 `sqlite3.connect(timeout=)` 와 `PRAGMA busy_timeout` 양쪽에 건다
    (앞의 것은 파이썬 쪽 대기, 뒤의 것은 SQLite 쪽 대기 — 둘 다 맞춰야 한다).

    260908-9(감사): `readonly=True` 는 **읽기만 하려는 곳**을 위한 것이다
    (예: 태그 워커가 `dict.db` 의 대역 맵을 훑을 때). 종전에는 그런 곳이
    `sqlite3.connect(... mode=ro ...)` 를 직접 불러 **대기 상한이 기본 5초**였다 —
    응답성 SOT §4 ⑤ 가 '어느 DB든' 이라고 못박은 바로 그 구멍이다.
    읽기 전용에서는 저널 모드를 바꿀 수 없으므로 대기 상한만 건다.
    """
    p = Path(db_path)
    if readonly:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True,
                               timeout=int(busy_ms) / 1000.0)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")
        except Exception:
            pass
        return conn
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(p, timeout=int(busy_ms) / 1000.0)
    if row_factory:
        conn.row_factory = sqlite3.Row
    tune(conn, busy_ms)
    return conn


def is_corrupt_error(e: Exception) -> bool:
    """'손상' 인가 — 잠금·권한 등 일시적 실패와 구분한다(§4 ⑤ 마지막 규칙)."""
    msg = str(e).lower()
    return ("malformed" in msg or "not a database" in msg
            or "file is encrypted" in msg or "corrupt" in msg)
