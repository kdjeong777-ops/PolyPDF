"""study.db — OCR/어휘 캐시 (기존 index.db 와 분리, 계획서 §4).

저장 위치: settings_store.settings_dir() / 'study.db' (= %APPDATA%\\LocalTools\\PolyPDF).
file_key = 파일 절대경로의 sha1(앞 16자) — 동일 파일 재오픈 시 캐시 적중.
재개(resume): ocr_page PK(file_key,page) 로 이미 처리한 페이지를 스킵.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional


def file_key_for(path: str | Path) -> str:
    """파일 절대경로 기반 안정 키."""
    p = str(Path(path).resolve()).lower()
    return hashlib.sha1(p.encode("utf-8")).hexdigest()[:16]


def default_db_path() -> Path:
    """기존 settings/index 와 동일 폴더의 study.db."""
    try:
        from viewer.settings_store import settings_dir
        return settings_dir() / "study.db"
    except Exception:
        # GUI 밖(테스트) 폴백
        return Path.home() / ".polypdf_study.db"


class StudyStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

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
        cur.execute("DELETE FROM ocr_page WHERE file_key=? AND page=?", (file_key, page))
        cur.execute("DELETE FROM ocr_word WHERE file_key=? AND page=?", (file_key, page))
        cur.execute(
            "INSERT INTO ocr_page(file_key,page,text,dpi,engine,source,conf,done_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (file_key, page, text, dpi, engine, source, conf,
             time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        cur.executemany(
            "INSERT INTO ocr_word(file_key,page,lemma,surface,lang,x0,y0,x1,y1,conf)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(file_key, page, w.get("lemma", ""), w["surface"], lang,
              w["x0"], w["y0"], w["x1"], w["y1"], w.get("conf", 0.0))
             for w in words],
        )
        self.conn.commit()

    def set_meta(self, file_key: str, path: str, page_count: int, lang: str) -> None:
        self.conn.execute(
            "INSERT INTO study_meta(file_key,path,page_count,lang,updated_at)"
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
            self.conn.execute(f"DELETE FROM {tbl} WHERE file_key=?", (file_key,))
        self.conn.commit()

    def clear_file(self, file_key: str) -> None:
        """260615-6: 해당 파일의 OCR·어휘 캐시 전체 삭제 → '단어장 다시 만들기'용."""
        for tbl in ("ocr_page", "ocr_word", "vocab", "vocab_page"):
            self.conn.execute(f"DELETE FROM {tbl} WHERE file_key=?", (file_key,))
        self.conn.commit()

    def save_vocab(self, file_key: str, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vocab(file_key,lemma,lang,level,zipf,freq_in_book)"
            " VALUES(?,?,?,?,?,?)",
            [(file_key, r["lemma"], r["lang"], r["level"], r.get("zipf"),
              r.get("freq_in_book", 0)) for r in rows])
        self.conn.commit()

    def save_page_lemmas(self, file_key: str, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vocab_page(file_key,page,lemma,lang,count,pos)"
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

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            try:
                from viewer.settings_store import settings_dir
                db_path = settings_dir() / "user_study.db"
            except Exception:
                db_path = Path.home() / ".polypdf_user_study.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
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
