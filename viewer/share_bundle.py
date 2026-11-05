# -*- coding: utf-8 -*-
"""261105-9(마스터 §4.7.23, 사용자 결정 '묶음 파일(.zip)'): '전달' — PDF 와 PolyPDF 자료를 **한 묶음**으로.

OCR 결과·고친 글·하이라이트·고른 낱말·태그는 이 PC 의 설정 폴더에, 꾸밈·하이퍼링크는 폴더 사이드카에 있어
PDF 만 보내면 받는 사람은 책갈피와 [저장]한 꾸밈만 본다. 묶음 `<이름>.polypdf.zip` 은

    <원본 PDF 그대로>.pdf ...      ← 바이트 그대로(서명이 깨지지 않는다)
    polypdf_share.json             ← 파일마다 자료(아래), 형식 이름·판

을 담는다. 받는 PolyPDF 가 열면(끌어 놓기·[열기]) 고른 폴더에 PDF 를 풀고 자료를 **그 경로 키로** 넣는다.
다른 프로그램 사용자도 압축을 풀면 PDF 는 그대로 쓴다.

안전 — 묶음은 남이 보낸 파일이다: JSON 만 읽고(코드 실행 없음), 이름은 **파일 이름만**(폴더·`..` 버림)·`.pdf` 만,
PDF 는 목록의 SHA-256 과 맞을 때만 그 자료를 넣는다, 크기 상한(`MAX_PDF_BYTES`·`MAX_JSON_BYTES`). Qt 없음 — 배경에서 부른다.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

from viewer.i18n import tr

FORMAT = "polypdf-share"
VERSION = 1
SUFFIX = ".polypdf.zip"
MANIFEST = "polypdf_share.json"
MAX_PDF_BYTES = 2 * 1024 ** 3          # 묶음 안 PDF 하나 상한(2GB)
MAX_JSON_BYTES = 512 * 1024 ** 2       # 자료 JSON 상한(512MB — OCR 낱말 수십만 개)
PARTS = ("ocr", "fix", "deco", "tags")  # 고를 수 있는 자료 — OCR·단어장 / 고친 글·하이라이트 / 꾸밈·링크 / 태그·키워드


def is_bundle(path) -> bool:
    return str(path).lower().endswith(SUFFIX)


def default_name(paths) -> str:
    ps = [Path(p) for p in paths]
    if len(ps) == 1:
        return ps[0].stem + SUFFIX
    return tr('전달_{date}_{n}개').format(date=time.strftime("%y%m%d"), n=len(ps)) + SUFFIX


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ── 만들기 ─────────────────────────────────────────────────────────
def _ocr_of(st, key: str) -> dict:
    """보이는 그대로(보류 ▶ 저장본) — 그 파일의 OCR 쪽·낱말·어휘."""
    c = st.conn
    out = {"pages": [list(r) for r in c.execute(
        "SELECT page,text,dpi,engine,source,conf FROM ocr_page WHERE file_key=? ORDER BY page", (key,))]}
    if not out["pages"]:
        return {}
    out["words"] = [list(r) for r in c.execute(
        "SELECT page,lemma,surface,lang,x0,y0,x1,y1,conf FROM ocr_word WHERE file_key=?", (key,))]
    out["vocab"] = [list(r) for r in c.execute(
        "SELECT lemma,lang,level,zipf,freq_in_book FROM vocab WHERE file_key=?", (key,))]
    out["vocab_page"] = [list(r) for r in c.execute(
        "SELECT page,lemma,lang,count,pos FROM vocab_page WHERE file_key=?", (key,))]
    m = c.execute("SELECT page_count,lang FROM study_meta WHERE file_key=?", (key,)).fetchone()
    if m:
        out["meta"] = [m[0], m[1]]
    return out


def collect(path, parts=PARTS, *, page_meta=None, hyperlinks=None, tags=None, study_db=None, user_db=None, fix_store=None) -> dict:
    """그 PDF 의 자료 한 묶음(dict). `page_meta`·`hyperlinks` 는 그 파일이 든 폴더의 사이드카 저장소, `tags` 는 TagStore."""
    from viewer.study.study_store import StudyStore, UserStore, file_key_for
    from viewer import dbutil
    p = Path(path)
    rec = {"name": p.name, "size": p.stat().st_size, "sha256": _sha256(p)}
    key = file_key_for(p)
    if "ocr" in parts:
        try:
            st = StudyStore(study_db, busy_ms=dbutil.BUSY_MS_BG)
            try:
                o = _ocr_of(st, key)
            finally:
                st.close()
            if o:
                rec["ocr"] = o
        except Exception:
            pass
        try:
            us = UserStore(user_db, busy_ms=dbutil.BUSY_MS_BG)
            try:
                sel = [list(r) for r in us.conn.execute(
                    "SELECT lemma,date,action,ts FROM sel_event WHERE file_key=? ORDER BY ts", (key,))]
            finally:
                us.close()
            if sel:
                rec["sel"] = sel
        except Exception:
            pass
    if "fix" in parts:
        try:
            if fix_store is None:
                from viewer.text_fix_store import store
                fix_store = store()
            d = fix_store.export_doc(p)
            if d:
                rec["fix"] = d
        except Exception:
            pass
    if "deco" in parts:
        for name, stx in (("page_meta", page_meta), ("hyperlinks", hyperlinks)):
            try:
                ent = stx.export_entry(p) if stx is not None else None
                if ent:
                    rec[name] = ent
            except Exception:
                pass
    if "tags" in parts and tags is not None:
        try:
            t = {"manual": list(tags.get_manual(str(p)) or []), "keywords": list(tags.get_keywords(str(p)) or [])}
            if t["manual"] or t["keywords"]:
                rec["tags"] = t
        except Exception:
            pass
    return rec


def build(paths, out_zip, parts=PARTS, *, stores_for=None, tags=None, progress=None, **kw) -> Path:
    """묶음을 만든다 — 임시 이름에 쓰고 다 쓰면 바꿔 이름(실패하면 반쯤 쓴 파일을 남기지 않는다).
    `stores_for(폴더) -> (page_meta, hyperlinks)`. `progress(i, n, 이름)` 이 False 면 멈춘다(임시 파일 지움)."""
    ps = [Path(p) for p in paths]
    out = Path(out_zip)
    tmp = out.with_name(out.name + ".tmp")
    names = set()
    files = []
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for i, p in enumerate(ps):
                if progress is not None and progress(i, len(ps), p.name) is False:
                    raise InterruptedError()
                pm = hl = None
                if stores_for is not None:
                    try:
                        pm, hl = stores_for(str(p.parent))
                    except Exception:
                        pm = hl = None
                rec = collect(p, parts, page_meta=pm, hyperlinks=hl, tags=tags, **kw)
                arc = p.name
                n = 2
                while arc.lower() in names:              # 다른 폴더의 같은 이름 — 묶음 안에서만 번호
                    arc = f"{p.stem} ({n}){p.suffix}"; n += 1
                names.add(arc.lower())
                rec["name"] = arc
                z.write(str(p), arc, compress_type=zipfile.ZIP_STORED)   # PDF 는 이미 압축돼 있다 — 그대로
                files.append(rec)
            man = {"format": FORMAT, "version": VERSION, "made": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "app": _app_version(), "parts": [x for x in PARTS if x in parts], "files": files}
            z.writestr(MANIFEST, json.dumps(man, ensure_ascii=False))
        os.replace(str(tmp), str(out))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    if progress is not None:
        progress(len(ps), len(ps), "")
    return out


def _app_version() -> str:
    try:
        from viewer import __version__
        return __version__
    except Exception:
        return ""


# ── 받기 ─────────────────────────────────────────────────────────
class BundleError(Exception):
    pass


def read_manifest(zip_path) -> dict:
    """묶음의 목록을 읽어 검사한다 — 형식이 다르거나 판이 더 새것이면 BundleError."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            try:
                info = z.getinfo(MANIFEST)
            except KeyError:
                raise BundleError(tr("PolyPDF 전달 묶음이 아닙니다(목록 없음)."))
            if info.file_size > MAX_JSON_BYTES:
                raise BundleError(tr("묶음 목록이 너무 큽니다."))
            man = json.loads(z.read(MANIFEST).decode("utf-8"))
    except zipfile.BadZipFile:
        raise BundleError(tr("압축 파일이 손상됐습니다."))
    if not isinstance(man, dict) or man.get("format") != FORMAT:
        raise BundleError(tr("PolyPDF 전달 묶음이 아닙니다."))
    if int(man.get("version") or 0) > VERSION:
        raise BundleError(tr("더 새 PolyPDF 가 만든 묶음입니다 — PolyPDF 를 업데이트하세요."))
    files = [f for f in (man.get("files") or []) if isinstance(f, dict) and _safe_name(f.get("name"))]
    man["files"] = files
    return man


