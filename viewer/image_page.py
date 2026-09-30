# -*- coding: utf-8 -*-
"""260930-1(마스터 §4.7.11): 사진을 **문서 쪽 크기의 1쪽 PDF** 로 바꾼다.

썸네일에 사진을 더하는 세 길(클립보드·스크린샷 스트립·바깥 파일)이 모두 여기로 모인다.
사진을 1쪽 PDF 로 바꿔 두면 §4.7.7 의 스테이징(`("ext", PDF경로, 쪽)`)이 그대로 받아,
썸네일 렌더·미저장 표시·저장 재구성·취소가 손댈 것 없이 돈다.

**Qt 를 쓰지 않는다** — 클립보드 그림은 부르는 쪽(Qt)이 임시 PNG 로 떨군 뒤 경로로 넘긴다.
그래서 이 모듈은 위젯 없이 그대로 검사할 수 있다.

쪽 크기 규칙(§4.7.11, 사용자 결정): 문서 **첫 쪽 크기**에 맞추고, 사진은 **비율을 지켜**
가운데에 둔다. 쪽보다 작으면 **키우지 않는다**(늘리면 흐려진다). 회전하지 않는다.
"""
from __future__ import annotations

from pathlib import Path

# 받는 그림 확장자 — 끌어 놓기에서 거르는 데도 쓴다(§4.7.11 '그림 파일만 받는다').
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def is_image_path(path) -> bool:
    """이 경로가 우리가 받는 그림인가 (확장자만 본다 — 끌어 놓기 판정은 빨라야 한다)."""
    try:
        return Path(str(path)).suffix.lower() in IMAGE_EXTS
    except Exception:
        return False


def fit_rect(img_w: float, img_h: float, page_w: float, page_h: float):
    """사진을 쪽 안에 **비율대로 가운데** 놓을 자리 `(x0, y0, x1, y1)` (§4.7.11).

    쪽보다 작은 사진은 **그 크기 그대로** 둔다(배율 1을 넘기지 않는다).
    """
    img_w, img_h = float(img_w), float(img_h)
    page_w, page_h = float(page_w), float(page_h)
    if img_w <= 0 or img_h <= 0 or page_w <= 0 or page_h <= 0:
        return (0.0, 0.0, page_w, page_h)
    scale = min(page_w / img_w, page_h / img_h, 1.0)
    w, h = img_w * scale, img_h * scale
    x0 = (page_w - w) / 2.0
    y0 = (page_h - h) / 2.0
    return (x0, y0, x0 + w, y0 + h)


def page_size_of(pdf_path, page_index: int = 0):
    """그 PDF 의 쪽 크기 `(폭, 높이)` pt. 못 읽으면 None.

    §4.7.11: 쪽마다 크기가 다른 문서는 **첫 쪽**을 기준으로 삼는다.
    """
    import fitz
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        if doc.page_count <= 0:
            return None
        r = doc.load_page(max(0, min(int(page_index), doc.page_count - 1))).rect
        w, h = float(r.width), float(r.height)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None
    finally:
        try:
            doc.close()
        except Exception:
            pass


def images_to_pdf(image_paths, out_pdf, page_size=None, progress=None) -> int:
    """그림들을 **한 장에 한 쪽씩** 담은 PDF 로 저장한다. 넣은 쪽 수를 준다.

    `page_size=(폭, 높이)` pt 면 그 크기로 쪽을 만들고 사진을 비율대로 가운데 놓는다
    (§4.7.11). None 이면 사진 크기 그대로 쪽을 만든다.

    읽을 수 없는 그림은 **건너뛴다** — 여러 장을 끌어다 놓았을 때 하나가 깨졌다고
    나머지까지 잃지 않게. 한 장도 못 넣으면 파일을 만들지 않고 0 을 준다.

    `progress(done, total, 안내)` 가 **False** 를 주면 `MergeCancelled` 로 멈춘다 —
    `app._run_merge_job` 이 쓰는 규약 그대로다(응답성 SOT §4). 큰 묶음을 배경에서
    돌리려고 두었다. 없으면 그냥 끝까지 만든다.
    """
    from viewer.twoup import MergeCancelled
    import fitz
    paths = [str(p) for p in (image_paths or [])]
    if not paths:
        return 0
    doc = fitz.open()
    try:
        for p in paths:
            try:
                pix = fitz.Pixmap(p)
                iw, ih = float(pix.width), float(pix.height)
                pix = None                      # 자리만 재고 곧바로 놓아 준다
            except Exception:
                continue                        # 깨진 그림은 건너뛴다
            if iw <= 0 or ih <= 0:
                continue
            pw, ph = (float(page_size[0]), float(page_size[1])) if page_size else (iw, ih)
            try:
                page = doc.new_page(width=pw, height=ph)
                page.insert_image(fitz.Rect(*fit_rect(iw, ih, pw, ph)), filename=p)
            except Exception:
                continue
            if progress is not None and progress(
                    doc.page_count, len(paths), "사진을 쪽으로 만드는 중") is False:
                raise MergeCancelled()
        n = doc.page_count
        if n:
            # ★ `deflate=True` 가 없으면 그림 스트림이 **날것으로** 들어간다 —
            #   실측(260930-1 SOT 점검): 스크린샷 PNG 0.01MB → **5.94MB**,
            #   사진 PNG 0.47MB → **17.17MB**(36~594배). 이 임시 PDF 는 저장할 때
            #   원본에 복사되므로 부풀면 임시 디스크·복사 시간이 그만큼 늘어난다.
            #   저장 옵션은 프로젝트 관례와 같다(마스터 §4.5.10 · 스크린샷 SOT §7).
            doc.save(str(out_pdf), deflate=True, garbage=4)
        return int(n)
    finally:
        try:
            doc.close()
        except Exception:
            pass
