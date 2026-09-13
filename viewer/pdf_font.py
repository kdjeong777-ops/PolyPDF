# -*- coding: utf-8 -*-
"""260913-5: 글꼴을 넣어 저장하는 PDF 의 글꼴 규칙 (마스터 SOT §4.5.10·§4.5.11).

① 저장 직전 `subset_fonts_safely(doc)` — 글꼴 **전체**(맑은 고딕 13MB)가 아니라 쓴 글자만 담는다.
② 글을 적기 전 `fresh_font_name(page, 기본이름)` — `Page.insert_font` 는 그 쪽에 **같은 이름의
   글꼴이 있으면 재사용**한다. 한 번 저장한 쪽의 글꼴은 이미 부분집합(`ABCDEF+…`)이라, 그 이름으로
   새 글자를 적으면 모양이 깨지고 추출·검색에서 빠진다. 그런 이름은 비켜 간다.
③ 260913-7(§4.5.11): 글쓰기 글꼴은 **맑은 고딕 하나**(`TEXT_FAMILY`·`text_font_file()`).
   굵게·기울임은 같은 글꼴로 흉내 낸다(`insert_textbox_styled`) — 글꼴 파일이 늘지 않는다.

쓰는 곳: `edit_controller`(krfont) · `text_apply`(krfix) · `twoup`(krf/pnf, ① 만) ·
`screenshot`(krhdr).
"""
from __future__ import annotations

import os
import re

_SUBSET_TAG = re.compile(r"^[A-Z]{6}\+")

# 260913-7(§4.5.11): 글쓰기·스크린샷 머리말의 글꼴은 이것 하나.
TEXT_FAMILY = "맑은 고딕"
_TEXT_FONT_FILES = (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
                    r"C:\Windows\Fonts\batang.ttc", r"C:\Windows\Fonts\NanumGothic.ttf")
BOLD_STROKE = 0.05      # 굵게 흉내 — 외곽선 굵기(글자 크기 대비)
ITALIC_SKEW = 0.21      # 기울임 흉내 — tan(≈12°)


def text_font_file():
    """맑은 고딕 파일 경로. 없으면 한글이 되는 다음 후보, 그것도 없으면 None."""
    for p in _TEXT_FONT_FILES:
        if os.path.exists(p):
            return p
    return None


def subset_fonts_safely(doc) -> bool:
    """쓴 글자만 남긴다. 실패해도 저장은 해야 하므로 예외를 삼키고 False.
    (PyMuPDF 1.23 의 `subset_fonts` 는 fontTools 가 필요하다 — 1.24+ 는 MuPDF 자체 기능.)"""
    try:
        doc.subset_fonts()
        return True
    except Exception:                            # noqa: BLE001
        return False


def fresh_font_name(page, base: str) -> str:
    """이 쪽에 새 글자를 적을 때 쓸 글꼴 이름.

    같은 이름이 없거나, 있어도 **부분집합이 아니면**(같은 저장 안에서 방금 넣은 전체 글꼴)
    `base` 그대로. 부분집합 표시가 붙은 같은 이름이면 `base2`, `base3`… 으로 비켜 간다."""
    try:
        used = {f[4]: (f[3] or "") for f in page.get_fonts()}
    except Exception:                            # noqa: BLE001
        return base
    name, n = base, 1
    while name in used and _SUBSET_TAG.match(used[name]):
        n += 1
        name = f"{base}{n}"
    return name


def insert_textbox_styled(fitz, page, rect, text, *, bold=False, italic=False, **kw) -> float:
    """`page.insert_textbox` + 굵게·기울임 흉내 (§4.5.11). 반환값은 `insert_textbox` 와 같다.

    - 굵게: 외곽선(`render_mode=2`)을 글자색으로 얹는다.
    - 기울임: 박스 전체에 `morph` 를 걸면 윗줄·아랫줄이 옆으로 밀린다. 그래서 빈 쪽에 **같은
      글을 한 번 배치**해 조각마다 기준점을 얻고, 실제 쪽에는 조각마다 그 점으로 기울여 적는다.
      행렬 부호는 `+k` 가 오른쪽으로 기운다(`-k` 는 거꾸로 — 실측)."""
    if bold:
        col = kw.get("color") or (0, 0, 0)
        kw.update(render_mode=2, border_width=BOLD_STROKE, fill=col, color=col)
    if not italic:
        return page.insert_textbox(rect, text, **kw)
    lay = {k: v for k, v in kw.items() if k in ("fontsize", "fontfile", "fontname", "align")}
    tmp = fitz.open()
    try:
        tp = tmp.new_page(width=page.rect.width, height=page.rect.height)
        rc = tp.insert_textbox(rect, text, **lay)
        if rc < 0:
            return rc
        spans = [(s["origin"], s["text"]) for b in tp.get_text("dict")["blocks"]
                 for ln in b.get("lines", []) for s in ln["spans"] if s["text"].strip()]
    finally:
        tmp.close()
    kw.pop("align", None)
    skew = fitz.Matrix(1, 0, ITALIC_SKEW, 1, 0, 0)
    for (ox, oy), t in spans:
        p = fitz.Point(ox, oy)
        page.insert_text(p, t, morph=(p, skew), **kw)
    return rc
