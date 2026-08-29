"""파일 해시태그·키워드·연도 저장소 — SOT: `파일 태그·키워드 작업 계획서.md`.

스키마 v2 (§6, 260829): `file_tags.json` 의 **값 타입으로 버전 구분**.
- v1 = list       → 전부 수동 태그. 그대로 유효(마이그레이션 없음 — lazy).
- v2 = dict       → manual/auto/auto_conf/rejected/keywords/year/fp …

핵심 계약 (위반 = 회귀 위험 1순위, §6):
- `get()` 은 **manual + auto 합집합**(manual 우선) — 트리 라벨·`#` 필터·
  `all_tags()` 가 전부 여기 걸려 있어 반환 형태를 바꾸면 안 된다.
- `set()` 은 **manual 로만** 쓴다. auto/rejected/keywords 는 보존.
- 자동 로직이 manual 을 건드리는 경로는 없다(§1-②).

파일 이동 내성 (§6.1, 260829 — 기존 절대경로 키 결함 수정):
- 경로가 주 키(조회 O(1)·v1 호환). 경로가 빗나가면 **지문**으로 재연결.
- 지문: PDF `/ID[0]`(`id:`) ▶ 폴백 `size`+앞 64KB SHA-1(`h64:`).
- ★ 유일성 가드 — 지문이 2개 이상 항목에 걸리면 재연결하지 않는다
  (분할 산출물이 `/ID` 를 공유할 수 있다). `id:` 중복 감지 시 `h64:` 강등.
- 이사만 자동 처리, 복사본은 상속하지 않는다(조용한 복제 금지).
- 고아 항목은 앱이 임의로 지우지 않는다 — `prune_missing()` 은 사용자
  확인 후에만 호출된다(§8.5).

저장 견고성 (§6):
- ★ 원자적 쓰기(tmp + `os.replace`) — `secure_store` 260618-4 와 같은 함정.
- 일괄 작업은 `with store.bulk():` 로 저장을 모아 **1회**만 쓴다.

표준 라이브러리만 사용(지문의 `/ID` 읽기에만 fitz 를 지연 임포트).
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

MAX_KEYWORDS = 10          # §9.1 — 파일당 키워드 상한


def normalize_tags(tags) -> list:
    """문자열('#도로 콘크리트, 지침') 또는 리스트 → 정규화 태그 리스트(앞 '#'·공백 제거, 중복 제거)."""
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out, seen = [], set()
    for t in (tags or []):
        t = (t or "").lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


class TagStore:
    def __init__(self, path=None):
        if path is None:
            try:
                from viewer.settings_store import settings_dir
                path = Path(settings_dir()) / "file_tags.json"
            except Exception:
                path = Path.home() / ".polypdf_file_tags.json"
        self._path = Path(path)
        self._data = {}          # key(절대경로 소문자) -> list(v1) | dict(v2)
        self._bulk_depth = 0
        self._dirty = False
        self._load()

    # ── 로드/저장 ─────────────────────────────────────────────────────────
    def _load(self):
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8")) or {}
        except Exception:
            self._data = {}

    def _save(self):
        """260829(§6): ★ 원자적 쓰기 — 임시파일 + os.replace. 중간 크래시에도 JSON 이 깨지지 않는다.
        bulk() 안에서는 쓰지 않고 표시만 해 뒀다가 빠져나올 때 1회 저장."""
        if self._bulk_depth > 0:
            self._dirty = True
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=0), encoding="utf-8")
            os.replace(tmp, self._path)
            self._dirty = False
        except Exception:
            pass

    @contextmanager
    def bulk(self):
        """일괄 작업용 — 블록 안의 모든 변경을 모아 저장 1회(§6·§7)."""
        self._bulk_depth += 1
        try:
            yield self
        finally:
            self._bulk_depth -= 1
            if self._bulk_depth == 0 and self._dirty:
                self._save()

    # ── 백업/복원 (§6 되돌리기) ───────────────────────────────────────────
    def backup(self) -> bool:
        """일괄 자동 부여 직전 스냅샷(1세대). 실패 시 False — 호출자는 일괄을 시작하면 안 된다."""
        try:
            import shutil
            if not self._path.exists():          # 파일이 아직 없으면 빈 스냅샷
                self._save()
            shutil.copy2(self._path, self._bak_path())
            return self._bak_path().exists()
        except Exception:
            return False

    def restore_backup(self) -> bool:
        try:
            import shutil
            if not self._bak_path().exists():
                return False
            shutil.copy2(self._bak_path(), self._path)
            self._load()
            return True
        except Exception:
            return False

    def _bak_path(self) -> Path:
        return self._path.with_name("file_tags.bak.json")

    # ── 키/레코드 ─────────────────────────────────────────────────────────
    @staticmethod
    def _key(p) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except Exception:
            return str(p or "").lower()

    def _dictify(self, key: str) -> dict:
        """v1(list) 항목을 v2(dict)로 승격(lazy 마이그레이션, §6). 없으면 생성."""
        v = self._data.get(key)
        if v is None:
            v = {"manual": []}
            self._data[key] = v
        elif isinstance(v, list):
            v = {"manual": list(v)}
            self._data[key] = v
        return v

    @staticmethod
    def _is_empty_rec(v) -> bool:
        if isinstance(v, list):
            return not v
        return not any(v.get(f) for f in
                       ("manual", "auto", "rejected", "keywords", "year", "fp"))

    def _collapse(self, key: str):
        v = self._data.get(key)
        if v is not None and self._is_empty_rec(v):
            self._data.pop(key, None)

    # ── 태그 조회/수정 — v1 계약 유지 ─────────────────────────────────────
    def get(self, path) -> list:
        """★ manual + auto 합집합(manual 우선). 반환 형태 변경 금지(§6 회귀 위험 1순위)."""
        v = self._data.get(self._key(path))
        if v is None:
            return []
        if isinstance(v, list):
            return list(v)
        man = list(v.get("manual") or [])
        low = {t.lower() for t in man}
        return man + [t for t in (v.get("auto") or []) if t.lower() not in low]

    def set(self, path, tags):
        """manual 로만 저장. auto/rejected/keywords 등은 보존(§6)."""
        tags = normalize_tags(tags)
        k = self._key(path)
        v = self._data.get(k)
        if v is None or isinstance(v, list):
            if tags:
                self._data[k] = tags                 # v1 형태 유지(파일 최소 변경)
            else:
                self._data.pop(k, None)
        else:
            v["manual"] = tags
            self._collapse(k)
        self._save()

    def get_manual(self, path) -> list:
        v = self._data.get(self._key(path))
        if isinstance(v, list):
            return list(v)
        if isinstance(v, dict):
            return list(v.get("manual") or [])
        return []

    def get_auto(self, path) -> list:
        v = self._data.get(self._key(path))
        if isinstance(v, dict):
            return list(v.get("auto") or [])
        return []

    def is_auto(self, path, tag) -> bool:
        return (tag or "").lower() in {t.lower() for t in self.get_auto(path)}

    def get_rejected(self, path) -> list:
        v = self._data.get(self._key(path))
        if isinstance(v, dict):
            return list(v.get("rejected") or [])
        return []

    def set_auto(self, path, tags, src: str = "local", conf: dict | None = None):
        """자동 태그 교체. rejected·manual 중복은 자동 제외(§6). 상한 판정은 파이프라인(§5.6) 소관."""
        tags = normalize_tags(tags)
        k = self._key(path)
        v = self._dictify(k)
        block = {t.lower() for t in (v.get("rejected") or [])}
        block |= {t.lower() for t in (v.get("manual") or [])}
        tags = [t for t in tags if t.lower() not in block]
        if tags:
            v["auto"] = tags
            if conf:
                v["auto_conf"] = {t: round(float(conf[t]), 4)
                                  for t in tags if t in conf}
            else:
                v.pop("auto_conf", None)
            v["auto_at"] = int(time.time())
            v["auto_src"] = src
        else:
            for f in ("auto", "auto_conf", "auto_at", "auto_src"):
                v.pop(f, None)
        self._collapse(k)
        self._save()

    def reject(self, path, tags):
        """사용자가 뺀 자동 태그 — rejected 에 영구 기록 + auto 에서 제거(§1-⑤)."""
        tags = normalize_tags(tags)
        if not tags:
            return
        k = self._key(path)
        v = self._dictify(k)
        rej = v.get("rejected") or []
        low = {t.lower() for t in rej}
        rej += [t for t in tags if t.lower() not in low]
        v["rejected"] = rej
        drop = {t.lower() for t in tags}
        v["auto"] = [t for t in (v.get("auto") or []) if t.lower() not in drop]
        if v.get("auto_conf"):
            v["auto_conf"] = {t: c for t, c in v["auto_conf"].items()
                              if t.lower() not in drop}
        if not v["auto"]:
            for f in ("auto", "auto_conf", "auto_at", "auto_src"):
                v.pop(f, None)
        self._save()

    def promote(self, path, tags):
        """자동 → 수동 승격(§8.1 📌). 이후 재계산이 건드리지 못한다."""
        tags = normalize_tags(tags)
        k = self._key(path)
        v = self._data.get(k)
        if not isinstance(v, dict):
            return
        auto_low = {t.lower(): t for t in (v.get("auto") or [])}
        man = v.get("manual") or []
        man_low = {t.lower() for t in man}
        moved = []
        for t in tags:
            tl = t.lower()
            if tl in auto_low and tl not in man_low:
                man.append(auto_low[tl])
                moved.append(tl)
        if not moved:
            return
        v["manual"] = man
        v["auto"] = [t for t in (v.get("auto") or []) if t.lower() not in moved]
        if v.get("auto_conf"):
            v["auto_conf"] = {t: c for t, c in v["auto_conf"].items()
                              if t.lower() not in moved}
        self._save()

    def clear_auto(self, paths=None):
        """자동 태그 일괄 삭제(None=전체). manual 무손실(§8.5)."""
        keys = ([self._key(p) for p in paths] if paths is not None
                else list(self._data.keys()))
        with self.bulk():
            for k in keys:
                v = self._data.get(k)
                if isinstance(v, dict):
                    for f in ("auto", "auto_conf", "auto_at", "auto_src"):
                        v.pop(f, None)
                    self._collapse(k)
            self._dirty = True

    def clear_auto_tag(self, tag: str):
        """특정 태그의 자동 부여만 전 파일에서 회수(§8.5 — 한 태그가 잘못 퍼졌을 때)."""
        tl = (tag or "").lower()
        if not tl:
            return
        with self.bulk():
            for k, v in list(self._data.items()):
                if isinstance(v, dict) and v.get("auto"):
                    v["auto"] = [t for t in v["auto"] if t.lower() != tl]
                    if v.get("auto_conf"):
                        v["auto_conf"] = {t: c for t, c in v["auto_conf"].items()
                                          if t.lower() != tl}
                    if not v["auto"]:
                        for f in ("auto", "auto_conf", "auto_at", "auto_src"):
                            v.pop(f, None)
                    self._collapse(k)
            self._dirty = True

    # ── 태그 통계 ─────────────────────────────────────────────────────────
    def tag_counts(self) -> dict:
        """{태그: 파일 수} — manual+auto 합집합 기준. 연도는 태그가 아니므로 불포함(§3.6).
        `#` 풀다운의 개수 표시용(검색 SOT §5.1)."""
        cnt = {}
        for k in self._data:
            for t in self.get(k):
                cnt[t] = cnt.get(t, 0) + 1
        return cnt

    def all_tags(self) -> list:
        """등록된 모든 태그(사용 빈도 내림차순 → 이름순). v1 과 같은 계약."""
        cnt = self.tag_counts()
        return sorted(cnt, key=lambda t: (-cnt[t], t.lower()))

    # ── 키워드 (§9) ───────────────────────────────────────────────────────
    def get_keywords(self, path) -> list:
        v = self._data.get(self._key(path))
        if isinstance(v, dict):
            return list(v.get("keywords") or [])
        return []

    def kw_edited(self, path) -> bool:
        v = self._data.get(self._key(path))
        return bool(isinstance(v, dict) and v.get("kw_edited"))

    def set_keywords(self, path, kws, src: str = "local", edited: bool | None = None):
        """키워드 저장(최대 10, §9.1). edited=True 면 이후 자동 재생성이 덮어쓰지 않는다
        — 그 판단(건너뛰기)은 파이프라인이 kw_edited() 로 한다."""
        kws = [str(w).strip() for w in (kws or []) if str(w).strip()]
        seen, out = set(), []
        for w in kws:
            if w.lower() not in seen:
                seen.add(w.lower())
                out.append(w)
        out = out[:MAX_KEYWORDS]
        k = self._key(path)
        v = self._dictify(k)
        if out:
            v["keywords"] = out
            v["kw_at"] = int(time.time())
            v["kw_src"] = src
        else:
            for f in ("keywords", "kw_at", "kw_src"):
                v.pop(f, None)
        if edited is not None:
            if edited:
                v["kw_edited"] = True
            else:
                v.pop("kw_edited", None)
        self._collapse(k)
        self._save()

    # ── 작성연도 (§9.4 — 태그가 아니다) ───────────────────────────────────
    def get_year(self, path):
        v = self._data.get(self._key(path))
        if isinstance(v, dict):
            return v.get("year")
        return None

    def get_year_info(self, path) -> tuple:
        v = self._data.get(self._key(path))
        if isinstance(v, dict) and v.get("year"):
            return v.get("year"), v.get("year_src", ""), v.get("year_conf", 0.0)
        return None, "", 0.0

    def set_year(self, path, year, src: str = "", conf: float = 0.0):
        k = self._key(path)
        v = self._dictify(k)
        if year:
            v["year"] = int(year)
            v["year_src"] = src
            v["year_conf"] = round(float(conf), 2)
        else:
            for f in ("year", "year_src", "year_conf"):
                v.pop(f, None)
        self._collapse(k)
        self._save()

    # ── 지문 · 파일 이동 내성 (§6.1) ──────────────────────────────────────
    @staticmethod
    def _fp_of(path, force_h64: bool = False) -> tuple:
        """(지문 문자열, size). `id:`=PDF /ID[0], `h64:`=size+앞 64KB SHA-1.
        /ID 는 유일하다고 가정하면 안 된다(분할 형제 공유 가능) — 충돌 처리는 호출부."""
        p = Path(path)
        size = p.stat().st_size
        if not force_h64:
            try:
                import fitz                      # 지연 임포트 — 스토어는 표준lib 유지
                d = fitz.open(str(p))
                try:
                    t, val = d.xref_get_key(-1, "ID")
                    m = re.match(r"\[\s*<([0-9A-Fa-f]+)>", val or "")
                    if t == "array" and m and m.group(1):
                        return "id:" + m.group(1).lower(), size
                finally:
                    d.close()
            except Exception:
                pass
        import hashlib
        h = hashlib.sha1()
        with open(p, "rb") as f:
            h.update(f.read(65536))
        return f"h64:{size}:{h.hexdigest()}", size

    def ensure_fp(self, path) -> str | None:
        """항목의 지문을 계산·저장(이미 있으면 재사용 — §7 재계산 없음).
        ★ `id:` 가 다른 항목과 충돌하면 양쪽 다 `h64:` 로 강등(§6.1 가드 ②)."""
        k = self._key(path)
        if k not in self._data:
            return None
        v = self._dictify(k)
        if v.get("fp"):
            return v["fp"]
        try:
            fp, size = self._fp_of(k)
        except Exception:
            return None
        if fp.startswith("id:"):
            clash = [ok for ok, ov in self._data.items()
                     if ok != k and isinstance(ov, dict) and ov.get("fp") == fp]
            if clash:
                fp, size = self._fp_of(k, force_h64=True)
                for ok in clash:                     # 기존 충돌 항목도 강등(파일 있을 때만)
                    try:
                        nfp, nsz = self._fp_of(ok, force_h64=True)
                        self._data[ok]["fp"] = nfp
                        self._data[ok]["size"] = nsz
                    except Exception:
                        pass
        v["fp"] = fp
        v["size"] = size
        self._save()
        return fp

    def set_fp(self, path, fp: str, size: int):
        """워커가 계산한 지문을 채워 넣기(§6.1 — UI 스레드에서 저장만). 항목 없으면 무시."""
        k = self._key(path)
        if k in self._data and fp:
            v = self._dictify(k)
            v["fp"] = fp
            v["size"] = int(size or 0)
            self._save()

    def auto_tag_set(self) -> list:
        """자동 부여된 태그의 어휘(§8.5 '이 태그의 자동 부여만 취소' 메뉴용) — 빈도 내림차순."""
        cnt = {}
        for v in self._data.values():
            if isinstance(v, dict):
                for t in (v.get("auto") or []):
                    cnt[t] = cnt.get(t, 0) + 1
        return sorted(cnt, key=lambda t: (-cnt[t], t.lower()))

    def rehome_missing(self, new_path, fp: str | None = None,
                       size: int | None = None) -> str:
        """§6.1 재연결 절차. 반환: 'exists'(경로 적중=비용 0) / 'moved'(이사 — 태그 따라감)
        / 'copy'(복사본 — 상속 안 함) / 'new'(모름) / 'ambiguous'(지문 충돌 — 안전하게 포기).
        `fp`/`size` 를 주면 지문 계산을 건너뛴다(워커가 미리 계산 — UI 스레드 무봉쇄)."""
        k_new = self._key(new_path)
        if k_new in self._data:
            return "exists"                          # ① 경로 적중 — 지문 계산 없음
        try:
            if fp is None:
                fp, size = self._fp_of(new_path)     # ② 빗나감 — 이때만 지문 계산
        except Exception:
            return "new"

        def _match(f):
            return [k for k, v in self._data.items()
                    if isinstance(v, dict) and v.get("fp") == f]

        matches = _match(fp)
        if fp.startswith("id:"):
            if len(matches) > 1:
                # 저장된 id 중복(분할 형제 등) — 파일이 남은 항목은 h64 로 강등(가드 ②)
                for ok in list(matches):
                    try:
                        nfp, nsz = self._fp_of(ok, force_h64=True)
                        self._data[ok]["fp"] = nfp
                        self._data[ok]["size"] = nsz
                    except Exception:
                        pass                         # 파일 소실분은 id 로 남는다
                matches = _match(fp)
            if len(matches) != 1:
                # ★ id 로 못 찾음 — 저장 쪽이 이미 h64 로 강등돼 있을 수 있다(등록 시
                #   가드 ② 이후의 정상 상태). h64 로 2차 조회해야 태그가 유실되지 않는다.
                fp2, size2 = self._fp_of(new_path, force_h64=True)
                m2 = _match(fp2)
                if len(m2) == 1:
                    matches, fp, size = m2, fp2, size2
                elif len(m2) > 1:
                    return "ambiguous"
                else:
                    return "ambiguous" if len(matches) > 1 else "new"
        if len(matches) > 1:
            return "ambiguous"                       # ★ 잘못 잇기 > 못 잇기 — 포기
        if not matches:
            return "new"                             # ⑤ 새 파일
        old = matches[0]
        if os.path.exists(old):
            return "copy"                            # ④ 복사본 — 상속 금지(조용한 복제)
        v = self._data.pop(old)                      # ③ 이사 — 키 이동, 옛 항목 삭제
        v["fp"] = fp
        v["size"] = size
        self._data[k_new] = v
        self._save()
        return "moved"

    def rehome(self, old_path, new_path):
        """앱이 직접 옮긴 경우(§8.6 폴더 정리) — 지문 계산 없이 키만 이동."""
        ko, kn = self._key(old_path), self._key(new_path)
        if ko in self._data and kn not in self._data:
            self._data[kn] = self._data.pop(ko)
            self._save()

    # ── 고아 항목 (§6.1 삭제·복원 — 앱이 임의로 지우지 않는다) ─────────────
    def count_missing(self) -> int:
        return sum(1 for k in self._data if not os.path.exists(k))

    def prune_missing(self) -> int:
        """없는 파일 항목 정리 — ★ 사용자 확인 후에만 호출할 것(§8.5)."""
        gone = [k for k in self._data if not os.path.exists(k)]
        for k in gone:
            self._data.pop(k, None)
        if gone:
            self._save()
        return len(gone)


# ── 신규 태그 후보 적립(§5.4-5·§8.5) — 파일 단위가 아니라 전역이라 별도 파일 ──
def _candidates_path() -> Path:
    try:
        from viewer.settings_store import settings_dir
        return Path(settings_dir()) / "tag_candidates.json"
    except Exception:
        return Path.home() / ".polypdf_tag_candidates.json"


def load_candidates(path=None) -> dict:
    """{"cand": {태그: {"n": 건수, "files": [예시…]}}, "rejected": [태그…]}"""
    p = Path(path) if path else _candidates_path()
    try:
        d = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        d = {}
    d.setdefault("cand", {})
    d.setdefault("rejected", [])
    return d


def save_candidates(data: dict, path=None):
    p = Path(path) if path else _candidates_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0),
                       encoding="utf-8")
        os.replace(tmp, p)                       # 원자적(§6)
    except Exception:
        pass


def merge_candidates(new_items: dict, path=None) -> dict:
    """워커가 모은 신규 후보를 적립 파일에 병합(전역 rejected 는 재적립 금지)."""
    data = load_candidates(path)
    rej = {t.lower() for t in data["rejected"]}
    for tag, info in (new_items or {}).items():
        if tag.lower() in rej:
            continue
        cur = data["cand"].setdefault(tag, {"n": 0, "files": []})
        cur["n"] = int(cur.get("n", 0)) + int(info.get("n", 1))
        for f in info.get("files", []):
            if f not in cur["files"]:
                cur["files"] = (cur["files"] + [f])[:8]
    save_candidates(data, path)
    return data