def _safe_name(name) -> str:
    """묶음 안 이름에서 **파일 이름만**(폴더·드라이브·`..` 버림). PDF 가 아니면 ""."""
    if not isinstance(name, str):
        return ""
    base = name.replace("\\", "/").split("/")[-1].strip()
    if not base or base in (".", "..") or not base.lower().endswith(".pdf") or ":" in base:
        return ""
    return base


def extract(zip_path, dest_dir, progress=None) -> list:
    """PDF 를 dest_dir 에 풀고(같은 이름이면 번호) 자료를 그 경로 키로 넣을 준비 — [(새 경로, 기록, 해시 맞음)].
    PDF 는 임시 이름에 쓰고 해시를 본 뒤 바꿔 이름."""
    from viewer.pathutil import unique_path
    man = read_manifest(zip_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        files = man["files"]
        for i, rec in enumerate(files):
            if progress is not None and progress(i, len(files), rec.get("name", "")) is False:
                raise InterruptedError()
            name = _safe_name(rec.get("name"))
            try:
                info = z.getinfo(rec.get("name"))
            except KeyError:
                continue
            if info.file_size > MAX_PDF_BYTES:
                continue
            target = unique_path(dest / name)
            tmp = target.with_name(target.name + ".polypdf-tmp")
            h = hashlib.sha256()
            try:
                with z.open(info) as src, open(tmp, "wb") as dst:
                    for b in iter(lambda: src.read(1 << 20), b""):
                        h.update(b)
                        dst.write(b)
                os.replace(str(tmp), str(target))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            out.append((target, rec, h.hexdigest() == str(rec.get("sha256") or "")))
    if progress is not None:
        progress(len(man["files"]), len(man["files"]), "")
    return out


def apply_records(new_path, rec: dict, *, study_db=None, user_db=None, fix_store=None) -> list:
    """푼 PDF 의 자료를 그 경로 키로 — OCR(저장본으로: 받기는 사용자가 고른 일이다)·고른 낱말·고친 글. 넣은 자료 이름 목록.
    꾸밈·링크·태그는 Qt 쪽 저장소라 앱이 넣는다(`rec['page_meta']` 등)."""
    from viewer.study.study_store import StudyStore, UserStore, file_key_for
    from viewer import dbutil
    p = Path(new_path)
    key = file_key_for(p)
    done = []
    o = rec.get("ocr") or {}
    if o.get("pages"):
        st = StudyStore(study_db, busy_ms=dbutil.BUSY_MS_BG)
        try:
            c = st.conn
            with c:
                for t in ("ocr_page", "ocr_word", "vocab", "vocab_page", "study_meta"):
                    c.execute(f"DELETE FROM main.{t} WHERE file_key=?", (key,))
                c.executemany("INSERT OR REPLACE INTO main.ocr_page(file_key,page,text,dpi,engine,source,conf,done_at)"
                              " VALUES(?,?,?,?,?,?,?,?)",
                              [(key, int(r[0]), str(r[1] or ""), int(r[2] or 0), str(r[3] or ""), str(r[4] or ""),
                                float(r[5] or 0), time.strftime("%Y-%m-%dT%H:%M:%S")) for r in o["pages"] if len(r) >= 6])
                c.executemany("INSERT INTO main.ocr_word(file_key,page,lemma,surface,lang,x0,y0,x1,y1,conf)"
                              " VALUES(?,?,?,?,?,?,?,?,?,?)",
                              [(key, int(r[0]), str(r[1] or ""), str(r[2] or ""), str(r[3] or ""),
                                float(r[4]), float(r[5]), float(r[6]), float(r[7]), float(r[8] or 0))
                               for r in (o.get("words") or []) if len(r) >= 9])
                c.executemany("INSERT OR REPLACE INTO main.vocab(file_key,lemma,lang,level,zipf,freq_in_book) VALUES(?,?,?,?,?,?)",
                              [(key, str(r[0]), str(r[1]), str(r[2] or ""), r[3], int(r[4] or 0))
                               for r in (o.get("vocab") or []) if len(r) >= 5])
                c.executemany("INSERT OR REPLACE INTO main.vocab_page(file_key,page,lemma,lang,count,pos) VALUES(?,?,?,?,?,?)",
                              [(key, int(r[0]), str(r[1]), str(r[2]), int(r[3] or 1), int(r[4] or 0))
                               for r in (o.get("vocab_page") or []) if len(r) >= 5])
                m = o.get("meta") or [len(o["pages"]), ""]
                c.execute("INSERT OR REPLACE INTO main.study_meta(file_key,path,page_count,lang,updated_at) VALUES(?,?,?,?,?)",
                          (key, str(p), int(m[0] or 0), str(m[1] or ""), time.strftime("%Y-%m-%dT%H:%M:%S")))
            done.append("ocr")
        finally:
            st.close()
    if rec.get("sel"):
        us = UserStore(user_db, busy_ms=dbutil.BUSY_MS_BG)
        try:
            with us.conn:
                us.conn.execute("DELETE FROM sel_event WHERE file_key=?", (key,))
                us.conn.executemany("INSERT INTO sel_event(file_key,lemma,date,action,ts) VALUES(?,?,?,?,?)",
                                    [(key, str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rec["sel"] if len(r) >= 4])
            done.append("sel")
        finally:
            us.close()
    if isinstance(rec.get("fix"), dict) and rec["fix"]:
        if fix_store is None:
            from viewer.text_fix_store import store
            fix_store = store()
        if fix_store.import_doc(p, rec["fix"]):
            done.append("fix")
    return done
