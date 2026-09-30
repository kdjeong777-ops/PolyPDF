# -*- coding: utf-8 -*-
"""260930-1: 사진을 새 쪽으로 추가 (마스터 §4.7.11).

사용자 요청(`#polypdf 편집모드에서 페이지 추가`)
  - 썸네일 우클릭 → 클립보드 사진을 그 썸네일 **다음 장**으로
  - 스크린샷 스트립의 컷을 끌어다 본문 썸네일에 놓으면 쪽 추가
  - 바깥 사진 파일을 끌어다 놓으면 쪽 추가(놓은 썸네일 다음 장)

셋은 **한 가지 일**이다 — 들어오는 문만 다르고, 안에서는 '그림 파일 목록' 하나로
흐른다(§4.7.11). 사진은 **1쪽짜리 PDF** 로 바뀌어 §4.7.7 의 스테이징에 그대로 들어간다.

검사 대상
  ① 쪽 크기 — 문서 첫 쪽 크기에 맞추고, 비율을 지켜 가운데. 작은 사진은 키우지 않는다
  ② 깨진 그림은 건너뛰고 나머지를 살린다 / 한 장도 못 읽으면 0
  ③ 그림만 받는다(PDF·아무 파일은 받지 않는다)
  ④ **실제 드롭 이벤트** — 편집모드면 기준 행 **뒤**에 들어가고 미저장(dirty)이 된다
  ⑤ 편집모드가 아니면 받지 않고 **까닭을 알린다**(조용히 무시하지 않는다)
  ⑥ ★ **복사로 받는다** — 스트립(InternalMove)의 컷이 지워지지 않게
  ⑦ 스트립이 끌 때 **파일 경로를 함께** 싣는다(받는 쪽에 전용 길을 내지 않는다)
  ⑧ 빈 곳에 놓으면 맨 뒤
  ⑨ 임시 파일은 문서를 닫을 때 치운다
  ⑩ 스테이징이 저장 재구성(§4.7.9)이 읽는 모양(`("ext", PDF, 쪽)`)으로 들어간다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPointF, QEvent
from PyQt6.QtGui import QDropEvent, QDragEnterEvent

from viewer.image_page import images_to_pdf, fit_rect, page_size_of, is_image_path
from viewer.widgets.thumbs_list import PageThumbs

fails = []


def chk(ok, what, got=""):
    print(("PASS - " if ok else "FAIL - ") + what + (" " + str(got) if got else ""))
    if not ok:
        fails.append(what)


app = QApplication.instance() or QApplication([])
root = tempfile.mkdtemp(prefix="add_img_")


def png(name, w, h):
    p = os.path.join(root, name)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.clear_with(180)
    pix.save(p)
    return p


def a4_pdf(name, pages=3):
    p = os.path.join(root, name)
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 100), f"page {i + 1}")
    d.save(p)
    d.close()
    return p


try:
    wide = png("wide.png", 1920, 1080)      # 16:9 — A4 에 넣으면 위아래 여백
    small = png("small.png", 100, 80)       # 쪽보다 작다 — 키우지 않는다
    pdf = a4_pdf("doc.pdf", 3)

    # ── ① 쪽 크기·배치 ───────────────────────────────────────────────
    size = page_size_of(pdf)
    chk(size and abs(size[0] - 595) < 1 and abs(size[1] - 842) < 1,
        "① 문서 첫 쪽 크기를 읽는다", size)
    out = os.path.join(root, "img.pdf")
    n = images_to_pdf([wide, small], out, page_size=size)
    chk(n == 2, "① 그림마다 한 쪽", n)
    d = fitz.open(out)
    chk(all(abs(d[i].rect.width - 595) < 1 and abs(d[i].rect.height - 842) < 1
            for i in range(d.page_count)),
        "① 새 쪽이 **문서 쪽 크기**다(사진 크기가 아니다)",
        f"{d[0].rect.width:.0f}x{d[0].rect.height:.0f}")
    r = fit_rect(1920, 1080, 595, 842)
    chk(abs(r[0]) < 0.5 and abs(r[2] - 595) < 0.5 and r[1] > 1,
        "① 16:9 는 폭을 꽉 채우고 위아래 여백(비율 유지)",
        [round(v, 1) for v in r])
    chk(abs((r[1]) - (842 - r[3])) < 0.5, "① 위아래 여백이 같다(가운데)")
    r2 = fit_rect(100, 80, 595, 842)
    chk(abs((r2[2] - r2[0]) - 100) < 0.5 and abs((r2[3] - r2[1]) - 80) < 0.5,
        "① 쪽보다 작은 사진은 **키우지 않는다**",
        [round(v, 1) for v in r2])
    d.close()

    # ── ② 깨진 그림 ─────────────────────────────────────────────────
    broken = os.path.join(root, "broken.png")
    Path(broken).write_bytes(b"not an image")
    o2 = os.path.join(root, "mix.pdf")
    chk(images_to_pdf([broken, wide], o2, page_size=size) == 1,
        "② 깨진 그림은 건너뛰고 나머지는 살린다")
    chk(images_to_pdf([broken], os.path.join(root, "none.pdf"), page_size=size) == 0,
        "② 한 장도 못 읽으면 0(파일을 만들지 않는다)")
    chk(not os.path.exists(os.path.join(root, "none.pdf")),
        "② 빈 PDF 를 남기지 않는다")

    # ── ⑫ 압축해서 저장한다(260930-1 SOT 점검) ──────────────────────
    #   `deflate=True` 가 없으면 그림이 **날것으로** 들어가 임시 PDF 가 수십 배가 된다.
    big = png("big.png", 2000, 1500)
    o3 = os.path.join(root, "big.pdf")
    images_to_pdf([big], o3, page_size=size)
    raw = 2000 * 1500 * 3 / 1048576.0          # 날것으로 넣으면 이만큼(8.6MB)
    chk(os.path.getsize(o3) / 1048576.0 < raw * 0.25,
        "⑫ 그림 스트림을 **압축**해서 넣는다(임시 PDF 가 부풀지 않게)",
        "%.2fMB (날것이면 %.1fMB)" % (os.path.getsize(o3) / 1048576.0, raw))

    # ── ⑬ 큰 묶음은 **취소**할 수 있다(응답성 SOT §4) ───────────────
    from viewer.twoup import MergeCancelled
    seen = []

    def _cancel_after_one(done, total, label):
        seen.append((done, total))
        return False                            # 첫 장 뒤 취소
    try:
        images_to_pdf([wide, small], os.path.join(root, "c.pdf"),
                      page_size=size, progress=_cancel_after_one)
        chk(False, "⑬ 취소하면 MergeCancelled 로 멈춘다")
    except MergeCancelled:
        chk(True, "⑬ 취소하면 MergeCancelled 로 멈춘다", seen)
    chk(not os.path.exists(os.path.join(root, "c.pdf")),
        "⑬ 취소하면 파일을 남기지 않는다")

    # ── ③ 그림만 받는다 ─────────────────────────────────────────────
    for f, want in ((wide, True), ("a.JPG", True), (pdf, False), ("a.txt", False)):
        chk(is_image_path(f) is want, "③ %s 판정" % Path(f).suffix, want)

    # ── 위젯 준비 ───────────────────────────────────────────────────
    pt = PageThumbs()
    pt.load_document(pdf)
    app.processEvents()
    chk(pt.list.count() == 3, "준비 — 썸네일 3쪽", pt.list.count())

    got = {}
    pt.addImagePagesRequested.connect(lambda row, ps: got.update(row=row, paths=list(ps)))
    refused = []
    pt.imageDropRefused.connect(lambda: refused.append(1))

    # ★ 오프스크린에서는 **합성 드롭을 sendEvent 로 보낼 수 없다** — QApplication.notify 가
    #   끌기·놓기를 드래그 매니저로 돌리므로, 진행 중인 끌기가 없으면 이벤트가 필터에
    #   닿지 않는다(실측: Drop(63) 을 보내도 필터가 한 번도 못 본다). 그래서
    #   **Qt 가 부르는 바로 그 함수**(`eventFilter`)를 같은 인자로 직접 부른다.
    #   '필터가 실제로 뷰포트에 걸려 있는가' 는 아래 ⑪ 에서 따로 못박는다.
    # 진짜 끌기가 내놓는 것과 같게 — 스트립·탐색기 모두 Copy|Move 를 내놓는다(아래 ⑥ 실측).
    MOVE_COPY = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def drop(paths, row=0, action=MOVE_COPY, etype=QEvent.Type.Drop):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(x) for x in paths])
        item = pt.list.item(row) if row is not None and row < pt.list.count() else None
        pos = (QPointF(pt.list.visualItemRect(item).center())
               if item is not None else QPointF(5, 100000))
        ev = QDropEvent(pos, action, md, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
        handled = pt.eventFilter(pt.list.viewport(), ev)
        ev._handled = handled
        return ev

    # ── ⑤ 편집모드가 아니면 ─────────────────────────────────────────
    pt.set_edit_mode(False)
    got.clear(); refused.clear()
    drop([wide], row=0)
    chk(not got and refused, "⑤ 편집모드가 아니면 받지 않고 **알린다**",
        "요청 %s 안내 %d" % (bool(got), len(refused)))

    # ── ④⑥ 편집모드 드롭 ───────────────────────────────────────────
    pt.set_edit_mode(True)
    got.clear()
    ev = drop([wide, small], row=1)
    def _same(a, b):      # QUrl 은 `/` 로 돌려준다 — 비교만 맞춰 준다
        return [str(x).replace("\\", "/") for x in a] == [str(y).replace("\\", "/") for y in b]
    chk(got.get("row") == 1 and _same(got.get("paths") or [], [wide, small]),
        "④ 놓은 행과 그림 목록이 그대로 온다", got)
    chk(ev.dropAction() == Qt.DropAction.CopyAction,
        "⑥ ★ **복사**로 받는다 — 스트립 컷이 지워지지 않게", ev.dropAction())
    # 복사를 안 내놓는 출처라면 그대로 받는다 — 받지 않는 것보다 낫다
    got.clear()
    ev_m = drop([wide], row=0, action=Qt.DropAction.MoveAction)
    chk(ev_m.isAccepted() and got.get("row") == 0,
        "⑥ 복사를 안 내놓는 출처여도 받는다", ev_m.dropAction())
    chk(ev.isAccepted(), "④ 드롭을 받았다")

    # ── ⑧ 빈 곳 → 맨 뒤 ────────────────────────────────────────────
    got.clear()
    drop([wide], row=None)
    chk(got.get("row") == pt.list.count() - 1, "⑧ 빈 곳에 놓으면 맨 뒤", got.get("row"))

    # ── ③ PDF 를 끌어 놓으면 우리 길로 오지 않는다 ──────────────────
    got.clear(); refused.clear()
    ev2 = drop([pdf], row=0)
    chk(not got, "③ PDF 는 받지 않는다(쪽 붙여넣기가 따로 있다)")

    # ── ④⑩ 실제 삽입 — 기준 행 '뒤', 미저장, 저장이 읽는 모양 ───────
    chk(not pt.is_page_dirty(), "④ 넣기 전에는 미저장이 아니다")
    tmp_pdf = pt.staged_temp_path(".pdf")
    n = images_to_pdf([wide, small], tmp_pdf, page_size=size)
    pt.insert_external_pages(1, tmp_pdf, range(n))
    app.processEvents()
    chk(pt.list.count() == 5, "④ 두 쪽이 늘었다", pt.list.count())
    plan = pt.current_page_plan()
    chk(plan[0] == ("own", 0) and plan[1] == ("own", 1),
        "④ 기준 행 **뒤**에 들어간다(앞은 그대로)", plan[:2])
    chk(plan[2] == ("ext", tmp_pdf, 0) and plan[3] == ("ext", tmp_pdf, 1),
        "⑩ 저장 재구성이 읽는 모양 `(\"ext\", PDF, 쪽)`", plan[2])
    chk(pt.is_page_dirty(), "④ 미저장(dirty)이 된다")
    chk(pt.current_page_sequence() == [0, 1, 2],
        "④ '자체 쪽' 목록에는 섞이지 않는다", pt.current_page_sequence())

    # ── ⑨ 임시 파일 정리 ───────────────────────────────────────────
    chk(os.path.exists(tmp_pdf), "⑨ 저장 전에는 임시 PDF 가 살아 있다")
    pt.clear_document()
    chk(not os.path.exists(tmp_pdf), "⑨ 문서를 닫으면 임시 파일을 치운다")

    # ── ⑦ 스트립이 경로를 싣는다 ───────────────────────────────────
    from viewer.widgets.strip import MiniStrip
    st = MiniStrip("🖼 스크린샷", max_items=10, draggable=True)
    st.add_item(wide, kind="image", label="cut1")
    app.processEvents()
    chk(st.list.count() == 1, "⑦ 준비 — 스트립에 컷 하나", st.list.count())
    md = st.list.mimeData([st.list.item(0)])
    urls = [u.toLocalFile() for u in md.urls()] if md is not None else []
    chk(_same(urls, [wide]), "⑦ 끌 때 **파일 경로**를 함께 싣는다", urls)
    chk(st.list.dragDropMode().name == "InternalMove",
        "⑦ 스트립 안의 순서 바꾸기는 그대로", st.list.dragDropMode().name)
    # ⑥ 의 '복사로 받기' 는 **보낸 쪽이 복사를 내놓을 때만** 된다 — 스트립이 내놓는지 못박는다.
    #   여기가 Move 만 남으면 밖으로 끌어낸 컷이 스트립에서 사라진다.
    chk(bool(st.list.model().supportedDragActions() & Qt.DropAction.CopyAction),
        "⑥ ★ 스트립이 **복사**를 내놓는다(컷이 사라지지 않는 근거)",
        st.list.model().supportedDragActions())

    # ── ⑪ 필터가 뷰포트에 **실제로 걸려 있다** ──────────────────────
    #   위 ④~⑧ 은 필터 함수를 직접 불렀으므로, 'Qt 가 그 함수를 부르는가' 를 따로 본다.
    #   같은 필터가 맡는 휠(뷰포트로 보내는 진짜 이벤트)이 먹히면 걸려 있는 것이다.
    from PyQt6.QtGui import QWheelEvent
    pt.list.verticalScrollBar().setValue(0)
    before = pt.list.currentRow()
    we = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPointF(0, 0).toPoint(),
                     QPointF(0, -120).toPoint(), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    handled = app.sendEvent(pt.list.viewport(), we)
    chk(handled, "⑪ 뷰포트 이벤트 필터가 걸려 있다(같은 필터가 휠을 먹는다)", handled)
    chk(pt.list.viewport().acceptDrops(),
        "⑪ 편집모드에서 뷰포트가 드롭을 받는다")
    pt.set_edit_mode(False)
    chk(pt.list.viewport().acceptDrops(),
        "⑪ ★ 편집모드가 **아닐 때도** 받는다 — 그래야 까닭을 알릴 수 있다")

except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    try:
        shutil.rmtree(root, ignore_errors=True)
    except Exception:
        pass

print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("=== ALL PASS ===")
