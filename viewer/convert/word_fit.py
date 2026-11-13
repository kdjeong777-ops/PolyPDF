# -*- coding: utf-8 -*-
"""Word 변환(pdf2docx)에 거는 걸이 — 줄 잇기·쪽 맞춤·글꼴 (형식 변환 SOT §1.2·§4.1 고침 8, 261113-3).

부모(`proc.convert_docx`)는 `page_plan` 으로 쪽마다 줄 잇기 계획을 만들어 일감에 싣고, 자식(`proc.serve`)은 `Hook(계획)` 을
`_vendor/pdf2docx/polypdf_fit.HOOK` 에 건다. pdf2docx 쪽 코드는 이 걸이만 부른다(앱을 직접 import 하지 않는다).
"""
from __future__ import annotations

import re

from viewer.convert import layout

MARGIN_SETTINGS = {"page_margin_factor_top": 1.0, "page_margin_factor_bottom": 1.0}   # §1.2 'Word 쪽 여백'
BOLD_K = 1.04      # 굵은 글자는 보통 글꼴 파일로 잰 너비보다 넓다(재는 글꼴 파일은 보통 굵기 하나)
WIDTH_MARGIN = 1.10  # §1.2 'Word 너비 여유' — 문단 너비 어림·낱말 단위 줄 바꿈 몫(별첨4 검토: 1.05 → 47쪽, 1.10 → 43쪽)
BEFORE_K = 0.9     # §1.2 'Word 문단 위 간격' — 표 칸 밖 글 문단의 위 간격 배율(사용자 결정 B 안)


# ---- 부모: 쪽마다 줄 잇기 계획 ----------------------------------------------------
def page_plan(ps, pg) -> list:
    """편집 가능 — 텍스트 창이 이은 줄의 **이어지는** 원본 줄 상자(마지막 줄 빼고)와 그 뒤에 넣을 사이 글(`" "` 또는 `""`).
    반환 `[[x0, y0, x1, y1, 사이], …]`."""
    try:
        joined = ps.lines(pg, tables="omit", join=True)
        plain = ps.lines(pg, tables="omit", join=False)
    except Exception:
        return []
    text_of = {}
    for r in plain:
        if r.get("rect"):
            text_of[tuple(round(v, 1) for v in r["rect"])] = str(r.get("text", ""))
    out = []
    for r in joined:
        rects = [tuple(x) for x in (r.get("rects") or [])]
        if len(rects) < 2:
            continue
        whole = re.sub(r"\s+", " ", str(r.get("text", "")))
        for a, b in zip(rects, rects[1:]):
            ta = text_of.get(tuple(round(v, 1) for v in a), "").rstrip()
            tb = text_of.get(tuple(round(v, 1) for v in b), "").lstrip()
            sep = ""
            if ta and tb and (ta[-8:] + " " + tb[:8]) in whole:
                sep = " "
            out.append([float(a[0]), float(a[1]), float(a[2]), float(a[3]), sep])
    return out


# ---- 자식: 글꼴 ---------------------------------------------------------------
_STYLE = re.compile(r"(bold|italic|oblique|regular|semibold|light|black|heavy|condensed|,b|,i|,bi|psmt|mt|ps)+$")


def _norm(name: str) -> str:
    n = re.sub(r"^[A-Z]{6}\+", "", str(name or ""))          # 묶음 글꼴 접두어 ABCDEF+
    return re.sub(r"[\s\-_]+", "", n).lower()


_INSTALLED = None


def installed_fonts() -> dict:
    """정규화한 글꼴 이름 → Word 에 넣을 이름(레지스트리 글꼴 목록, 굵기 낱말 뺀 갈래 이름). 한 번만 읽는다."""
    global _INSTALLED
    if _INSTALLED is not None:
        return _INSTALLED
    out = {}
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                k = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    raw = winreg.EnumValue(k, i)[0]
                except OSError:
                    break
                i += 1
                base = re.sub(r"\s*\((TrueType|OpenType|All res)\)\s*$", "", raw, flags=re.I)
                for fam in base.split("&"):
                    fam = fam.strip()
                    if not fam:
                        continue
                    plain = re.sub(r"\s+(Bold|Italic|Oblique|Regular|Bold Italic|Semibold|Light)(\s+(Italic|Bold))*$", "",
                                   fam, flags=re.I).strip() or fam
                    for key in (_norm(fam), _norm(plain)):
                        out.setdefault(key, plain)
    except Exception:
        pass
    _INSTALLED = out
    return out


def resolve_font(name: str, flags: int = 0) -> tuple:
    """원본 글꼴 → (Word 에 넣을 이름, 설치됨). 설치 안 된 글꼴은 바탕 / 맑은 고딕(§1.2 '글꼴(Word)')."""
    inst = installed_fonts()
    n = _norm(name)
    for key in (n, _STYLE.sub("", n)):
        if key and key in inst:
            return inst[key], True
    _bold, serif = layout.font_kind(name, flags)
    return (layout.SERIF_FACE if serif else layout.SANS_FACE), False


# ---- 자식: 걸이 -----------------------------------------------------------------
class Hook:
    """`_vendor/pdf2docx/polypdf_fit.py` 가 부르는 것 — `plan(쪽 id)`, `font(이름, 플래그)`, `width(…)`, `fit(…)`."""

    def __init__(self, plan: dict | None):
        plan = plan or {}
        self.mode = plan.get("mode", "shape")
        self.pages = {int(k): v for k, v in (plan.get("pages") or {}).items()}

    def plan(self, pid: int) -> dict:
        return {"mode": self.mode, "cont": self.pages.get(int(pid), [])}

    def font(self, name: str, flags: int = 0) -> tuple:
        return resolve_font(name, flags)

    def bold(self, name: str, flags: int = 0) -> bool:
        return layout.font_kind(name, flags)[0]

    def safe(self, text: str) -> str:
        """XML 에 못 넣는 제어 문자 → '�' — 다른 변환(`source.xml_safe`)과 같게."""
        from viewer.convert.source import xml_safe
        return xml_safe(text)

    def width(self, text: str, size: float, name: str, flags: int, orig_w: float) -> float:
        """Word 가 그릴 너비(쪽 맞춤용 어림) — 설치된 글꼴이면 원본 너비, 아니면 바꿔 쓸 글꼴로 잰 너비. 둘 다 × `WIDTH_MARGIN`(§1.2)."""
        face, inst = resolve_font(name, flags)
        if inst:
            return float(orig_w) * WIDTH_MARGIN
        serif = face == layout.SERIF_FACE
        m = layout.measure_fit(text, size, serif)
        if m is None:
            return float(orig_w) * WIDTH_MARGIN
        return float(m) * (BOLD_K if layout.font_kind(name, flags)[0] else 1.0) * WIDTH_MARGIN

    before_k = BEFORE_K

    def fit(self, width, n_rows, avail, size, pitch=None, indent=0.0) -> dict:
        return layout.fit_plan(width, n_rows, avail, size, pitch, indent=indent)
