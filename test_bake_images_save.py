# -*- coding: utf-8 -*-
"""260930-2: 삽입 사진 굽기 · 일반뷰어용 저장 · 저장 메뉴 (마스터 §4.7.13).

사용자 보고·요청
  - 메인화면에 붙인 사진이 인쇄 '문서 + 주석·꾸미기' 로 PDF 인쇄해도 **안 보인다**
  - '파일' 메뉴에 저장을 넣고, **일반뷰어용**(플래튼) 저장을 더해 다른 프로그램에서도
    꾸밈·사진이 보이게
  - **책갈피 우클릭**에도 저장 관련 기능을

원인은 하나였다 — 굽기가 **선·도형·글·하이퍼링크만** 굽고 사진(`page_meta.images`)을
빠뜨렸다. 인쇄와 'PDF 꾸밈 저장' 이 같은 구멍을 공유했다.

검사 대상
  ① 사진이 없던 쪽에 **그림이 하나 생긴다**(굽기 전에는 없다)
  ② 자리 — 정규화 rect 대로 그 자리에 간다
  ③ 회전한 사진은 **테두리 상자**에 맞춰 들어간다(모서리가 잘리지 않는다)
  ④ 글자는 **그대로 남는다**(일반뷰어용 = 글자 살리고 굽기, 사용자 결정)
  ⑤ 인쇄 경로('문서 + 주석·꾸미기')가 사진을 굽는다 / '문서만' 이면 굽지 않는다
  ⑥ 사진만 있어도 '일반뷰어용으로 저장' 이 막히지 않는다(종전에는 돌아섰다)
  ⑦ 파일 메뉴에 저장 세 항목 · 책갈피 우클릭에 저장 항목
"""
import os, sys, tempfile, shutil, base64
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

fails = []


def chk(ok, what, got=""):
    print(("PASS - " if ok else "FAIL - ") + what + (" " + str(got) if got else ""))
    if not ok:
        fails.append(what)


app = QApplication.instance() or QApplication([])
root = tempfile.mkdtemp(prefix="bake_img_")

