# -*- coding: utf-8 -*-
"""260908-2: 고친 글을 **OCR 텍스트층에 다시 적기** (텍스트 창 SOT §5.2).

스캔 PDF 는 그림 위에 **보이지 않는 글자**(render mode 3)가 얹혀 있다. 복사·검색은 그
글자를 읽는다. OCR 이 틀리게 읽었으면 그 글자만 바꿔 끼우면 **화면 모양은 그대로**이고
복사 결과만 고쳐진다.

절차
  1) 원본 백업 `<이름>.textfix.bak.pdf`
  2) 고친 줄의 사각형에 redact 를 걸어 **글자만** 지운다
     (`images=PDF_REDACT_IMAGE_NONE` — 그림은 건드리지 않는다)
  3) 같은 자리에 `render_mode=3`(보이지 않음)으로 고친 글을 적는다
  4) 저장은 마스터 §4.7.5 규칙(`finalize` 콜백 = 원본 덮어쓰기·실패 시 알림)

★ **텍스트층이 보이는 일반 PDF 에는 쓰지 않는다.** 그 글자는 곧 화면에 보이는 내용이라
  다시 적으면 글꼴이 바뀐다. 호출측(app)이 미리 가른다.
"""
from __future__ import annotations

from pathlib import Path

BACKUP_SUFFIX = ".textfix.bak.pdf"


def _korean_font_file():
    """한글이 들어간 글을 적을 때 쓸 글꼴 파일. 없으면 None(기본 글꼴)."""
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
              r"C:\Windows\Fonts\batang.ttc"):
        if Path(p).exists():
            return p
    return None


def apply_fixes_to_pdf(src, page_index: int, rows: list, fixes: dict,
                       finalize=None) -> tuple:
    """고친 줄을 텍스트층에 반영. 반환 (결과 경로, 오류 문자열)."""
    try:
        import fitz
    except Exception as e:                       # noqa: BLE001
        return "", f"PyMuPDF 없음: {e}"
    src = Path(src)
    if not src.exists():
        return "", f"원본이 없습니다: {src}"
    if not fixes:
        return str(src), ""
    try:
        bak = src.with_name(src.name + BACKUP_SUFFIX)
        if not bak.exists():
            import shutil
            shutil.copy2(str(src), str(bak))
    except Exception:
        pass                                     # 백업 실패가 반영을 막지는 않는다

    tmp = src.with_name(src.stem + "_textfix_tmp.pdf")
    try:
        doc = fitz.open(str(src))
        try:
            page = doc.load_page(int(page_index))
            targets = []
            for i, text in fixes.items():
                if not (0 <= i < len(rows)):
                    continue
                rc = rows[i].get("rect")
                if not rc:
                    continue
                targets.append((fitz.Rect(*rc), str(text)))
            if not targets:
                return "", "고친 줄의 위치를 알 수 없습니다(OCR 좌표 없음)."
            for rect, _t in targets:
                page.add_redact_annot(rect)
            # 그림은 건드리지 않는다 — 스캔본의 본 모습이 그림이다
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            ff = _korean_font_file()
            for rect, text in targets:
                size = max(4.0, min(72.0, rect.height * 0.8))
                kw = {"fontsize": size, "render_mode": 3}   # 3 = 보이지 않음
                if ff:
                    kw.update(fontfile=ff, fontname="krfix")
                try:
                    page.insert_textbox(rect, text, **kw)
                except Exception:
                    page.insert_text((rect.x0, rect.y1 - size * 0.2), text, **kw)
            doc.save(str(tmp), garbage=3, deflate=True)
        finally:
            doc.close()
    except Exception as e:                       # noqa: BLE001
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "", str(e)

    if finalize is not None:
        try:
            return str(finalize(str(src), str(tmp))), ""
        except Exception as e:                   # noqa: BLE001
            return "", str(e)
    import os as _os
    _os.replace(str(tmp), str(src))
    return str(src), ""
