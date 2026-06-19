"""책갈피(Bookmark)를 PDF에 직접 임베드해 저장한다.

외부 PDF 편집기를 거치지 않고도 책갈피가 적용된 PDF를 바로 만들 수 있다.
스펙(개발지시서 §3) 의 고정 속성:
  - color  = Black (0,0,0)
  - bold   = True
  - italic = False
  - open   = True
  - fit    = FitPage  (= pypdf Fit.fit())
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter
from pypdf.generic import Fit

from .core import Bookmark


def apply_bookmarks_to_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    bookmarks: Iterable[Bookmark],
    *,
    clear_existing: bool = True,
    bold: bool = True,
    italic: bool = False,
    is_open: bool = True,
    color: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Path:
    """`input_pdf` 를 읽어 책갈피를 임베드하고 `output_pdf` 에 저장한다.

    Parameters
    ----------
    input_pdf : 원본 PDF 경로
    output_pdf : 저장할 PDF 경로 (덮어쓰기)
    bookmarks : Bookmark 리스트. level 은 트리 깊이(0=최상위)
    clear_existing : True면 기존 책갈피를 모두 지우고 새로 작성 (기본). False면 추가
    bold/italic/is_open/color : 책갈피 외관 — 스펙 기본값 사용

    Returns
    -------
    저장된 출력 PDF의 Path

    Raises
    ------
    FileNotFoundError : input_pdf 가 없을 때
    ValueError       : 책갈피의 페이지가 PDF 페이지 범위를 벗어날 때
    """
    in_path = Path(input_pdf)
    out_path = Path(output_pdf)
    if not in_path.exists():
        raise FileNotFoundError(in_path)

    reader = PdfReader(str(in_path))
    writer = PdfWriter(clone_from=reader)
    total_pages = len(writer.pages)

    if clear_existing:
        # 기존 outline 제거 — clone_from 으로 복제된 outline 을 비운다
        writer._root_object[writer._root_object.raw_get("/Outlines")] if False else None
        # pypdf 공개 API: outline 리스트 자체를 비운다
        try:
            writer._outline.clear()  # type: ignore[attr-defined]
        except Exception:
            pass
        # Catalog 의 /Outlines 가 남아있으면 제거 (clone_from 가 가져왔을 때)
        from pypdf.generic import NameObject  # 지역 import — 헤더 정리 목적
        if NameObject("/Outlines") in writer._root_object:
            del writer._root_object[NameObject("/Outlines")]

    fit_page = Fit.fit()  # FitPage

    # stack[i] = level i 의 가장 최근 outline item (level i+1 의 부모로 사용)
    stack: list = []
    for bm in bookmarks:
        if bm.page < 1 or bm.page > total_pages:
            raise ValueError(
                f"책갈피 페이지 {bm.page} 가 PDF 범위(1~{total_pages})를 벗어남: {bm.title!r}"
            )
        # 슬래시 치환을 환원: 우리 포맷에서는 '/'를 '／' 로 바꾸지만,
        # PDF outline 의 title 에는 원래 글자(/)로 두는 게 자연스럽다.
        title = bm.title.replace("／", "/")

        parent = stack[bm.level - 1] if bm.level > 0 and len(stack) >= bm.level else None
        item = writer.add_outline_item(
            title=title,
            page_number=bm.page - 1,  # 0-based
            parent=parent,
            color=color,
            bold=bold,
            italic=italic,
            fit=fit_page,
            is_open=is_open,
        )
        # stack 을 현재 level 까지 자르고 새 item을 그 자리에 둔다
        del stack[bm.level:]
        stack.append(item)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path