try:
    # 글자가 있는 2쪽 PDF
    src = os.path.join(root, "doc.pdf")
    d = fitz.open()
    for i in range(2):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 120), "hello page %d" % (i + 1), fontsize=14)
    d.save(src)
    d.close()

    # 삽입 사진 하나(빨간 네모) — page_meta 형식(base64 PNG + 정규화 rect)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 100))
    pix.clear_with(200)
    png_path = os.path.join(root, "o.png")
    pix.save(png_path)
    b64 = base64.b64encode(Path(png_path).read_bytes()).decode()

    from viewer.page_meta import PageMetaStore
    # 저장소는 **폴더**를 받는다 — 그 아래 파일만 키가 잡힌다(상대경로 키).
    st = PageMetaStore(root)
    st.set_images(src, 0, [{"data": b64, "rect": [0.25, 0.10, 0.50, 0.20],
                            "rot": 0.0, "alpha": 100, "shape": "rect"}])
    st.set_images(src, 1, [{"data": b64, "rect": [0.30, 0.40, 0.40, 0.15],
                            "rot": 30.0, "alpha": 80, "shape": "round"}])

    # `_bake_images_into_doc` 만 떼어 쓴다 — 위젯 없이 그대로 부를 수 있어야 한다.
    from viewer.edit_controller import EditMixin as _EM
    host = _EM.__new__(_EM)
    host._ensure_page_meta_store = lambda: st

    # ── ① 굽기 전/후 ────────────────────────────────────────────────
    doc = fitz.open(src)
    chk(len(doc[0].get_images(full=True)) == 0, "① 굽기 전에는 쪽에 그림이 없다")
    n = _EM._bake_images_into_doc(host, doc, src)
    chk(n == 2, "① 두 쪽의 사진을 구웠다", n)
    chk(len(doc[0].get_images(full=True)) == 1, "① 굽고 나면 그림이 생긴다",
        len(doc[0].get_images(full=True)))

    # ── ② 자리 ─────────────────────────────────────────────────────
    xref = doc[0].get_images(full=True)[0][0]
    r = doc[0].get_image_rects(xref)[0]
    chk(abs(r.x0 - 0.25 * 595) < 2 and abs(r.y0 - 0.10 * 842) < 2
        and abs(r.width - 0.50 * 595) < 2 and abs(r.height - 0.20 * 842) < 2,
        "② 정규화 rect 그대로 그 자리에", [round(v, 1) for v in (r.x0, r.y0, r.width, r.height)])

    # ── ③ 회전 ─────────────────────────────────────────────────────
    import math
    xr2 = doc[1].get_images(full=True)[0][0]
    r2 = doc[1].get_image_rects(xr2)[0]
    w_pt, h_pt = 0.40 * 595, 0.15 * 842
    th = math.radians(30.0)
    bw = abs(w_pt * math.cos(th)) + abs(h_pt * math.sin(th))
    bh = abs(w_pt * math.sin(th)) + abs(h_pt * math.cos(th))
    chk(abs(r2.width - bw) < 2 and abs(r2.height - bh) < 2,
        "③ 회전한 사진은 **테두리 상자**에 맞춰 들어간다(모서리 안 잘림)",
        "%.0fx%.0f (기대 %.0fx%.0f)" % (r2.width, r2.height, bw, bh))
    chk(r2.width > w_pt, "③ 돌렸으니 폭이 원래보다 넓다")

    # ── ④ 글자 보존 ────────────────────────────────────────────────
    chk("hello page 1" in doc[0].get_text("text"),
        "④ 글자는 **그대로 남는다**(검색·복사가 계속 된다)")
    doc.close()

    # ── ⑤ 인쇄 경로가 사진을 굽는가 ────────────────────────────────
    import inspect
    from viewer import print_controller as pc
    src_pr = inspect.getsource(pc)
    # 261009-1(§4.7.13): 굽기가 `_print_pdf_pages` 안에서 **원천 만들기**(`_baked_src`)로
    #   옮겨 갔다 — 그래야 다단·여러 파일·PDF로 인쇄까지 같이 굽힌다. 경로별로 실제 결과에
    #   사진이 들어가는지는 `test_print_bake_paths.py` 가 센다. 여기서는 자리만 확인한다.
    i_bake = src_pr.find("def _baked_src")
    seg = src_pr[i_bake:i_bake + 2500]
    chk(i_bake > 0 and "_bake_images_into_doc" in seg,
        "⑤ 인쇄 원천 만들기(`_baked_src`)가 사진도 굽는다")
    chk("include_decorations" in seg,
        "⑤ '문서만' 이면 굽지 않는다(같은 함수가 받는다)")

    # ── ⑥ 사진만 있어도 저장이 막히지 않는다 ───────────────────────
    from viewer import edit_controller as ec
    s_act = inspect.getsource(ec.EditMixin._action_save_decorated_pdf)
    chk("pages_with_images" in s_act and "has_img" in s_act,
        "⑥ 사진만 있어도 '구울 것이 있다' 로 본다")
    chk("file_path" in inspect.signature(ec.EditMixin._action_save_decorated_pdf).parameters,
        "⑥ 다른 파일에도 걸 수 있다(책갈피 우클릭용)")
    s_apply = inspect.getsource(ec.EditMixin._apply_drawings_to_pdf)
    chk("_bake_images_into_doc" in s_apply, "⑥ 일반뷰어용 저장이 사진을 굽는다")
    chk("garbage=4" in s_apply and "deflate=True" in s_apply,
        "⑥ 저장 옵션은 관례대로(마스터 §4.5.10)")

    # ── ⑦ 메뉴 ─────────────────────────────────────────────────────
    from viewer import app as appmod
    s_app = inspect.getsource(appmod)
    i_file = s_app.find('m_file = bar.addMenu')
    seg_f = s_app[i_file:i_file + 2000]
    for label in ("저장(PolyPDF용)", "다른 이름으로 저장", "저장(일반뷰어용)"):   # 261008-1 이름
        chk(label in seg_f, "⑦ 파일 메뉴에 '%s'" % label)
    chk("_force_save_as" in s_app,
        "⑦ '다른 이름으로' 는 💾 와 같은 길에 깃발만 세운다(저장 규칙 한 벌)")
    from viewer.widgets import bookmark_tree as bt
    s_bt = inspect.getsource(bt)
    chk("flattenFileRequested" in s_bt and "저장(일반뷰어용)" in s_bt,
        "⑦ 책갈피 우클릭에 저장 항목")
    chk("self.flattenFileRequested.emit(_dir_target)" in s_bt,   # 261008-1: 책갈피 행이면 그 파일
        "⑦ ★ **누른 그 파일**에 작용한다(사용자 결정)")

except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("=== ALL PASS ===")
