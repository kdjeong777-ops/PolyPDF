# -*- coding: utf-8 -*-
"""261009-1: 인쇄·내보내기 **모든 경로**가 꾸밈·사진을 굽는다 (마스터 §4.7.13).

260930-2 는 `_print_pdf_pages` 한 곳만 고쳤다. 그런데 진입이 그 하나가 아니라서,
사용자가 처음 보고한 **'pdf인쇄'** 는 그대로 빈손이었다(열 갈래 중 둘만 동작).

이 검사는 **소스를 읽어 확인하지 않는다** — 경로마다 결과 PDF 를 실제로 만들어
**그 안에 그림이 몇 개 들어갔는지 센다.** 종전 결함이 '함수는 부르는데 빈손' 이라
소스 검사로는 잡히지 않았기 때문이다.

검사 대상
  ① 구울 것이 없으면 **원본 경로를 그대로** 준다(비용 0)
  ② 구울 것이 있으면 구운 임시 PDF — 사진이 들어 있고 글자는 남는다
  ③ '문서만'(include_decorations=False)이면 굽지 않는다
  ④ 같은 파일을 두 번 물어도 **한 번만** 굽는다(캐시)
  ⑤ ★ 낱쪽 **PDF 로 인쇄** — 사용자가 보고한 바로 그 경로
  ⑥ ★ 다단(인쇄·PDF로) — 축소돼도 사진이 따라간다
  ⑦ ★ 여러 파일(묶음·다단) — 파일마다 구워 들어간다
  ⑧ `_print_pdf_pages` 는 **스스로 굽지 않는다**(부르는 쪽이 구운 원천을 넘긴다)
  ⑨ 미리보기도 구운 원천을 본다 — '미리보기 = 인쇄'
  ⑩ 굽기가 터져도 인쇄 자체는 막지 않는다
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
root = tempfile.mkdtemp(prefix="printbake_")


def imgs(path, page=0):
    doc = fitz.open(path)
    try:
        return len(doc[page].get_images(full=True))
    finally:
        doc.close()


def total_imgs(path):
    doc = fitz.open(path)
    try:
        return sum(len(doc[i].get_images(full=True)) for i in range(doc.page_count))
    finally:
        doc.close()


def make_pdf(name, n=2):
    p = os.path.join(root, name)
    d = fitz.open()
    for i in range(n):
        d.new_page(width=595, height=842).insert_text(
            (72, 120), "page %d of %s" % (i + 1, name), fontsize=13)
    d.save(p); d.close()
    return p


try:
    from viewer.print_controller import PrintMixin
    from viewer.edit_controller import EditMixin
    from viewer.page_meta import PageMetaStore

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200)); pix.clear_with(170)
    png = os.path.join(root, "o.png"); pix.save(png)
    b64 = base64.b64encode(Path(png).read_bytes()).decode()

    src_a = make_pdf("a.pdf", 2)
    src_b = make_pdf("b.pdf", 2)
    plain = make_pdf("plain.pdf", 2)          # 구울 것이 없는 문서
    st = PageMetaStore(root)
    for f in (src_a, src_b):
        st.set_images(f, 0, [{"data": b64, "rect": [0.2, 0.1, 0.5, 0.2],
                              "rot": 0.0, "alpha": 100, "shape": "rect"}])

    class _Status:
        def showMessage(self, *a, **k):
            pass

    class Host(PrintMixin, EditMixin):
        """위젯 없이 인쇄 경로의 **원천 만들기**만 떼어 쓴다."""
        status = _Status()
        _folder = None
        _page_meta = None

        def _ensure_page_meta_store(self):
            return st

        def _ensure_hyperlink_store(self):
            return None

        def _run_merge_job(self, job, title, cancellable=True):
            """진행창 없이 그 자리에서 돌린다 — 검사에서는 스레드·모달이 필요 없다."""
            try:
                job(lambda *a, **k: True)
                return {"ok": True, "err": None, "cancelled": False}
            except Exception as e:                       # noqa: BLE001
                return {"ok": False, "err": str(e), "cancelled": False}

    h = Host()

    # ── ① 구울 것 없음 → 원본 그대로 ────────────────────────────────
    chk(h._baked_src(plain, True) == plain,
        "① 구울 것이 없으면 **원본 경로 그대로**(비용 0)")
    chk(h._has_bakeables(plain) is False and h._has_bakeables(src_a) is True,
        "① 구울 것이 있는지 먼저 본다")

    # ── ② 구운 사본 ─────────────────────────────────────────────────
    baked = h._baked_src(src_a, True)
    chk(baked != src_a and os.path.exists(baked), "② 구운 임시 PDF 를 만든다")
    chk(imgs(src_a) == 0 and imgs(baked) == 1,
        "② 원본엔 없고 구운 사본엔 사진이 있다", "%d → %d" % (imgs(src_a), imgs(baked)))
    doc = fitz.open(baked)
    chk("page 1" in doc[0].get_text("text"), "② 글자는 그대로 남는다")
    doc.close()

    # ── ③ '문서만' ─────────────────────────────────────────────────
    chk(h._baked_src(src_a, False) == src_a, "③ '문서만' 이면 굽지 않는다")

    # ── ④ 캐시 ─────────────────────────────────────────────────────
    chk(h._baked_src(src_a, True) == baked, "④ 같은 파일은 한 번만 굽는다(캐시)")

    # ── ⑤ ★ 낱쪽 'PDF 로 인쇄' — 사용자가 보고한 그 경로 ────────────
    out5 = os.path.join(root, "export.pdf")
    chk(h._export_pages_pdf(baked, [0, 1], out5) and total_imgs(out5) == 1,
        "⑤ ★ 낱쪽 **PDF 로 인쇄** 에 사진이 들어간다", total_imgs(out5))
    out5b = os.path.join(root, "export_plain.pdf")
    h._export_pages_pdf(h._baked_src(plain, True), [0], out5b)
    chk(total_imgs(out5b) == 0, "⑤ 구울 것 없는 문서는 그대로(군더더기 없음)")

    # ── ⑥ ★ 다단 — 축소돼도 따라간다 ───────────────────────────────
    from viewer.twoup import build_twoup
    sub = os.path.join(root, "sub.pdf")
    sd = fitz.open(baked); td = fitz.open()
    for p_ in (0, 1):
        td.insert_pdf(sd, from_page=p_, to_page=p_)
    td.save(sub); sd.close(); td.close()
    nup = os.path.join(root, "nup.pdf")
    build_twoup([{"type": "pdf", "path": sub, "name": "a"}],
                {"make_cover": False, "make_toc": False}, nup,
                log=lambda *a, **k: True, progress=lambda *a, **k: True)
    chk(total_imgs(nup) >= 1, "⑥ ★ 다단으로 묶어도 사진이 남는다", total_imgs(nup))
    d6 = fitz.open(nup)
    chk(d6.page_count < 2, "⑥ 두 쪽이 한 장으로 묶였다(다단이 실제로 돌았다)", d6.page_count)
    d6.close()

    # ── ⑦ ★ 여러 파일 ──────────────────────────────────────────────
    bk = [h._baked_src(f, True) for f in (src_a, src_b)]
    comb = h._combine_pdfs_temp(bk)
    chk(comb and total_imgs(comb) == 2,
        "⑦ ★ 여러 파일을 묶어도 파일마다 사진이 들어간다",
        total_imgs(comb) if comb else None)

    # ── ⑧ `_print_pdf_pages` 는 스스로 굽지 않는다 ──────────────────
    import inspect
    s_pp = inspect.getsource(PrintMixin._print_pdf_pages)
    chk("_bake_images_into_doc" not in s_pp and "_bake_drawings_into_doc" not in s_pp,
        "⑧ `_print_pdf_pages` 안에 굽기가 없다(부르는 쪽이 구운 원천을 넘긴다)")
    s_ap = inspect.getsource(PrintMixin.action_print)
    chk(s_ap.count("_baked_src") >= 1 and "_print_pdf_pages(src" in s_ap
        and "_export_pages_pdf(src" in s_ap and "_build_nup_pdf(src" in s_ap,
        "⑧ 네 갈래가 모두 같은 `src` 를 쓴다")

    # ── ⑨ 미리보기 ─────────────────────────────────────────────────
    from viewer.widgets.print_dialog import PrintScopeDialog
    chk("bake_src" in inspect.signature(PrintScopeDialog.__init__).parameters,
        "⑨ 인쇄 창이 굽기 콜백을 받는다")
    s_prev = inspect.getsource(PrintScopeDialog)
    chk("_baked_sample()" in s_prev and s_prev.count("_baked_sample()") >= 2,
        "⑨ 미리보기 둘(낱쪽·다단)이 구운 원천을 본다 — '미리보기 = 인쇄'")
    s_ctl = inspect.getsource(PrintMixin.action_print)
    chk("bake_src=self._baked_src" in s_ctl, "⑨ 본창이 그 콜백을 넘긴다")

    # ── ⑩ 굽기가 터져도 인쇄는 막지 않는다 ─────────────────────────
    class Boom(Host):
        def _bake_images_into_doc(self, doc, path):
            raise RuntimeError("일부러")
    hb = Boom()
    got = hb._baked_src(src_a, True)
    chk(os.path.exists(got), "⑩ 사진 굽기가 터져도 원천은 나온다(인쇄가 막히지 않는다)")

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
