# -*- coding: utf-8 -*-
"""PDF 정보 한 줄·문서 정보 창의 값 (마스터 SOT §4.12, 261107-3).

- 메인 스레드는 **열린 문서에서 이미 아는 값만** 쓴다 — 이름·쪽 수·지금 쪽 크기·암호(`main_facts`).
- 파일 크기·서명·글자층·메타 정보는 `DocInfoWorker` 가 파일을 따로 열어 배경에서 읽는다(응답성 SOT §4.4 표).
- 화면 글은 `tr()`, 값(제목·작성자 …)은 그대로.
"""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from viewer.i18n import tr

PT_PER_MM = 72.0 / 25.4
PAPER_TOL = 0.015                 # 표준 용지로 볼 차이(긴 변·짧은 변 각각 1.5% 안)
# 표준 용지(mm, 짧은 변 × 긴 변) — 정보 줄의 '지금 쪽 용지' 이름. B 판은 한국·일본에서 흔한 JIS 판.
PAPERS = (
    ("A4", 210.0, 297.0), ("A3", 297.0, 420.0), ("A5", 148.0, 210.0),
    ("B4", 257.0, 364.0), ("B5", 182.0, 257.0),
    ("Letter", 215.9, 279.4), ("Legal", 215.9, 355.6),
)
SEP = "  ·  "                     # 사진 정보 줄(`photo_controller.photo_info_line`)과 같은 구분
CACHE_MAX = 64


def paper_name(w_pt: float, h_pt: float) -> str:
    """쪽 크기(pt, 회전 뒤 보이는 방향) → 'A4 세로' · 'Letter 가로' · 아니면 '210 × 297 mm'."""
    try:
        w, h = float(w_pt) / PT_PER_MM, float(h_pt) / PT_PER_MM
    except (TypeError, ValueError):
        return ""
    if w <= 0 or h <= 0:
        return ""
    s, l = min(w, h), max(w, h)
    orient = tr("세로") if h >= w else tr("가로")
    for name, ps, pl in PAPERS:
        if abs(s - ps) <= ps * PAPER_TOL and abs(l - pl) <= pl * PAPER_TOL:
            return "%s %s" % (name, orient)
    return "%d × %d mm" % (round(w), round(h))


def fmt_bytes(n: int) -> str:
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, round(n / 1024.0))


def fmt_pdf_date(s: str) -> str:
    """PDF 날짜 'D:20240102123456+09'00'' → '2024-01-02 12:34'. 모르는 꼴은 그대로."""
    s = (s or "").strip()
    if s.startswith("D:"):
        s = s[2:]
    if len(s) >= 12 and s[:12].isdigit():
        return "%s-%s-%s %s:%s" % (s[0:4], s[4:6], s[6:8], s[8:10], s[10:12])
    if len(s) >= 8 and s[:8].isdigit():
        return "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])
    return s


def main_facts(doc, page_index: int) -> dict:
    """열린 `PdfDocument` 에서 이미 아는 값 — 메인 스레드에서 부른다(파일을 다시 열지 않는다)."""
    out = {"name": doc.path.name, "path": str(doc.path), "pages": int(doc.page_count)}
    fz = doc.doc
    try:
        out["encrypted"] = bool(fz.is_encrypted) or bool((fz.metadata or {}).get("encryption"))
    except Exception:
        out["encrypted"] = False
    try:
        r = fz.load_page(max(0, min(out["pages"] - 1, int(page_index)))).rect
        out["paper"] = paper_name(r.width, r.height)
    except Exception:
        out["paper"] = ""
    return out


def _scan_word(info: dict) -> str:
    n_no = int(info.get("pages_no_text") or 0)
    if n_no <= 0:
        return ""
    return tr("스캔") if n_no >= int(info.get("pages_checked") or 0) else tr("스캔 일부")


def doc_info_line(facts: dict, info: dict | None = None) -> str:
    """정보 한 줄 — 파일 이름 · N쪽 · 지금 쪽 용지 · 파일 크기 · (있으면) 암호 · 서명 · 스캔."""
    info = info or {}
    parts = [facts.get("name") or ""]
    if facts.get("pages"):
        parts.append(tr("{n}쪽").format(n=facts["pages"]))
    if facts.get("paper"):
        parts.append(facts["paper"])
    if info.get("bytes"):
        parts.append(fmt_bytes(info["bytes"]))
    if facts.get("encrypted") or info.get("encrypted"):
        parts.append(tr("암호"))
    if info.get("signed"):
        parts.append(tr("서명"))
    sw = _scan_word(info)
    if sw:
        parts.append(sw)
    return SEP.join(p for p in parts if p)


