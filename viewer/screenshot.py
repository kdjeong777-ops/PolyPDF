"""스크린샷 캡처/저장/PDF 일괄 내보내기.

v1.5.0:
 - 파일명 datetime 접두 (YYMMDD_HHMM_) (M5/M8)
 - 2장 보기 시 좌·우 분리 캡처 helper (M3)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import html as _html
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple

import fitz
from PyQt6.QtCore import QRect, QStandardPaths
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget


def _temp_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    p = Path(base) / "screenshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_stem(name: str) -> str:
    s = _INVALID.sub("_", name).strip().strip(".")
    return s or "screenshot"


def datetime_prefix() -> str:
    """YYMMDD_HHMM_ 형태."""
    return _dt.datetime.now().strftime("%y%m%d_%H%M_")


def unique_path(folder: Path, stem: str, ext: str = ".png") -> Path:
    target = folder / f"{stem}{ext}"
    n = 1
    while target.exists():
        target = folder / f"{stem} ({n}){ext}"
        n += 1
    return target


def capture_widget(widget: QWidget) -> QPixmap:
    return widget.grab()


def split_pixmap_horizontally(pix: QPixmap) -> Tuple[QPixmap, QPixmap]:
    """v1.5.0 M3: 가운데를 기준으로 좌·우로 분리 (2장 보기 캡처용)."""
    w = pix.width()
    h = pix.height()
    half = w // 2
    left = pix.copy(QRect(0, 0, half, h))
    right = pix.copy(QRect(half, 0, w - half, h))
    return left, right


def save_screenshot(pixmap: QPixmap, *, source_name: str,
                    folder: Path | None = None,
                    suffix: str = "") -> Path:
    """스크린샷 PNG 저장. 파일명 = 'YYMMDD_HHMM_<stem><suffix>.png'."""
    folder = folder or _temp_dir()
    base_stem = safe_stem(Path(source_name).stem) + suffix
    stem = datetime_prefix() + base_stem      # v1.5.0 M8
    target = unique_path(folder, stem, ".png")
    pixmap.save(str(target), "PNG")
    return target


def render_page_png(src_pdf: str | Path, src_page: int,
                    query: str | None = None,
                    dpi: int = 150,
                    folder: Path | None = None) -> Path:
    """v1.6.5 D2: 원본 PDF 페이지를 형광펜 포함 재렌더 → PNG 경로 반환.

    파일명이 (src_pdf stem, page, query 해시, dpi) 로 결정적이라
    같은 조합이면 기존 파일을 그대로 재사용(재렌더 생략) → ◀▶ 연타에도 빠름.
    """
    folder = Path(folder) if folder else _temp_dir()
    q = query or ""
    qhash = hashlib.md5(q.encode("utf-8")).hexdigest()[:8] if q else "noq"
    stem = safe_stem(Path(str(src_pdf)).stem)
    target = folder / f"_hl_{stem}_{int(src_page)}_{qhash}_{int(dpi)}.png"
    if target.exists():
        return target
    doc = fitz.open(str(src_pdf))
    try:
        pno = max(0, min(doc.page_count - 1, int(src_page)))
        page = doc.load_page(pno)
        if q:
            for r in page.search_for(q):
                page.add_highlight_annot(r)
        zoom = max(0.5, float(dpi) / 72.0)
        pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pm.save(str(target))
        return target
    finally:
        doc.close()


def export_pdf(image_paths: Iterable[str | Path], out_pdf: str | Path) -> Path:
    """이미지 파일 리스트를 한 PDF 로 합쳐 저장. (구버전 호환 — 품질 손실 있음)"""
    out = Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_doc = fitz.open()
    try:
        for img_path in image_paths:
            img_path = str(img_path)
            try:
                pix = fitz.Pixmap(img_path)
            except Exception:
                continue
            page = new_doc.new_page(width=pix.width, height=pix.height)
            page.insert_image(page.rect, filename=img_path)
        new_doc.save(out)
    finally:
        new_doc.close()
    return out


def _overlay_header_footer(page, *, top_text: str | None = None,
                           bottom_text: str | None = None) -> None:
    """v1.6.4: 페이지 상/하단에 흰 배경 + 가운데 텍스트 오버레이.

    한글 파일명 대응을 위해 `insert_textbox`(내장 라틴 폰트) 가 아닌
    `insert_htmlbox`(유니코드 자동 폰트) 를 사용. 실패해도 저장은 계속.
    """
    try:
        R = page.rect
        if top_text:
            band = fitz.Rect(R.x0, R.y0, R.x1, R.y0 + 26)
            page.draw_rect(band, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
            page.insert_htmlbox(
                fitz.Rect(R.x0 + 8, R.y0 + 3, R.x1 - 8, R.y0 + 24),
                f"<div style='text-align:center;font-size:11px;"
                f"font-family:sans-serif'>{_html.escape(top_text)}</div>",
            )
        if bottom_text:
            band = fitz.Rect(R.x0, R.y1 - 24, R.x1, R.y1)
            page.draw_rect(band, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
            page.insert_htmlbox(
                fitz.Rect(R.x0 + 8, R.y1 - 22, R.x1 - 8, R.y1 - 3),
                f"<div style='text-align:center;font-size:10px;"
                f"font-family:sans-serif;color:#444'>{_html.escape(bottom_text)}</div>",
            )
    except Exception:
        pass


def export_pdf_from_meta(meta_list: Iterable[dict], out_pdf: str | Path,
                         *,
                         show_query: bool = False,
                         show_filename: bool = False,
                         show_pageno: bool = False,
                         render_dpi: int = 200) -> Path:
    """v1.6.2: 카드 메타 리스트로부터 PDF 저장. v1.6.4: 옵션 추가.

    각 dict 항목 키:
      - src_pdf (str|None): 원본 PDF 경로.
      - src_page (int|None): 원본 페이지(0-based). src_pdf 있으면 필수.
      - src_query (str|None): 캡처 당시 검색어 (show_query 형광펜 대상, v1.6.4).
      - path (str): 폴백용 PNG 경로 (src_pdf 없거나 못 열 때).
      - kind (str): "image" / "pdf" / etc.

    옵션 (v1.6.4):
      - show_query=False(기본): 원본 페이지를 `insert_pdf()` 로 1:1 복사 →
        벡터·원본 화질, 형광펜 없음 (= v1.6.2 동작).
      - show_query=True: 원본 페이지를 render_dpi 로 재렌더하고 src_query
        매치에 형광펜을 그린 뒤 이미지로 삽입 → 검색어가 보이나 화질 다소 손실.
      - show_filename: 각 페이지 상단에 카드 파일명(stem) 오버레이.
      - show_pageno: 각 페이지 하단에 `i / N` (리스트 순번) 오버레이.
      - src_pdf 없는 항목은 PNG 폴백 (예전과 동일).
    """
    out = Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    metas = list(meta_list)
    total = len(metas)
    new_doc = fitz.open()
    opened: dict = {}                       # 같은 PDF 재오픈 방지 캐시
    try:
        for i, meta in enumerate(metas, start=1):
            src_pdf = meta.get("src_pdf")
            src_page = meta.get("src_page")
            src_query = meta.get("src_query")
            png_path = meta.get("path")
            added = False

            if src_pdf and src_page is not None:
                try:
                    src_doc = opened.get(src_pdf)
                    if src_doc is None:
                        src_doc = fitz.open(src_pdf)
                        opened[src_pdf] = src_doc
                    pno = max(0, min(src_doc.page_count - 1, int(src_page)))
                    if show_query:
                        page = src_doc.load_page(pno)
                        if src_query:
                            for r in page.search_for(src_query):
                                page.add_highlight_annot(r)
                        zoom = max(0.5, render_dpi / 72.0)
                        pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                             alpha=False)
                        # JPEG 압축 삽입 — 무압축 픽맵(페이지당 ~11MB) 대신
                        # 고해상도 유지하며 ~50KB 수준으로. (화질 약간 손실 허용)
                        try:
                            img_bytes = pm.tobytes("jpeg", jpg_quality=85)
                        except Exception:
                            img_bytes = pm.tobytes("png")
                        npage = new_doc.new_page(width=page.rect.width,
                                                 height=page.rect.height)
                        npage.insert_image(npage.rect, stream=img_bytes)
                    else:
                        new_doc.insert_pdf(src_doc, from_page=pno, to_page=pno)
                    added = True
                except Exception:
                    added = False

            if not added and png_path:
                try:
                    pix = fitz.Pixmap(str(png_path))
                except Exception:
                    pix = None
                if pix is not None:
                    npage = new_doc.new_page(width=pix.width, height=pix.height)
                    npage.insert_image(npage.rect, filename=str(png_path))
                    added = True

            if not added:
                continue

            top = bottom = None
            if show_filename:
                # v1.6.7 E2: 원본 PDF 명 우선(확장자·날짜 접두 없음).
                # 없으면 PNG stem 에서 'YYMMDD_HHMM_' 캡처 시각 접두 제거.
                if src_pdf:
                    top = Path(str(src_pdf)).stem
                else:
                    top = re.sub(r"^\d{6}_\d{4}_", "",
                                 Path(png_path or "screenshot").stem)
            if show_pageno:
                bottom = f"{i} / {total}"
            if top or bottom:
                _overlay_header_footer(new_doc[-1], top_text=top,
                                       bottom_text=bottom)

        new_doc.save(out)
    finally:
        new_doc.close()
        for d in opened.values():
            try:
                d.close()
            except Exception:
                pass
    return out


def temp_screenshot_dir() -> Path:
    return _temp_dir()
