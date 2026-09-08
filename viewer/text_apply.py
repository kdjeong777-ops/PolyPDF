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


def _write_invisible(page, rect, text, fontfile) -> bool:
    """사각형 안에 **보이지 않는 글자**를 적는다. 적었으면 True.

    260908-6(SOT §5.2): `insert_textbox` 는 글이 안 들어가면 **예외 없이 음수를 돌려주고
    아무것도 적지 않는다**. 종전 코드는 그 값을 보지 않아, 지우기만 되고 다시 적히지
    않은 줄이 생길 수 있었다(사용자 보고 '텍스트가 매칭이 안 된다'의 한 갈래).
    그래서 크기를 줄여 가며 다시 시도하고, 그래도 안 되면 한 줄로 적는다."""
    if not str(text):
        return True                              # 빈 줄 = 지우기(다시 적지 않는다)
    size = max(4.0, min(72.0, rect.height * 0.8))
    for _ in range(4):
        kw = {"fontsize": size, "render_mode": 3}
        if fontfile:
            kw.update(fontfile=fontfile, fontname="krfix")
        try:
            if page.insert_textbox(rect, text, **kw) >= 0:
                return True
        except Exception:
            break
        size *= 0.7
        if size < 3.0:
            break
    kw = {"fontsize": max(3.0, min(72.0, rect.height * 0.8)), "render_mode": 3}
    if fontfile:
        kw.update(fontfile=fontfile, fontname="krfix")
    try:
        page.insert_text((rect.x0, rect.y1 - kw["fontsize"] * 0.2), text, **kw)
        return True
    except Exception:
        return False


def apply_fixes_to_pdf(src, page_index: int, rows: list, fixes,
                       finalize=None) -> tuple:
    """고친 줄을 텍스트층에 반영. 반환 (결과 경로, 오류 문자열).

    `fixes` 는 `{줄번호: 고친 글}` 또는 **`[{"line","text","rect"}]`**(260908-6) 이다.
    뒤쪽이면 **저장해 둔 사각형을 그대로 지운다** — 줄 목록이 달라져도 지우는 자리가
    흔들리지 않는다(SOT §5.1.1). 못 적은 줄이 있으면 오류 문자열에 그 수를 담는다."""
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
            items = (fixes if isinstance(fixes, list)
                     else [{"line": i, "text": t, "rect": None}
                           for i, t in fixes.items()])
            for it in items:
                rc = it.get("rect")
                if not rc:                       # 자리를 안 적어 둔 옛 기록만 줄 번호로
                    i = int(it.get("line", -1))
                    rc = rows[i].get("rect") if 0 <= i < len(rows) else None
                if not rc:
                    continue
                targets.append((fitz.Rect(*rc), str(it.get("text", ""))))
            if not targets:
                return "", "고친 줄의 위치를 알 수 없습니다(OCR 좌표 없음)."
            for rect, _t in targets:
                page.add_redact_annot(rect)
            # 그림은 건드리지 않는다 — 스캔본의 본 모습이 그림이다
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            ff = _korean_font_file()
            unwritten = 0
            for rect, text in targets:
                if not _write_invisible(page, rect, text, ff):
                    unwritten += 1
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

    warn = (f"{unwritten}줄은 자리가 좁아 다시 적지 못했습니다(그 줄의 옛 글자는 지워졌습니다)."
            if unwritten else "")
    if finalize is not None:
        try:
            return str(finalize(str(src), str(tmp))), warn
        except Exception as e:                   # noqa: BLE001
            return "", str(e)
    import os as _os
    _os.replace(str(tmp), str(src))
    return str(src), warn
