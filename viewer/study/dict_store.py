"""dict.db — 계층형 전문 용어사전(Base/User). 계획서 §4.2 (P1: 데이터 계층).

적용 우선순위: 사용자(User) ▶ 기본(Base) ▶ 자동(Auto, study.db).
- dict_source: 출처(사전/용어집) — 참고문헌·enabled(켜고끔)·priority(세부 우선순위)
- dict_entry : 표제어 항목 — term_ko/term_en, def_ko/def_en, examples, reference, level

저장 위치: settings_store.settings_dir()/'dict.db' (= %APPDATA%\\LocalTools\\PolyPDF).
study.db 재생성과 무관하게 보존(사용자/기본 사전은 영구 자산).
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = 7
USER_SOURCE_ID = "user"
ONLINE_SOURCE_ID = "online"

_NORM_RE = re.compile(r"[^0-9a-z가-힣]")


def normalize_key(s: str) -> str:
    """매칭/검색 정규화: 소문자 + 한글/영숫자만(공백·기호·한자병기·괄호 제거)."""
    return _NORM_RE.sub("", str(s or "").lower())


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def default_db_path() -> Path:
    try:
        from viewer.settings_store import settings_dir
        return settings_dir() / "dict.db"
    except Exception:
        return Path.home() / ".polypdf_dict.db"


class DictStore:
    """계층형 사전 저장소(Base/User 공존, 출처 kind 로 구분)."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._ensure_default_sources()
        self._migrate_user_words()
        # 260615-17: 기존 캐시의 HTML 마크업(&#44;·<strong> 등) 1회 일괄 정리
        if self._meta_get("markup_sanitized") != "1":
            try:
                self.sanitize_markup()
            except Exception:
                pass
            self._meta_set("markup_sanitized", "1")
        # 260615-18: 단일 '인터넷 사전' 출처 → 제공처별 출처로 1회 재분류(재조회 없음)
        if self._meta_get("online_reclassified") != "1":
            try:
                self.reclassify_online_sources()
            except Exception:
                pass
            self._meta_set("online_reclassified", "1")
        # 260616-2: 온용어 출처를 '인터넷' → '온용어사전' 구분으로 1회 분리
        if self._meta_get("onterm_category_split") != "1":
            try:
                self.conn.execute(
                    "UPDATE dict_source SET category='온용어사전' "
                    "WHERE source_id LIKE 'online_onterm%'")
                self.conn.commit()
            except Exception:
                pass
            self._meta_set("onterm_category_split", "1")

    # --- 스키마 ------------------------------------------------------------
    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dict_meta(
                key TEXT PRIMARY KEY, value TEXT);
            -- 출처(사전/용어집)
            CREATE TABLE IF NOT EXISTS dict_source(
                source_id  TEXT PRIMARY KEY,
                name       TEXT,            -- 출처명
                category   TEXT DEFAULT '', -- 구분(일반/도로/IT 등 사용자 등록명)
                kind       TEXT,            -- 'base' | 'user'
                reference  TEXT,            -- 참고문헌 인용
                enabled     INTEGER DEFAULT 1,
                priority    INTEGER DEFAULT 100,
                version     INTEGER DEFAULT 0,   -- 동봉 용어집 갱신 추적(재적재 판단)
                is_termbase INTEGER DEFAULT 1,   -- 전문용어집 여부(난이도='전문용어' 승격 대상)
                created_at  TEXT);
            -- 표제어 항목(개념 단위)
            CREATE TABLE IF NOT EXISTS dict_entry(
                entry_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id  TEXT,
                term_ko    TEXT,
                term_en    TEXT,
                norm_ko    TEXT,
                norm_en    TEXT,
                def_ko     TEXT,
                def_en     TEXT,
                examples   TEXT,
                reference  TEXT,
                level      TEXT,
                hanja      TEXT,
                image      TEXT DEFAULT '',  -- 그림 파일명(dict_images/ 기준)
                image_ref  TEXT DEFAULT '',  -- 그림 출처/라이선스(예: Openverse · CC-BY · 저작자)
                enabled    INTEGER DEFAULT 1,
                updated_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_entry_normko  ON dict_entry(norm_ko);
            CREATE INDEX IF NOT EXISTS ix_entry_normen  ON dict_entry(norm_en);
            CREATE INDEX IF NOT EXISTS ix_entry_source  ON dict_entry(source_id);
            -- 260615-10(P12): 예시(예문) 누적 — 단어장 생성 시 축적, 이후 재사용
            CREATE TABLE IF NOT EXISTS dict_example(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                norm TEXT, lemma TEXT, example TEXT,
                category TEXT DEFAULT '', source TEXT DEFAULT '', created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_dexa_norm ON dict_example(norm);
            -- 260615-13: 인터넷 사전 조회 완료 표시(재조회 방지 캐시)
            CREATE TABLE IF NOT EXISTS online_fetched(norm TEXT PRIMARY KEY, at TEXT);
            """
        )
        # v1→v2: dict_source.version, v2→v3: is_termbase (있으면 무시)
        for ddl in ("ALTER TABLE dict_source ADD COLUMN version INTEGER DEFAULT 0",
                    "ALTER TABLE dict_source ADD COLUMN is_termbase INTEGER DEFAULT 1",
                    "ALTER TABLE dict_source ADD COLUMN category TEXT DEFAULT ''",
                    "ALTER TABLE dict_entry ADD COLUMN image TEXT DEFAULT ''",
                    "ALTER TABLE dict_entry ADD COLUMN image_ref TEXT DEFAULT ''"):
            try:
                self.conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        self.conn.execute(
            "INSERT OR IGNORE INTO dict_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),))
        self._meta_set_silent("schema_version", str(SCHEMA_VERSION))
        self.conn.commit()

    def _meta_set_silent(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO dict_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _meta_get(self, key: str) -> Optional[str]:
        r = self.conn.execute("SELECT value FROM dict_meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def _meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO dict_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def _ensure_default_sources(self) -> None:
        """사용자 단어장 출처는 항상 존재(최우선 priority)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO dict_source"
            "(source_id,name,kind,reference,enabled,priority,created_at)"
            " VALUES(?,?,?,?,1,0,?)",
            (USER_SOURCE_ID, "사용자 단어장", "user", "", _now()))
        self.conn.commit()

    # --- 출처 CRUD ---------------------------------------------------------
    def add_source(self, source_id: str, name: str, kind: str = "base",
                   reference: str = "", priority: int = 100,
                   enabled: bool = True, version: int = 0,
                   is_termbase: bool = True, category: str = "") -> None:
        self.conn.execute(
            "INSERT INTO dict_source"
            "(source_id,name,category,kind,reference,enabled,priority,version,"
            " is_termbase,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,"
            " category=excluded.category, kind=excluded.kind,"
            " reference=excluded.reference, priority=excluded.priority,"
            " version=excluded.version, is_termbase=excluded.is_termbase",
            (source_id, name, category, kind, reference, 1 if enabled else 0, priority,
             int(version), 1 if is_termbase else 0, _now()))
        self.conn.commit()

    def source_version(self, source_id: str) -> int:
        r = self.conn.execute("SELECT version FROM dict_source WHERE source_id=?",
                              (source_id,)).fetchone()
        return int(r["version"]) if r and r["version"] is not None else -1

    def replace_source_entries(self, source_id: str, rows: Iterable[dict]) -> int:
        """동봉/임포트 용어집 재적재 — 해당 출처의 기존 항목을 비우고 새로 채움(멱등).

        기본 사전을 계속 보강할 때 같은 출처를 다시 적재해도 **중복이 생기지 않음**.
        사용자(user) 출처·다른 base 출처는 영향 없음."""
        self.conn.execute("DELETE FROM dict_entry WHERE source_id=?", (source_id,))
        self.conn.commit()
        return self.add_entries(source_id, rows)

    def seed_source_if_newer(self, source_id: str, name: str, *, reference: str,
                             version: int, rows: Iterable[dict], kind: str = "base",
                             priority: int = 50, is_termbase: bool = True,
                             category: str = "") -> bool:
        """동봉 용어집 시드/갱신(P3 용). 저장된 version 보다 새 version 일 때만 재적재.

        앱 업데이트로 기본 사전이 보강되면 그 출처만 최신으로 교체(사용자 항목 보존).
        반환: 재적재했으면 True."""
        if self.source_version(source_id) >= int(version):
            # 이미 최신 — 사용자가 끈 상태(enabled) 등은 보존하고 메타만 갱신 생략
            return False
        rows = list(rows)
        self.add_source(source_id, name, kind=kind, reference=reference,
                        priority=priority, version=int(version),
                        is_termbase=is_termbase, category=category)
        self.replace_source_entries(source_id, rows)
        return True

    def list_sources(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM dict_entry e"
            "  WHERE e.source_id=s.source_id AND e.enabled=1) AS n_entries"
            " FROM dict_source s ORDER BY"
            " CASE s.kind WHEN 'user' THEN 0 WHEN 'base' THEN 1 ELSE 2 END, s.priority")]

    def get_source(self, source_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM dict_source WHERE source_id=?",
                              (source_id,)).fetchone()
        return dict(r) if r else None

    def set_source_enabled(self, source_id: str, enabled: bool) -> None:
        self.conn.execute("UPDATE dict_source SET enabled=? WHERE source_id=?",
                          (1 if enabled else 0, source_id))
        self.conn.commit()

    def set_source_priority(self, source_id: str, priority: int) -> None:
        self.conn.execute("UPDATE dict_source SET priority=? WHERE source_id=?",
                          (int(priority), source_id))
        self.conn.commit()

    def delete_source(self, source_id: str) -> None:
        """출처와 그 항목 모두 삭제(사용자 출처는 보호)."""
        if source_id == USER_SOURCE_ID:
            return
        self.conn.execute("DELETE FROM dict_entry WHERE source_id=?", (source_id,))
        self.conn.execute("DELETE FROM dict_source WHERE source_id=?", (source_id,))
        self.conn.commit()

    # --- 항목 CRUD ---------------------------------------------------------
    def add_entry(self, *, source_id: str = USER_SOURCE_ID,
                  term_ko: str = "", term_en: str = "",
                  def_ko: str = "", def_en: str = "", examples: str = "",
                  reference: str = "", level: str = "", hanja: str = "",
                  image: str = "", image_ref: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO dict_entry"
            "(source_id,term_ko,term_en,norm_ko,norm_en,def_ko,def_en,examples,"
            " reference,level,hanja,image,image_ref,enabled,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (source_id, term_ko, term_en, normalize_key(term_ko),
             normalize_key(term_en), def_ko, def_en, examples, reference,
             level, hanja, image, image_ref, _now()))
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_user_term(self, term_en: str, term_ko: str, *, def_ko: str = "") -> int:
        """사용자 사전(User)에 (영문 표제어 → 한글 대역) 교정 1건 저장(중복 시 갱신).

        번역 용어집의 오역을 고칠 때 사용 — User 가 최우선이라 이후 모든 번역에 반영된다.
        같은 영문 표제어의 기존 User 항목은 비우고 새로 넣어 중복을 막는다."""
        en = (term_en or "").strip()
        ko = (term_ko or "").strip()
        if not en or not ko:
            return 0
        nen = normalize_key(en)
        self.conn.execute(
            "DELETE FROM dict_entry WHERE source_id=? AND norm_en=?",
            (USER_SOURCE_ID, nen))
        self.conn.commit()
        return self.add_entry(source_id=USER_SOURCE_ID, term_en=en, term_ko=ko, def_ko=def_ko)

    def add_entries(self, source_id: str, rows: Iterable[dict]) -> int:
        """대량 적재(임포트용). rows: term_ko/term_en/def_ko/def_en/examples/reference/level/hanja/image."""
        data = [(source_id, r.get("term_ko", ""), r.get("term_en", ""),
                 normalize_key(r.get("term_ko", "")), normalize_key(r.get("term_en", "")),
                 r.get("def_ko", ""), r.get("def_en", ""), r.get("examples", ""),
                 r.get("reference", ""), r.get("level", ""), r.get("hanja", ""),
                 r.get("image", ""), r.get("image_ref", ""), _now())
                for r in rows]
        self.conn.executemany(
            "INSERT INTO dict_entry"
            "(source_id,term_ko,term_en,norm_ko,norm_en,def_ko,def_en,examples,"
            " reference,level,hanja,image,image_ref,enabled,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)", data)
        self.conn.commit()
        return len(data)

    def update_entry(self, entry_id: int, **fields) -> None:
        allowed = {"term_ko", "term_en", "def_ko", "def_en", "examples",
                   "reference", "level", "hanja", "image", "image_ref",
                   "enabled", "source_id"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?"); args.append(v)
            if k == "term_ko":
                sets.append("norm_ko=?"); args.append(normalize_key(v))
            elif k == "term_en":
                sets.append("norm_en=?"); args.append(normalize_key(v))
        if not sets:
            return
        sets.append("updated_at=?"); args.append(_now())
        args.append(entry_id)
        self.conn.execute(f"UPDATE dict_entry SET {','.join(sets)} WHERE entry_id=?", args)
        self.conn.commit()

    def get_entry(self, entry_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM dict_entry WHERE entry_id=?",
                              (entry_id,)).fetchone()
        return dict(r) if r else None

    def delete_entry(self, entry_id: int, *, hard: bool = False) -> None:
        if hard:
            self.conn.execute("DELETE FROM dict_entry WHERE entry_id=?", (entry_id,))
        else:
            self.conn.execute("UPDATE dict_entry SET enabled=0, updated_at=? "
                              "WHERE entry_id=?", (_now(), entry_id))
        self.conn.commit()

    # --- 조회(레이어 우선순위) --------------------------------------------
    _LAYER_ORDER = ("ORDER BY CASE s.kind WHEN 'user' THEN 0 WHEN 'base' THEN 1 "
                    "ELSE 2 END, s.priority, e.entry_id")

    def _join_rows(self, where: str, args: list) -> list[dict]:
        sql = (
            "SELECT e.*, s.name AS src_name, s.category AS src_category,"
            " s.kind AS src_kind,"
            " s.reference AS src_reference, s.priority AS src_priority,"
            " s.is_termbase AS src_is_termbase"
            " FROM dict_entry e JOIN dict_source s ON s.source_id=e.source_id"
            f" WHERE e.enabled=1 AND s.enabled=1 AND {where} " + self._LAYER_ORDER)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def lookup(self, term: str) -> list[dict]:
        """표제어(한글/영문 표면형) 정확 매칭 — enabled 출처만, 우선순위 정렬."""
        nk = normalize_key(term)
        if not nk:
            return []
        return self._join_rows("(e.norm_ko=? OR e.norm_en=?)", [nk, nk])

    def best(self, term: str) -> Optional[dict]:
        """우선순위 1위 항목(사용자 ▶ 기본). 없으면 None."""
        rows = self.lookup(term)
        return rows[0] if rows else None

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """부분일치 검색(관련 단어 리스트·편집기 보조)."""
        nk = normalize_key(query)
        if not nk:
            return []
        like = f"%{nk}%"
        rows = self._join_rows("(e.norm_ko LIKE ? OR e.norm_en LIKE ?)", [like, like])
        return rows[:limit]

    def all_terms(self, *, kind: Optional[str] = None) -> list[dict]:
        """term spotting(P4)용 — 활성 출처의 항목 전체(우선순위 정렬)."""
        if kind:
            return self._join_rows("s.kind=?", [kind])
        return self._join_rows("1=1", [])

    def export_rows(self, source_id: Optional[str] = None) -> list[dict]:
        """260611-106(P7): 내보내기용 항목 — 출처 enabled 무관, 항목 enabled 만(삭제 제외).
        source_id 지정 시 그 출처만, None 이면 전체."""
        sql = ("SELECT e.*, s.name AS src_name, s.reference AS src_reference,"
               " s.kind AS src_kind FROM dict_entry e"
               " JOIN dict_source s ON s.source_id=e.source_id WHERE e.enabled=1")
        args: list = []
        if source_id:
            sql += " AND e.source_id=?"; args.append(source_id)
        sql += " ORDER BY e.source_id, e.entry_id"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def count(self, source_id: Optional[str] = None) -> int:
        if source_id:
            return self.conn.execute(
                "SELECT COUNT(*) c FROM dict_entry WHERE source_id=? AND enabled=1",
                (source_id,)).fetchone()["c"]
        return self.conn.execute(
            "SELECT COUNT(*) c FROM dict_entry WHERE enabled=1").fetchone()["c"]

    # --- 인터넷 사전 캐시(P11b) -------------------------------------------
    def ensure_online_source(self) -> None:
        """260615-13: 인터넷 사전 결과 캐시용 출처(구분='인터넷')."""
        if not self.get_source(ONLINE_SOURCE_ID):
            self.add_source(ONLINE_SOURCE_ID, "인터넷 사전", kind="base",
                            reference="", priority=70, is_termbase=False,
                            category="인터넷")

    def ensure_online_provider(self, source_id: str, name: str,
                               is_termbase: bool) -> None:
        """260615-18: 제공처별 인터넷 사전 출처(출처명=API명).
        260616-2: 온용어(online_onterm*)는 구분='온용어사전', 그 외는 '인터넷'."""
        if not self.get_source(source_id):
            cat = "온용어사전" if str(source_id).startswith("online_onterm") else "인터넷"
            self.add_source(source_id, name, kind="base", reference="",
                            priority=70, is_termbase=is_termbase, category=cat)

    def reclassify_online_sources(self) -> int:
        """260615-18: 기존 단일 'online'(인터넷 사전) 항목을 제공처별 출처로 재분류.
        **재조회 없이** 보관된 reference(제공처명)로 이동. 반환: 이동 항목 수."""
        try:
            from viewer.study.online_dict import ONLINE_PROVIDERS, ONLINE_NAME2ID
        except Exception:
            return 0
        rows = self.conn.execute(
            "SELECT entry_id, reference FROM dict_entry WHERE source_id=?",
            (ONLINE_SOURCE_ID,)).fetchall()
        moved = 0
        for r in rows:
            ref = (r["reference"] or "").strip()
            sid = None
            for part in [p.strip() for p in ref.split(",") if p.strip()]:
                if part in ONLINE_NAME2ID:
                    sid = ONLINE_NAME2ID[part]
                    break
            if not sid:                    # 제공처 불명 → 일반 인터넷 출처
                sid = "online_etc"
                self.ensure_online_provider(sid, "인터넷", False)
            else:
                nm, tb = ONLINE_PROVIDERS[sid]
                self.ensure_online_provider(sid, nm, tb)
            self.conn.execute("UPDATE dict_entry SET source_id=? WHERE entry_id=?",
                              (sid, r["entry_id"]))
            moved += 1
        self.conn.commit()
        # 비워진 옛 'online' 출처 정리
        if not self.conn.execute(
                "SELECT 1 FROM dict_entry WHERE source_id=? LIMIT 1",
                (ONLINE_SOURCE_ID,)).fetchone():
            self.conn.execute("DELETE FROM dict_source WHERE source_id=?",
                              (ONLINE_SOURCE_ID,))
            self.conn.commit()
        return moved

    def onterm_cached_terms(self) -> list[tuple]:
        """260615-20: 온용어 출처(online_onterm*)에 캐시된 (표제어, lang) 목록(중복 제거)."""
        rows = self.conn.execute(
            "SELECT DISTINCT e.term_ko, e.term_en FROM dict_entry e"
            " JOIN dict_source s ON s.source_id=e.source_id"
            " WHERE s.source_id LIKE 'online_onterm%'").fetchall()
        out = []
        for r in rows:
            if (r["term_ko"] or "").strip():
                out.append((r["term_ko"], "kor"))
            elif (r["term_en"] or "").strip():
                out.append((r["term_en"], "eng"))
        return out

    def clear_onterm_cache(self, terms) -> int:
        """260615-20: 주어진 표제어들의 **모든 인터넷(online_*) 캐시 + 재조회표시**를 삭제.
        (재조회 시 모든 제공처를 새로 받아 온용어를 용어집별로 다시 분류 — 중복 방지)
        terms: [(term, lang)]. 반환: 비운 표제어 수."""
        norms = {normalize_key(t) for t, _ in terms if normalize_key(t)}
        n = 0
        for nk in norms:
            self.conn.execute(
                "DELETE FROM dict_entry WHERE (norm_ko=? OR norm_en=?)"
                " AND source_id LIKE 'online_%'", (nk, nk))
            self.conn.execute("DELETE FROM online_fetched WHERE norm=?", (nk,))
            n += 1
        # 비워진 온용어 출처 정리
        for r in self.conn.execute(
                "SELECT source_id FROM dict_source WHERE source_id LIKE 'online_onterm%'").fetchall():
            if not self.conn.execute("SELECT 1 FROM dict_entry WHERE source_id=? LIMIT 1",
                                     (r["source_id"],)).fetchone():
                self.conn.execute("DELETE FROM dict_source WHERE source_id=?",
                                  (r["source_id"],))
        self.conn.commit()
        return n

    def is_online_fetched(self, lemma: str) -> bool:
        nk = normalize_key(lemma)
        if not nk:
            return True
        return bool(self.conn.execute(
            "SELECT 1 FROM online_fetched WHERE norm=?", (nk,)).fetchone())

    def mark_online_fetched(self, lemma: str) -> None:
        nk = normalize_key(lemma)
        if not nk:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO online_fetched(norm,at) VALUES(?,?)", (nk, _now()))
        self.conn.commit()

    # --- 예시 누적(P12) ----------------------------------------------------
    def add_examples(self, rows: Iterable[dict]) -> int:
        """예문 누적 — rows:[{lemma,example,category,source}]. (norm,example) 중복 제외."""
        n = 0
        for r in rows:
            nk = normalize_key(r.get("lemma", ""))
            ex = (r.get("example") or "").strip()
            if not nk or not ex:
                continue
            if self.conn.execute("SELECT 1 FROM dict_example WHERE norm=? AND example=?",
                                 (nk, ex)).fetchone():
                continue
            self.conn.execute(
                "INSERT INTO dict_example(norm,lemma,example,category,source,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (nk, r.get("lemma", ""), ex, r.get("category", ""),
                 r.get("source", ""), _now()))
            n += 1
        if n:
            self.conn.commit()
        return n

    def examples_for(self, lemma: str, limit: int = 10) -> list[dict]:
        nk = normalize_key(lemma)
        if not nk:
            return []
        return [dict(r) for r in self.conn.execute(
            "SELECT example,category,source FROM dict_example WHERE norm=?"
            " ORDER BY id LIMIT ?", (nk, int(limit)))]

    # --- HTML 마크업 일괄 정리(P11+) --------------------------------------
    @staticmethod
    def _clean_markup(s: str) -> str:
        """HTML 엔티티/태그 제거(줄바꿈 보존). 빈 줄 제거."""
        import html as _html
        out = []
        for line in str(s or "").split("\n"):
            t = _html.unescape(line)
            t = re.sub(r"<[^>]+>", "", t)
            t = re.sub(r"[ \t ]+", " ", t).strip()
            if t:
                out.append(t)
        return "\n".join(out)

    def sanitize_markup(self) -> int:
        """260615-17: dict_entry(def_ko/def_en/examples)·dict_example(example) 의
        HTML 마크업을 일괄 제거. 변경된 행 수 반환."""
        cl = self._clean_markup
        n = 0
        for r in self.conn.execute(
                "SELECT entry_id,def_ko,def_en,examples FROM dict_entry").fetchall():
            nk, ne, nex = cl(r["def_ko"]), cl(r["def_en"]), cl(r["examples"])
            if (nk, ne, nex) != ((r["def_ko"] or ""), (r["def_en"] or ""),
                                 (r["examples"] or "")):
                self.conn.execute(
                    "UPDATE dict_entry SET def_ko=?,def_en=?,examples=? WHERE entry_id=?",
                    (nk, ne, nex, r["entry_id"]))
                n += 1
        for r in self.conn.execute("SELECT id,example FROM dict_example").fetchall():
            ne = cl(r["example"])
            if ne != (r["example"] or ""):
                self.conn.execute("UPDATE dict_example SET example=? WHERE id=?",
                                  (ne, r["id"]))
                n += 1
        self.conn.commit()
        return n

    # --- 마이그레이션 ------------------------------------------------------
    def _migrate_user_words(self) -> None:
        """기존 user_study.db 의 user_word → dict_entry(user) 1회 이관."""
        if self._meta_get("migrated_user_words") == "1":
            return
        try:
            from viewer.study.study_store import UserStore
            us = UserStore()
            words = us.all_words()       # {(lemma,lang): {definition, example}}
            us.close()
        except Exception:
            words = {}
        rows = []
        for (lemma, lang), v in (words or {}).items():
            defi = (v.get("definition") or "").strip()
            ex = (v.get("example") or "").strip()
            if not (defi or ex):
                continue
            if str(lang).startswith("ko"):
                # 한국어 표제어 → 정의는 영어뜻 칸
                rows.append({"term_ko": lemma, "def_en": defi, "examples": ex})
            else:
                # 영어 표제어 → 정의는 한글뜻 칸
                rows.append({"term_en": lemma, "def_ko": defi, "examples": ex})
        if rows:
            self.add_entries(USER_SOURCE_ID, rows)
        self._meta_set("migrated_user_words", "1")

    def close(self) -> None:
        self.conn.close()
