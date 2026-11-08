# -*- coding: utf-8 -*-
"""261101-3: 이미지 넣기 · 등록 이미지(도장·명판) (마스터 SOT §4.6.11).

A 영역 → 벡터 조각(글자층) / 그림(글자층 없음)   B 날짜 글자(벡터·그림)
C 단추·실제 마우스로 도구 켜기·누른 자리 실제 크기·▾ 메뉴   D page_meta blobs(한 번만·풀어 읽기·지우기)·모르는 필드 유지
E 여러 쪽 — 가까운 모서리 기준   F 굽기 — 벡터 그대로(글자가 글자로)
수정 전 코드에는 이미지 단추·stamp_* 모듈이 없어 실패한다.
"""
import os, sys, tempfile, shutil, json, datetime
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_stamp_%d" % os.getpid())
from PyQt6.QtTest import QTest
import fitz
from viewer import stamp_core, stamp_store, pdf_font
from viewer.settings_store import settings_dir
from viewer.page_meta import PageMetaStore, BLOB_MIN
from viewer.widgets.main_view import MainView

root = Path(tempfile.mkdtemp(prefix="polypdf_stamp_"))
sdir = Path(settings_dir())
chk("polypdf_stamp_" in str(sdir) or "qttest" in str(sdir).lower(), "설정 폴더가 시험용이다(전제)", str(sdir))


def make_pdf(path, sizes):
    """쪽마다: 왼쪽 위 '원본대조필' 상자(글자층) + 오른쪽 아래 글자 없는 그림 블록."""
    d = fitz.open()
    ff = pdf_font.text_font_file()
    for (w, h) in sizes:
        p = d.new_page(width=w, height=h)
        p.draw_rect(fitz.Rect(40, 40, 200, 80), color=(0.1, 0.2, 0.6), width=2)
        p.insert_text((50, 70), "원본대조필", fontsize=22, fontfile=ff, fontname="kr", color=(0.1, 0.2, 0.6))
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 30), False)
        pix.set_rect(pix.irect, (120, 40, 160))
        p.insert_image(fitz.Rect(w - 120, h - 80, w - 40, h - 40), pixmap=pix)
    d.save(str(path))
    d.close()


