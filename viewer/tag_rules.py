# -*- coding: utf-8 -*-
"""해시태그 사용자 규칙 — PDF 자동 해시태그 켜고 끄기·별칭 표·사진 자동 해시태그 (태그 SOT §5.8, 261107-10·261113-10).

저장은 `settings_dir()/tag_rules.json`(읽기는 `auto_tag.load_rules`). 키:
- `alias` {원래 태그: 붙일 태그} — 별칭 표(사진·주제 태그). PDF 자동 해시태그 이름은 바꿀 수 없다(261113-10 — 그 이름의 줄은 버린다)
- `format_off` [PDF 자동 해시태그 이름] — 붙이지 않는 항목(`auto_tag.PDF_AUTO_ITEMS`)
- `photo_off` ["date", "region", "device", "screenshot"] 중 — 붙이지 않는 사진 머리 태그
- `pdf_auto_v` 2 — 261113-10 한 번 정리를 마친 표시(없으면 앱 시작 뒤 정리, `migrate_if_needed`)
종전 `format_custom`(261112-11 '분류 더하기')은 없앴다 — 정리 때 그 분류의 자동 태그를 뗀다.

저장하면 곧바로 다시 붙인다(`TagRulesJob`) — 규칙 파일 쓰기·사진 색인 글·사진 머리 다시 읽기는 배경, 태그 저장소는 메인이 한 번에.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from viewer.i18n import tr

PHOTO_KINDS = ("date", "region", "device", "screenshot")      # 사진 종류(영수증·명함·서류)는 설정 photo_kind_ocr 이 켜고 끈다
PDF_AUTO_V = 3                       # 3 = 261114-14 '설명서' → '제품설명서' 옮기기
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RULE_KEYS = ("alias", "format_off", "photo_off", "format_custom", "pdf_auto_v")


def rules_path() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / "tag_rules.json"


def normalize(rules: dict | None) -> dict:
    """알 수 없는 값을 걸러 낸 규칙. 다른 키(사용자가 손으로 넣은 것)는 그대로 둔다."""
    from viewer.auto_tag import PDF_AUTO_ITEMS
    r = dict(rules or {})
    fixed = {f.lower() for f in PDF_AUTO_ITEMS}
    alias = {}
    for k, v in dict(r.get("alias") or {}).items():
        k, v = str(k or "").strip().lstrip("#"), str(v or "").strip().lstrip("#")
        if k and v and k != v and k.lower() not in fixed:     # 261113-10: PDF 자동 해시태그 이름은 고정
            alias[k] = v
    r["alias"] = alias
    r.pop("format_custom", None)                              # 261113-10: '분류 더하기' 없앰
    from viewer.auto_tag import RENAMED_FORMATS
    off = {RENAMED_FORMATS.get(f, f) for f in (r.get("format_off") or ())}     # 261114-14: 끈 '설명서' 는 끈 '제품설명서'
    r["format_off"] = [f for f in PDF_AUTO_ITEMS if f in off]
    r["photo_off"] = [k for k in PHOTO_KINDS if k in set(r.get("photo_off") or ())]
    if r.get("pdf_auto_v") != PDF_AUTO_V:
        r.pop("pdf_auto_v", None)
    for key in ("alias", "format_off", "photo_off"):
        if not r[key]:
            r.pop(key)
    return r


def save_rules(rules: dict, path=None) -> bool:
    """임시 파일 + 바꿔치기. **배경에서** 부른다(os.replace 백신 정지 — 마스터 §4.7.5)."""
    p = Path(path) if path else rules_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(normalize(rules), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def needs_migration(rules: dict | None) -> bool:
    return (rules or {}).get("pdf_auto_v") != PDF_AUTO_V


def remapper(old: dict | None, new: dict | None, migrate: bool = False):
    """옛 규칙으로 붙은 자동 태그 → 새 규칙의 태그(None = 뺀다) — `fn(태그, 파일 키)`.
    옛 붙일 이름 → 원래 이름 → 새 규칙. 끈 PDF 자동 해시태그는 **PDF 파일에서만** 뺀다(§5.8 의 7 — 사진의 같은 이름은 사진 설정 몫).
    migrate(§5.8 의 6): 빠진 종전 형식·사용자 분류(`format_custom`)의 자동 태그도 PDF 에서 뗀다."""
    from viewer.auto_tag import REMOVED_FORMATS, FORMAT_VOCAB, RENAMED_FORMATS
    raw_old = dict(old or {})
    ren = {k.lower(): v for k, v in RENAMED_FORMATS.items()} if migrate else {}
    new = normalize(new)
    rev = {}
    for k, v in dict(raw_old.get("alias") or {}).items():     # 정규화 전 — 종전 '형식 이름 바꾸기' 도 원래 이름으로
        k, v = str(k or "").strip().lstrip("#"), str(v or "").strip().lstrip("#")
        if k and v and k != v:
            rev[v.lower()] = k
    nal = {k.lower(): v for k, v in (new.get("alias") or {}).items()}
    off = {f.lower() for f in new.get("format_off") or ()}
    gone = set()
    if migrate:
        gone = {f.lower() for f in REMOVED_FORMATS}
        gone |= {str(c.get("name") or "").strip().lower() for c in raw_old.get("format_custom") or () if isinstance(c, dict)}
        gone -= {f.lower() for f in FORMAT_VOCAB}
        gone.discard("")

    def fn(tag: str, key: str = ""):
        std = rev.get((tag or "").lower(), tag)
        sl = std.lower()
        if str(key or "").lower().endswith(".pdf"):
            if sl in ren:                                   # 261114-14: 종전 형식 이름 → 새 이름(PDF 만)
                std = ren[sl]
                sl = std.lower()
            if sl in gone or sl in off or ("날짜" in off and _DATE.match(sl)):
                return None
        return nal.get(sl, std)
    fn.wants_key = True
    return fn


def diff(old: dict | None, new: dict | None) -> dict:
    """바뀐 것 — names(이름·끄기: 저장소만 옮기면 된다), formats_on(다시 켠 항목: 다시 판정), photo(사진 종류: 머리 다시 읽기)."""
    old, new = normalize(old), normalize(new)
    return {
        "names": old.get("alias") != new.get("alias") or old.get("format_off") != new.get("format_off"),
        "formats_on": sorted(set(old.get("format_off") or ()) - set(new.get("format_off") or ())),
        "photo": old.get("photo_off") != new.get("photo_off"),
    }


class RulesSaveWorker(QObject):
    done = pyqtSignal(bool)
    finished = pyqtSignal()

    def __init__(self, rules: dict, path=None):
        super().__init__()
        self.rules, self.path = rules, path

    def request_cancel(self):
        pass

    def run(self):
        ok = False
        try:
            ok = save_rules(self.rules, self.path)
        finally:
            self.done.emit(ok)
            self.finished.emit()


class PhotoTextWorker(QObject):
    """사진 정보 색인 행의 태그 글(사진 모드 검색)을 새 태그로 — {사진 경로: 태그}. 행이 없는 사진은 건너뛴다."""
    finished = pyqtSignal()

    def __init__(self, rows: dict):
        super().__init__()
        self.rows = dict(rows)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing, photo_index
        try:
            con = photo_index.connect()
            try:
                n = 0
                for path, tags in self.rows.items():
                    if self._cancel:
                        break
                    photo_index.set_tags(con, os.path.normcase(os.path.abspath(str(path))), tags)
                    n += 1
                    if n % 200 == 0:
                        con.commit()
                        pacing.pace(self)
                con.commit()
            finally:
                con.close()
        except Exception:
            pass
        finally:
            self.finished.emit()


class PhotoMetaRetagWorker(QObject):
    """사진 머리 태그를 새 규칙으로 다시(§5.8 의 4) — 사진 정보 색인의 모든 사진 행. zip 안·클라우드 전용(사진 보기 SOT §4.37)은 건너뛴다.
    {경로: 머리 태그} 를 묶어 내보내고 저장소에는 메인이 쓴다(`_photo_autotag_apply`)."""
    found = pyqtSignal(dict)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    BATCH = 50

    def __init__(self, rules: dict):
        super().__init__()
        self.rules = dict(rules or {})
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing, photo_index, photo_io, photo_tags
        out = {}
        try:
            try:
                con = photo_index.connect_read()
            except Exception:
                return
            try:
                rows = con.execute("SELECT key, path FROM photos WHERE zip IS NULL AND mtime_ns<>0").fetchall()
            finally:
                con.close()
            total = len(rows)
            for i, (_k, path) in enumerate(rows):
                if self._cancel:
                    break
                try:
                    if photo_io.cloud_only(os.stat(path)):
                        continue
                    out[path] = photo_tags.meta_tags(path, photo_io.photo_info(path), self.rules)
                except OSError:
                    continue
                except Exception:
                    out[path] = []
                if len(out) >= self.BATCH:
                    self.found.emit(out)
                    out = {}
                    self.progress.emit(i + 1, total)
                pacing.pace(self)
        finally:
            if out:
                self.found.emit(out)
            self.finished.emit()


class TagRulesJob(QObject):
    """저장하면 곧바로 다시 붙이기(§5.8) — 작업 창 한 줄·취소, 시작·끝을 상태 막대에. MainWindow 하나에 하나."""
    JID = "tag_rules"
    ended = pyqtSignal(int)                      # 바뀐 파일 수 — 검사용

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self._workers = []
        self._cancel = False
        self._changed = set()
        self._rid = 0                            # 다시 저장하면 앞 회차의 신호는 버린다

    def _g(self, fn):
        r = self._rid
        return lambda *a: (fn(*a) if r == self._rid else None)

    # 메인에서 부른다
    def apply(self, new_rules: dict):
        from viewer.auto_tag import load_rules
        self.cancel()
        if self._rid:
            self._job(False)                     # 앞 회차의 작업 창 줄
        self._rid += 1
        self._cancel = False
        self._changed = set()
        self.old = load_rules()
        self.migrate = needs_migration(self.old)                 # 261113-10 한 번 정리(§5.8 의 6)
        keep = {k: v for k, v in (self.old or {}).items() if k not in RULE_KEYS}
        self.new = normalize({**keep, **normalize(new_rules), "pdf_auto_v": PDF_AUTO_V})    # 사용자가 손으로 넣은 다른 키는 남긴다
        self.d = diff(self.old, self.new)
        if self.migrate:
            self.d["names"] = True
        self._job(True)
        self._status(tr("해시태그 규칙 적용 시작 — 이미 붙은 자동 태그를 새 규칙으로 바꿉니다"))
        w = RulesSaveWorker(self.new)
        w.done.connect(self._g(self._on_saved))
        self._run(w)

    def cancel(self):
        self._cancel = True
        for w in list(self._workers):
            try:
                w.request_cancel()
            except Exception:
                pass

    def _run(self, w):
        from viewer.workers import run_in_thread
        self._workers.append(w)
        w.finished.connect(lambda _w=w: self._workers.remove(_w) if _w in self._workers else None)
        run_in_thread(w, self.mw.__dict__.setdefault("_thread_keep", []))

    def _job(self, on: bool):
        try:
            if on:
                self.mw.job_add(self.JID, tr("해시태그 규칙 적용"), cancel=self.cancel)
            else:
                self.mw.job_done(self.JID)
        except Exception:
            pass

    def _status(self, msg: str, ms: int = 6000):
        try:
            self.mw.status.showMessage(msg, ms)
        except Exception:
            pass

    def _store(self):
        return getattr(getattr(self.mw, "bookmark_tree", None), "_tags", None)

    def _on_saved(self, ok: bool):
        if not ok:
            self._job(False)
            self._status(tr("해시태그 규칙을 저장하지 못했습니다 — 아무것도 바꾸지 않았습니다"))
            return
        if self._cancel:
            return self._finish()
        store = self._store()
        if store is not None and self.d["names"]:
            if not store.backup():
                self._job(False)
                self._status(tr("태그 백업 실패 — 해시태그 규칙 적용을 건너뜀"))
                return
            keys = store.remap_auto(remapper(self.old, self.new, self.migrate))
            self._changed |= set(keys)
            if self.migrate:                                # 261114-14: 직접 붙인·거절한 종전 형식 이름도(PDF 만)
                from viewer.auto_tag import RENAMED_FORMATS
                for o, n in RENAMED_FORMATS.items():
                    self._changed |= set(store.rename_pdf_tag(o, n))
            try:
                self.mw.bookmark_tree.refresh_tag_labels()
            except Exception:
                pass
        if self.d["formats_on"] and not self._cancel:
            try:
                self.mw._start_autotag_scan(force=True)     # 다시 켠 형식 — 지금 목록의 PDF 다시 판정(§5.8 의 4)
            except Exception:
                pass
        if self.d["photo"] and not self._cancel:
            w = PhotoMetaRetagWorker(self.new)
            w.found.connect(self._g(self._on_photo_meta))
            w.progress.connect(self._g(self._progress))
            w.finished.connect(self._g(self._after_photo))
            self._run(w)
            return
        self._after_photo()

    def _progress(self, i: int, n: int):
        try:
            self.mw.job_progress(self.JID, tr("사진 {i}/{n}").format(i=i, n=n))
        except Exception:
            pass

    def _on_photo_meta(self, found: dict):
        store = self._store()
        if store is None:
            return
        try:
            self.mw._photo_autotag_apply(found, "meta", self)
        except Exception:
            with store.bulk():
                for p, ts in found.items():
                    store.set_auto_part(p, "meta", ts)
        self._changed |= {store._key(p) for p in found}

    def _after_photo(self):
        from viewer.image_page import PHOTO_EXTS
        store = self._store()
        rows = {}
        if store is not None and not self._cancel:
            exts = tuple(e.lower() for e in PHOTO_EXTS)
            for k in self._changed:
                if str(k).lower().endswith(exts):
                    rows[k] = store.get(k)
        if rows:
            w = PhotoTextWorker(rows)
            w.finished.connect(self._g(self._finish))
            self._run(w)
            return
        self._finish()

    def _finish(self):
        self._job(False)
        n = len(self._changed)
        if self._cancel:
            self._status(tr("해시태그 규칙 적용을 멈췄습니다 — 여기까지 바꾼 것은 남습니다: {n}개 파일").format(n=n))
        else:
            self._status(tr("해시태그 규칙 적용 끝 — {n}개 파일").format(n=n))
        self.ended.emit(n)


def migrate_if_needed(mw):
    """261113-10(§5.8 의 6): 규칙 파일에 `pdf_auto_v` 가 없으면 지금 규칙 그대로 한 번 적용 — 빠진 형식·사용자 분류의 자동 태그를 떼고
    종전 형식 이름 바꾸기를 원래 이름으로. 앱 시작 뒤 한 번(MainWindow)."""
    from viewer.auto_tag import load_rules
    cur = load_rules()
    if not needs_migration(cur):
        return None
    return apply(mw, cur)


def apply(mw, new_rules: dict) -> TagRulesJob:
    """환경설정 [저장] 에서 부른다 — 규칙을 쓰고 곧바로 다시 붙인다(§5.8)."""
    job = mw.__dict__.get("_tag_rules_job")
    if job is None:
        job = TagRulesJob(mw)
        mw._tag_rules_job = job
    job.apply(new_rules)
    return job