def doc_info_rows(facts: dict, info: dict | None) -> list:
    """문서 정보 창의 (항목, 값). 배경 값이 아직이면(info None) 그 행은 '읽는 중…'."""
    wait = tr("읽는 중…")
    none = "—"

    def bg(key, fmt=str):
        if info is None:
            return wait
        v = info.get(key)
        return fmt(v) if v not in (None, "", []) else none

    meta = (info or {}).get("meta") or {}

    def mv(key, fmt=str):
        if info is None:
            return wait
        v = (meta.get(key) or "").strip()
        return fmt(v) if v else none

    def yes_no(v):
        return tr("있음") if v else tr("없음")

    perm = (info or {}).get("perm")
    if info is None:
        perm_s = wait
    elif not perm:
        perm_s = none
    else:
        names = (("print", tr("인쇄")), ("copy", tr("복사")), ("modify", tr("고치기")), ("annotate", tr("주석")))
        perm_s = " · ".join("%s %s" % (lab, "○" if perm.get(k) else "×") for k, lab in names)
    if info is None:
        text_s = wait
    elif info.get("pages_checked"):
        n_all = int(info["pages_checked"])
        n_no = int(info.get("pages_no_text") or 0)
        text_s = tr("있는 쪽 {a} · 없는 쪽 {b}").format(a=n_all - n_no, b=n_no)
    else:
        text_s = none
    return [
        (tr("파일"), facts.get("path") or ""),
        (tr("파일 크기"), bg("bytes", fmt_bytes)),
        (tr("쪽 수"), str(facts.get("pages") or none)),
        (tr("지금 쪽 용지"), facts.get("paper") or none),
        (tr("제목"), mv("title")),
        (tr("작성자"), mv("author")),
        (tr("주제"), mv("subject")),
        (tr("키워드"), mv("keywords")),
        (tr("만든 프로그램"), mv("creator")),
        (tr("PDF 변환기"), mv("producer")),
        (tr("만든 날짜"), mv("creationDate", fmt_pdf_date)),
        (tr("고친 날짜"), mv("modDate", fmt_pdf_date)),
        (tr("PDF 판"), mv("format")),
        (tr("암호"), yes_no(facts.get("encrypted") or (info or {}).get("encrypted"))),
        (tr("권한"), perm_s),
        (tr("서명"), wait if info is None else yes_no(info.get("signed"))),
        (tr("글자층"), text_s),
        (tr("책갈피 수"), bg("toc", str) if (info is None or info.get("toc")) else "0"),
        (tr("첨부 수"), bg("attach", str) if (info is None or info.get("attach")) else "0"),
    ]


# ── 배경 읽기 ───────────────────────────────────────────────────────────
_CACHE: dict = {}
_LOCK = threading.Lock()


def _cache_key(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)


def cached(path: str):
    """메인 스레드용 — 캐시만 본다(파일을 열지도 stat 하지도 않는다: 가장 최근 값)."""
    k = os.path.normcase(os.path.abspath(str(path)))
    with _LOCK:
        for key, val in reversed(list(_CACHE.items())):
            if key[0] == k:
                return val
    return None


def read_info(path: str, password: str | None = None, cancelled=lambda: False, pace=None) -> dict:
    """파일을 따로 열어 문서 정보 창의 값을 모은다 — **배경 스레드에서만**. 같은 크기·수정 시각이면 캐시."""
    key = _cache_key(path)
    if key is not None:
        with _LOCK:
            hit = _CACHE.get(key)
        if hit is not None:
            return hit
    out: dict = {"bytes": key[1] if key else 0}
    try:
        import fitz
        d = fitz.open(str(path))
    except Exception:
        return out
    try:
        out["encrypted"] = bool(d.is_encrypted) or bool(d.needs_pass)
        if d.needs_pass and not (password and d.authenticate(password)):
            return out                              # 열 수 없다 — 크기·암호만
        out["meta"] = dict(d.metadata or {})
        try:
            p = int(d.permissions)
            out["perm"] = {"print": bool(p & fitz.PDF_PERM_PRINT), "copy": bool(p & fitz.PDF_PERM_COPY),
                           "modify": bool(p & fitz.PDF_PERM_MODIFY), "annotate": bool(p & fitz.PDF_PERM_ANNOTATE)}
        except Exception:
            pass
        try:
            out["toc"] = len(d.get_toc(simple=True) or [])
        except Exception:
            out["toc"] = 0
        try:
            out["attach"] = int(d.embfile_count())
        except Exception:
            out["attach"] = 0
        try:
            from viewer.sign_core import doc_is_signed
            out["signed"] = bool(doc_is_signed(d))
        except Exception:
            out["signed"] = False
        from viewer.text_extract2 import has_text_layer     # 쪽 판정은 단어학습 SOT §14.18 그대로
        n_no = 0
        for i in range(d.page_count):
            if cancelled():
                return out                          # 덜 읽은 것은 캐시에 넣지 않는다
            if not has_text_layer(d, i):
                n_no += 1
            if pace is not None:
                pace()
        out["pages_checked"] = d.page_count
        out["pages_no_text"] = n_no
    finally:
        try:
            d.close()
        except Exception:
            pass
    if key is not None:
        with _LOCK:
            _CACHE[key] = out
            while len(_CACHE) > CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
    return out


class DocInfoWorker(QObject):
    """PDF 문서 정보를 배경에서 읽는다 — 응답성 SOT §4.4 감사표의 한 행."""
    done = pyqtSignal(int, int, str, dict)        # 세대, 창 번호, 경로, 값
    finished = pyqtSignal()

    def __init__(self, gen: int, pane: int, path: str, password: str | None = None):
        super().__init__()
        self.gen, self.pane, self.path, self.password = gen, pane, path, password
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            from viewer import pacing
            pw = self.password
            if pw is None:
                try:
                    from viewer import secure_store            # 이번 실행에서 연 암호(키를 만들며 stat 한다 — 그래서 배경에서)
                    pw = secure_store.get_session(self.path)
                except Exception:
                    pw = None
            info = read_info(self.path, pw, cancelled=lambda: self._cancel,
                             pace=lambda: pacing.pace(self))
            if not self._cancel:
                self.done.emit(self.gen, self.pane, self.path, info)
        except Exception:
            pass
        finally:
            self.finished.emit()