pdf = root / "doc.pdf"
make_pdf(pdf, [(595, 842), (842, 1191), (612, 792)])
try:
    # ── A 영역 → 벡터 조각 / 그림 ─────────────────────────────────────
    doc = fitz.open(str(pdf))
    txt_clip = fitz.Rect(36, 36, 204, 84)
    img_clip = fitz.Rect(595 - 124, 842 - 84, 595 - 36, 842 - 36)
    chk(stamp_core.region_has_text(doc[0], txt_clip), "A1 글자층이 있는 영역을 알아본다")
    chk(not stamp_core.region_has_text(doc[0], img_clip), "A2 그림뿐인 영역은 글자층이 없다")
    piece = stamp_core.region_piece(doc, 0, txt_clip)
    with fitz.open(stream=piece, filetype="pdf") as q:
        chk("원본대조필" in q[0].get_text(), "A3 벡터 조각에 글자가 글자로 남는다", repr(q[0].get_text()[:20]))
        chk(abs(q[0].rect.width - txt_clip.width) < 0.5, "A4 조각 크기 = 끈 영역(pt)", str(q[0].rect))
    chk(len(piece) < 200_000, "A5 조각에 글꼴 전체가 들어가지 않는다(부분집합)", f"{len(piece)} B")
    png = stamp_core.clean(stamp_core.region_png(doc[0], img_clip, dpi=150))
    chk(png.mode == "RGBA" and png.getchannel("A").getextrema()[0] == 0 or png.getchannel("A").getextrema()[1] > 0,
        "A6 그림 영역은 RGBA 로 정리된다")
    # 회전한 쪽 — 보이는 방향 그대로
    d2 = fitz.open(str(pdf)); d2[0].set_rotation(90)
    vis = fitz.Rect(36, 36, 204, 84) * d2[0].rotation_matrix
    vis.normalize()
    chk(stamp_core.region_has_text(d2[0], vis), "A7 회전한 쪽의 보이는 좌표 영역에서도 글자층을 찾는다")
    with fitz.open(stream=stamp_core.region_piece(d2, 0, vis), filetype="pdf") as q:
        chk("원본대조필" in q[0].get_text() and q[0].rect.height > q[0].rect.width,
            "A8 회전한 쪽의 조각은 보이는 방향(세로)으로", str(q[0].rect))
    d2.close()

    # ── B 날짜 글자 ────────────────────────────────────────────────────
    day = datetime.date(2026, 11, 1)
    e_pdf = stamp_store.add("pdf", piece, "원본대조필", 59.3, {"on": True, "fmt": "%Y.%m.%d", "box": [0.75, 0.0, 0.25, 1.0]})
    c = stamp_core.compose(e_pdf, stamp_store.payload(e_pdf), when=day)
    with fitz.open(stream=c["pdf"], filetype="pdf") as q:
        chk("2026.11.01" in q[0].get_text(), "B1 벡터 조각에 날짜가 글자로 들어간다", repr(q[0].get_text()))
    chk(stamp_store.date_text("%Y년 %#m월 %#d일", day) == "2026년 11월 1일", "B2 날짜 형식(앞 0 없음·한글)")
    from PIL import Image
    seal = Image.new("RGBA", (400, 200), (255, 255, 255, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(seal).rectangle((10, 10, 390, 190), outline=(110, 60, 160, 255), width=8)
    e_png = stamp_store.add("png", stamp_core.png_bytes(seal), "명판", 50, {"on": False})
    c0 = stamp_core.compose(e_png, stamp_store.payload(e_png), when=day)
    stamp_store.update(e_png["id"], date={"on": True, "fmt": "%Y-%m-%d", "box": [0.1, 0.4, 0.8, 0.3]})
    c1 = stamp_core.compose(stamp_store.get(e_png["id"]), stamp_store.payload(e_png), when=day)
    chk(c0["png"] != c1["png"] and c1["pdf"] is None, "B3 그림에는 날짜를 그림으로 그린다")
    ic = stamp_core.ink_color(seal)
    chk(all(abs(int(ic[i:i + 2], 16) - v) <= 6 for i, v in ((1, 110), (3, 60), (5, 160))),
        "B4 날짜 기본색 = 잉크 평균색", ic)
    stamp_store.update(e_png["id"], date={"on": False})

    # ── C 단추·마우스 ──────────────────────────────────────────────────
    st = PageMetaStore(root)
    mv = MainView()
    mv._img_resolver = lambda f, p: st.get_images(f, p)
    mv._img_setter = lambda f, p, imgs: st.set_images(f, p, imgs)
    mv.resize(1000, 1100)
    mv.show()
    mv.load_document(pdf, 0)
    app.processEvents()
    mv.set_draw_mode(True)
    app.processEvents()
    hb = mv._text_btn.parentWidget().layout()
    order = [hb.itemAt(i).widget() for i in range(hb.count())]
    chk(mv._image_btn in order and order.index(mv._image_btn) == order.index(mv._text_btn) + 1,
        "C1 이미지 단추는 글쓰기 단추 바로 오른쪽")
    stamp_store.set_last(e_pdf["id"])
    mv._stamp_id = ""
    mv._image_btn.click(); app.processEvents()
    chk(mv._draw_kind == "stamp" and mv._draw_tool == ("stamp", e_pdf["id"]), "C2 단추를 누르면 마지막 등록 이미지로 도구가 켜진다",
        str(mv._draw_tool))
    chk("#ff7a00" in mv._image_btn.styleSheet(), "C3 켜진 모양")
    pr = mv._page_view_rect()
    pw, ph = mv.page_size_pt()
    chk(abs(pw - 595) < 1.5 and abs(ph - 842) < 1.5, "C4 쪽 크기(pt) = 화면 상자 ÷ 배율(전제)", f"{pw:.1f}x{ph:.1f}")
    at = QPoint(int(pr.left() + pr.width() * 0.5), int(pr.top() + pr.height() * 0.6))
    QTest.mouseClick(mv.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    app.processEvents()
    chk(len(mv._img_objects) == 1, "C5 본문을 누르면 하나 넣는다", str(len(mv._img_objects)))
    if mv._img_objects:
        o = mv._img_objects[0]
        w_mm = o["rect"][2] * pw / stamp_core.PT_PER_MM
        chk(abs(w_mm - 59.3) < 0.6, "C6 실제 폭 mm 그대로", f"{w_mm:.2f} mm")
        chk(abs(o["rect"][0] - (at.x() - pr.left()) / pr.width()) < 0.01
            and abs(o["rect"][1] - (at.y() - pr.top()) / pr.height()) < 0.01, "C7 누른 자리가 왼쪽 위", str(o["rect"][:2]))
        chk("pdf" in (o.get("extra") or {}), "C8 벡터 조각을 꾸밈에 함께 든다")
    chk(mv._draw_tool == ("select", None), "C9 넣은 뒤 개체선택으로(바로 옮길 수 있게)", str(mv._draw_tool))
    # 큰 등록 이미지 — 쪽 밖이면 줄여 안으로
    e_big = stamp_store.add("png", stamp_core.png_bytes(seal), "큰 것", 280, {})
    mv.pick_stamp(e_big["id"])
    QTest.mouseClick(mv.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(pr.left() + pr.width() * 0.9), int(pr.top() + pr.height() * 0.9)))
    app.processEvents()
    ob = mv._img_objects[-1]["rect"]
    chk(ob[0] >= -1e-6 and ob[1] >= -1e-6 and ob[0] + ob[2] <= 1 + 1e-6 and ob[1] + ob[3] <= 1 + 1e-6,
        "C10 쪽보다 크거나 넘치면 쪽 안으로", str([round(v, 3) for v in ob]))
    # ▾ 메뉴 — 등록 이미지를 고르면 도구가 켜진다
    mv._draw_kind = None; mv._apply_tool()
    mv._rebuild_image_menu()
    acts = [a for a in mv._image_menu.actions() if a.text().startswith("명판")]
    chk(bool(acts), "C11 ▾ 에 등록 이미지가 이름·폭으로 보인다", str([a.text() for a in mv._image_menu.actions()]))
    if acts:
        acts[0].trigger(); app.processEvents()
        chk(mv._draw_tool == ("stamp", e_png["id"]), "C12 ▾ 에서 고르면 그것으로 도구가 켜진다", str(mv._draw_tool))
    got = []
    mv.imageMenuRequested.connect(got.append)
    for a in mv._image_menu.actions():
        if a.text() in ("PDF 에서 영역 등록", "등록 이미지 관리"):   # 261107-20: 글 끝 '…' 없음
            a.trigger()
    chk(got == ["region", "manage"], "C13 ▾ 의 영역 등록·관리는 앱으로 알린다", str(got))
    # 등록 이미지가 없으면 단추가 메뉴를 연다
    for e in stamp_store.items():
        pass
    shown = []
    mv._image_btn.showMenu = lambda: shown.append(1)
    saved = json.loads((stamp_store.root() / stamp_store.INDEX).read_text(encoding="utf-8"))
    stamp_store.save({"items": [], "last": ""})
    mv._draw_kind = None; mv._apply_tool(); mv._stamp_id = ""
    mv._image_btn.click(); app.processEvents()
    chk(shown == [1] and mv._draw_kind != "stamp", "C14 등록 이미지가 없으면 단추가 ▾ 메뉴를 연다")
    stamp_store.save(saved)

    # ── D blobs · 모르는 필드 ───────────────────────────────────────────
    f = str(pdf)
    raw = st._data["files"]["doc.pdf"]["images"]["0"]
    chk(str(raw[0].get("data", "")).startswith("@") and str(raw[0].get("pdf", "")).startswith("@")
        and not str(raw[1].get("data", "")).startswith("@"),
        "D1 큰 값(BLOB_MIN 넘음)은 blobs 에 두고 항목에는 @sha1, 작은 값은 그대로", str([str(d.get("data"))[:6] for d in raw]))
    chk(st.get_images(f, 0)[0]["pdf"] == mv._img_objects[0]["extra"]["pdf"], "D2 읽을 때 풀어 준다")
    mv._load_page_images()
    chk("pdf" in mv._img_objects[0].get("extra", {}) and mv._img_objects[0]["extra"].get("stamp") == "원본대조필",
        "D3 다시 읽어도 모르는 필드(pdf·stamp)가 남는다")
    big = "A" * (BLOB_MIN * 3)
    for p in (0, 1, 2):
        st.set_images(f, p, [{"data": big, "rect": [0.1, 0.1, 0.2, 0.1], "shape": "rect", "alpha": 100, "rot": 0}])
    st.save()
    from viewer import bg_write              # 261108-15: 파일 쓰기는 배경 쓰기 줄 — 디스크를 보기 전에 비운다
    bg_write.flush()
    text = (root / "page_meta.json").read_text(encoding="utf-8")
    chk(text.count(big) == 1, "D4 같은 그림을 세 쪽에 넣어도 파일에는 한 번", str(text.count(big)))
    for p in (0, 1, 2):
        st.set_images(f, p, [])
    st.save()
    bg_write.flush()
    chk("blobs" not in json.loads((root / "page_meta.json").read_text(encoding="utf-8"))["files"]["doc.pdf"],
        "D5 아무도 안 쓰는 blobs 는 저장 때 지운다")
    st.copy_file(f, str(root / "copy.pdf"))      # rename·copy 는 파일 항목째 — blobs 도 따라간다(전제)

    # ── E 여러 쪽 — 가까운 모서리 ───────────────────────────────────────
    mm10 = 10 * stamp_core.PT_PER_MM
    w, h = 50 * stamp_core.PT_PER_MM, 20 * stamp_core.PT_PER_MM
    src = [(595 - mm10 - w) / 595, (842 - mm10 - h) / 842, w / 595, h / 842]       # A4 오른쪽 아래 10mm
    r = stamp_core.same_corner_rect(src, 595, 842, 842, 1191)                        # A3
    chk(abs((842 - (r[0] + r[2]) * 842) - mm10) < 0.01 and abs((1191 - (r[1] + r[3]) * 1191) - mm10) < 0.01
        and abs(r[2] * 842 - w) < 0.01, "E1 큰 쪽에서도 오른쪽 아래 10mm·같은 크기")
    tl = [mm10 / 595, mm10 / 842, w / 595, h / 842]
    r2 = stamp_core.same_corner_rect(tl, 595, 842, 300, 200)
    chk(abs(r2[0] * 300 - mm10) < 0.01 and abs(r2[1] * 200 - mm10) < 0.01, "E2 왼쪽 위는 왼쪽 위 거리 그대로")
    r3 = stamp_core.same_corner_rect([0.1, 0.1, 0.8, 0.8], 595, 842, 100, 100)
    chk(r3[2] <= 1 + 1e-9 and r3[3] <= 1 + 1e-9, "E3 쪽보다 크면 줄인다", str(r3))

    from viewer import stamp_controller as sc

    class _Stub(sc.StampMixin):
        def __init__(self):
            self.main_view = mv
            self.hist = []
            self.msgs = []

            class _S:
                def showMessage(_s, m, *_a):
                    self.msgs.append(m)
            self.status = _S()

        def _ensure_page_meta_store(self):
            return st

        def _hist_record(self, *a):
            self.hist.append(a)

        def _persist_meta(self, s):
            s.save()

        def _refresh_hidden_ui(self, p):
            pass

    stub = _Stub()
    mv.load_document(pdf, 0); app.processEvents()
    mv.set_draw_mode(True); app.processEvents()
    mv.pick_stamp(e_pdf["id"])
    pr = mv._page_view_rect()
    QTest.mouseClick(mv.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(pr.left() + pr.width() * 0.6), int(pr.top() + pr.height() * 0.85)))
    app.processEvents()
    o = mv.selected_image_object()
    sc.QInputDialog.getText = staticmethod(lambda *a, **k: ("", True))
    stub._stamp_to_pages(mv)
    p1 = st.get_images(f, 1)
    chk(len(p1) == 1 and len(st.get_images(f, 2)) == 1, "E4 모든 쪽 — 다른 두 쪽에 하나씩", str([len(st.get_images(f, p)) for p in (1, 2)]))
    if p1 and o is not None:
        R = p1[0]["rect"]
        src_right = (1 - o["rect"][0] - o["rect"][2]) * 595
        chk(abs((1 - R[0] - R[2]) * 842 - src_right) < 0.6 and abs(R[2] * 842 - o["rect"][2] * 595) < 0.6,
            "E5 다른 크기 쪽에서 같은 mm·오른쪽 거리 유지", f"{(1 - R[0] - R[2]) * 842:.1f} vs {src_right:.1f}")
        chk("pdf" in p1[0], "E6 벡터 조각도 함께 넣는다")
    chk(len(stub.hist) == 2, "E7 되돌리기 기록에 쪽마다 적는다", str(len(stub.hist)))
    stub._stamp_to_pages(mv)
    chk(len(st.get_images(f, 1)) == 1, "E8 같은 자리 같은 그림은 다시 넣지 않는다", str(len(st.get_images(f, 1))))

    # ── F 굽기 — 벡터 그대로 ───────────────────────────────────────────
    from viewer.edit_controller import EditMixin
    from viewer import pdf_mirror
    out = fitz.open(str(pdf))
    ov = pdf_mirror.overlay_doc(out)
    d1 = p1[0]
    W, H = ov[1].rect.width, ov[1].rect.height
    chk(EditMixin._bake_stamp_vector(ov[1], d1, W, H), "F1 벡터 조각을 show_pdf_page 로 얹는다")
    pdf_mirror.place(out, ov, oc=0)
    words = [w_[4] for w_ in out[1].get_text("words")]
    chk(words.count("원본대조필") >= 2, "F2 구운 쪽에 도장 글자가 글자로(원래 1 + 도장 1)", str(words))
    chk(not EditMixin._bake_stamp_vector(ov[1], dict(d1, alpha=60), W, H), "F3 투명도가 있으면 그림 길로")
    dr = dict(d1, rot=90.0)
    ov2 = pdf_mirror.overlay_doc(fitz.open(str(pdf)))
    EditMixin._bake_stamp_vector(ov2[1], dr, W, H)
    dirs = [l["dir"] for b in ov2[1].get_text("dict")["blocks"] for l in b.get("lines", [])]
    chk(any(abs(dx) < 0.01 and dy > 0.9 for dx, dy in dirs), "F4 90° 돌린 도장은 화면처럼 시계 방향(글이 아래로)", str(dirs))
    out.close()

    # ── G 창(띄우지 않고 — 모달 없음) ────────────────────────────────────
    from viewer.widgets.stamp_dialog import StampEditDialog, StampManagerDialog
    dlg = StampEditDialog(None, name="원본대조필", pdf=piece, img=stamp_core.region_png(doc[0], txt_clip),
                          width_mm=59.3, kind="pdf")
    chk(dlg.is_pdf() and dlg.rb_pdf.isEnabled(), "G1 글자층 영역은 '선명하게' 가 기본")
    dlg._ok()
    r = dlg.result_value() or {}
    chk(r.get("kind") == "pdf" and r.get("payload") == piece, "G2 [확인] — 벡터 조각 그대로")
    dlg2 = StampEditDialog(None, name="원본대조필", pdf=piece, img=stamp_core.region_png(doc[0], txt_clip), kind="pdf")
    dlg2.rb_png.setChecked(True)
    dlg2.cb_date.setChecked(True)
    dlg2._ok()
    r2 = dlg2.result_value() or {}
    chk(r2.get("kind") == "png" and r2.get("date", {}).get("on") and r2.get("payload", b"")[:4] == b"\x89PNG",
        "G3 '그림' 으로 바꾸면 바탕 투명 PNG·날짜 켬")
    two = Image.new("RGB", (400, 100), (250, 250, 245))
    ImageDraw.Draw(two).rectangle((20, 20, 160, 80), outline=(110, 60, 160), width=6)
    ImageDraw.Draw(two).rectangle((240, 20, 380, 80), outline=(110, 60, 160), width=6)
    dlg3 = StampEditDialog(None, name="명판", img=two)
    dlg3.btn_crop.setChecked(True)
    dlg3._on_box([0.0, 0.0, 0.5, 1.0])
    dlg3._ok()
    im3 = Image.open(__import__("io").BytesIO((dlg3.result_value() or {}).get("payload", b"")))
    chk(im3.width < 200 and im3.width > 100, "G5 자르기 — 사진의 두 도장 중 하나만 남긴다", str(im3.size))
    man = StampManagerDialog(None, shots=lambda: [])
    chk(man.lst.count() == len(stamp_store.items()) and man.btn_edit.isEnabled(), "G4 관리 창 목록·미리보기", str(man.lst.count()))
    doc.close()
finally:
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(sdir, ignore_errors=True)

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
