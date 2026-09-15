"""260915-9(마스터 §4.7.9): 썸네일 쪽 편집(순서·삭제·붙여넣기)으로 새 PDF 를 만든다 — **배경 스레드용**.

Qt 를 쓰지 않는다(위젯·대화상자 금지). 원본에는 손대지 않고 **임시 파일까지만** 만든다.
원본 자리에 놓기(다른 PolyPDF 창 확인·바꿔치기·제자리 쓰기)는 메인의 `_finalize_save` 가 한다 —
텍스트 창 반영(`TextLayerWorker`)과 같은 나눔이다.

실측(260915-9, 메인에서 돌던 종전 코드): 최장 정지 1.1~3.0초 — 책갈피 다시 쓰기 0.7~3.0초,
쪽마다 `insert_pdf` 최대 3.8초. 그래서
- 배경 스레드에서 돌리고(진행·취소),
- **이어진 쪽은 한 번에** 복사한다(`insert_pdf(from_page, to_page)`) — 쪽마다 부르면 호출이 쪽수만큼이고,
  같은 글꼴·그림을 부를 때마다 다시 복사해 저장 정리(`garbage=4`)도 무거워진다.
  덤으로 한 번에 복사한 구간 안의 쪽 사이 링크가 살아남는다(쪽마다 복사하면 끊겼다).
"""
from __future__ import annotations

import os
from pathlib import Path


class Cancelled(Exception):
    """진행 콜백이 False 를 돌려줬다(사용자가 진행창에서 취소)."""


def runs(plan, src: str):
    """plan([('own', i) | ('ext', 경로, 쪽)]) → 이어진 구간 목록 [(경로|None, 처음, 끝, [own 쪽들])].

    같은 파일의 쪽이 1씩 늘면 한 구간이다. 'own' 은 경로 None 으로 둔다.
    붙여넣기 쪽이 원본 파일 자신이면(같은 문서 안 복사) 'own' 과 섞지 않고 따로 둔다 — 책갈피는 'own' 만 따라간다."""
    out = []
    for e in plan:
        if e[0] == "own":
            key, pg = None, int(e[1])
        else:
            key, pg = str(e[1]), int(e[2])
        if out and out[-1][0] == key and out[-1][2] == pg - 1:
            k, a, _b, owns = out[-1]
            out[-1] = (k, a, pg, owns + ([pg] if key is None else []))
        else:
            out.append((key, pg, pg, [pg] if key is None else []))
    return out


def apply_toc(doc, bms) -> int:
    """책갈피 [(제목, 쪽 1-based, 레벨 0-based)] 를 **열린 문서에 바로** 넣는다(저장 전). 넣은 개수.

    종전에는 저장한 파일을 `pdf_bookmarker.apply_bookmarks_to_pdf`(pypdf)로 **통째로 다시 읽고 다시 썼다** —
    순수 파이썬이라 GIL 을 쥐어 배경 스레드여도 창이 섰고(실측 0.7~6초), 파일을 두 번 썼다. 모양은 그대로 맞춘다:
    제목의 '／' → '/', 굵게, **펼친 상태**(PyMuPDF 는 늘 접힌 `/Count -1` 로 쓰므로 양수로 고친다), 레벨은 윗 항목 +1 까지."""
    import fitz
    toc, prev = [], 0
    for title, page, level in bms:
        lvl = int(level) + 1
        lvl = 1 if not toc else max(1, min(lvl, prev + 1))
        t = str(title).replace("／", "/") or "(제목 없음)"
        toc.append([lvl, t, int(page), {"kind": fitz.LINK_GOTO, "page": int(page) - 1,
                                        "to": fitz.Point(0, 0), "bold": True}])
        prev = lvl
    doc.set_toc(toc)
    for e in doc.get_toc(simple=False):
        xr = (e[3] or {}).get("xref")
        if not xr:
            continue
        typ, val = doc.xref_get_key(xr, "Count")
        if typ == "int" and val.startswith("-"):
            doc.xref_set_key(xr, "Count", val[1:])
    return len(toc)


def build(src, plan, bookmarks_raw, recon, book_tmp, progress=None) -> dict:
    """새 PDF 를 만들고 {"path": 만든 임시 파일, "pages": 쪽수, "calls": insert_pdf 호출 수} 를 돌려준다.

    `progress(done, total, label) -> bool` 이 False 면 `Cancelled` (임시 파일은 지운다).
    책갈피는 남은 원본 쪽만 새 번호로 옮기고 지운 쪽 책갈피는 버린다(종전과 같다)."""
    import fitz
    src, recon, book_tmp = Path(src), Path(recon), Path(book_tmp)

    def tick(d, t, label):
        if progress is not None and progress(d, t, label) is False:
            raise Cancelled()

    total = max(1, len(plan))
    try:
        sdoc = fitz.open(str(src))
        ext = {}
        odoc = fitz.open()
        ownpos, outc, calls = {}, 0, 0
        try:
            for key, a, b, owns in runs(plan, str(src)):
                tick(outc, total, "쪽 복사 중")
                if key is None:
                    doc = sdoc
                else:
                    doc = ext.get(key)
                    if doc is None:
                        doc = sdoc if key == str(src) else fitz.open(key)
                        ext[key] = doc
                a2, b2 = max(0, a), min(doc.page_count - 1, b)
                if a2 > b2:
                    continue
                odoc.insert_pdf(doc, from_page=a2, to_page=b2)
                calls += 1
                for pg in range(a2, b2 + 1):
                    if key is None:
                        ownpos[pg] = outc
                    outc += 1
            if outc == 0:
                raise RuntimeError("저장할 페이지가 없습니다.")
            # 책갈피: 지운 쪽 것은 버리고 남은 원본 쪽은 새 번호로 — 저장 **전에** 같은 문서에(한 번에 쓴다)
            bms = [(t, ownpos[p1 - 1] + 1, lv) for (t, p1, lv) in (bookmarks_raw or []) if (p1 - 1) in ownpos]
            if bms:
                apply_toc(odoc, bms)
            tick(outc, total, "저장 중")
            odoc.save(str(recon), garbage=4, deflate=True)
        finally:
            odoc.close()
            for d in ext.values():
                if d is not sdoc:
                    try:
                        d.close()
                    except Exception:
                        pass
            sdoc.close()
        tick(total, total, "원본에 놓을 준비")
        return {"path": str(recon), "pages": outc, "calls": calls, "bookmarks": len(bms)}
    except BaseException:
        for t in (recon, book_tmp):
            try:
                if t.exists():
                    os.remove(str(t))
            except Exception:
                pass
        raise
