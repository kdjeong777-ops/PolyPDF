# -*- coding: utf-8 -*-
"""260913-3: PDF 꾸밈 저장 — 글쓰기 굽기의 글꼴은 **쓴 글자만** 담는다 (SOT §4.5.10).

`_bake_text_stroke` 가 `fontfile=`(맑은 고딕 13MB)로 글을 넣으면 저장 파일에 글꼴 전체가
들어가 수 MB 불어났다. `_apply_drawings_to_pdf` 가 저장 직전 `doc.subset_fonts()` 를 부른다.

  ① 실제 저장 경로(`_apply_drawings_to_pdf`)가 부분집합 없는 저장보다 훨씬 작다
  ② 모든 쪽의 렌더 픽셀이 같다 (보이는 글자가 깨지지 않음)
  ③ 텍스트 추출·검색이 같다
  ④ `subset_fonts` 가 실패해도 저장은 된다
"""
import os, sys, tempfile, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
import test_fixtures as _fx
from viewer.edit_controller import EditMixin


class _Status:
    def showMessage(self, *a, **k):
        pass


class _Host(EditMixin):
    status = _Status()
    # 260930-2(§4.7.13) 부터 꾸밈 저장이 사진도 굽는다(`_ensure_page_meta_store`) — 폴더가 없으면 사진 없음.
    #   이 둘이 없으면 AttributeError 를 저장의 except 가 받아 파일이 안 생겼다(261008-1 전체 검사에서 발견).
    _folder = None
    _page_meta = None
    # 261011-2(§4.7.16): 평탄화 내보내기는 배경 작업·서명 재서명 길을 거친다 — 검사에서는 그 자리에서 돌린다
    from viewer.sign_controller import SignMixin as _SM
    _resign_prepare, _resign_apply = _SM._resign_prepare, _SM._resign_apply
    _resign_mark, _resign_take = staticmethod(_SM._resign_mark), staticmethod(_SM._resign_take)
    _sign_unlink = staticmethod(_SM._sign_unlink)

    def _run_merge_job(self, job, title, cancellable=True):
        try:
            job(lambda *a: True)
            return {"ok": True}
        except Exception as e:                   # noqa: BLE001
            return {"ok": False, "err": str(e)}

    def _file_op_bg(self, fn, label):
        try:
            fn()
            return None
        except Exception as e:                   # noqa: BLE001
            return e


root = Path(tempfile.mkdtemp(prefix="polypdf_subset_"))
_out = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_out["path"], "PDF (*.pdf)"))
QMessageBox.information = staticmethod(lambda *a, **k: None)
_warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: _warned.append(a))

NORM = {0: [
    {"text_box": True, "rect": [0.1, 0.1, 0.8, 0.2], "text": "한글 텍스트 박스 검색어ABC",
     "size_pt": 14, "color": "#112233"},
    {"leader": True, "rect": [0.2, 0.5, 0.6, 0.56], "anchor": [0.7, 0.8],
     "text": "지시선 글", "size_pt": 12},
]}


def save_with(src, name, subset_impl=None):
    """실제 저장 경로로 저장. subset_impl 로 `Document.subset_fonts` 를 바꿔 끼운다."""
    orig = fitz.Document.subset_fonts
    if subset_impl is not None:
        fitz.Document.subset_fonts = subset_impl
    try:
        _out["path"] = str(root / name)
        _Host()._apply_drawings_to_pdf(NORM, src, with_hyperlinks=False)
    finally:
        fitz.Document.subset_fonts = orig
    return _out["path"]


def snapshot(path):
    d = fitz.open(path)
    try:
        return ([hashlib.md5(p.get_pixmap(dpi=72).samples).hexdigest() for p in d],
                [p.get_text() for p in d],
                [len(p.search_for("검색어")) for p in d])
    finally:
        d.close()


def _noop(self, *a, **k):
    return None


def _boom(self, *a, **k):
    raise RuntimeError("subset 실패 모사")


if not _fx.KRFONT:
    print("SKIP - 한글 글꼴(malgun/gulim) 없음 — 글꼴 내장 크기 검사 불가")
    sys.stdout.flush(); os._exit(0)

for label, src in (("텍스트 PDF", _fx.text_pdf()), ("스캔 PDF", _fx.scanned_pdf())):
    full = save_with(src, f"{label}_full.pdf", _noop)
    real = save_with(src, f"{label}_real.pdf")
    sz_full, sz_real = os.path.getsize(full), os.path.getsize(real)
    chk(sz_real < sz_full / 5 and sz_full - sz_real > 3_000_000,
        f"① {label}: 꾸밈 저장에 글꼴 전체가 안 들어간다", f"({sz_full:,} → {sz_real:,} B)")
    s_full, s_real = snapshot(full), snapshot(real)
    chk(s_full[0] == s_real[0], f"② {label}: 모든 쪽 렌더 픽셀 동일", f"({len(s_real[0])}쪽)")
    chk(s_full[1] == s_real[1] and "검색어" in s_real[1][0],
        f"③ {label}: 텍스트 추출 동일 (구운 글 포함)")
    chk(s_full[2] == s_real[2] and s_real[2][0] >= 1, f"③ {label}: 검색 결과 동일")

_warned.clear()
p = save_with(_fx.text_pdf(), "boom.pdf", _boom)
chk(os.path.exists(p) and not _warned and "검색어" in snapshot(p)[1][0],
    "④ subset_fonts 가 실패해도 저장된다")

src_code = Path(__file__).with_name("viewer").joinpath("edit_controller.py").read_text("utf-8")
chk(src_code.index("subset_fonts_safely(doc)") < src_code.index("doc.save(tmp, garbage=4"),
    "⑤ 저장 **직전**에 부분집합을 만든다")

# ⑥ 260913-5(§4.5.10 ②): 저장한 파일에 **새 글자로 다시** 꾸밈 저장. insert_font 는 같은 이름의
#    글꼴을 재사용하는데 그 글꼴은 이미 부분집합이다 → 이름을 비켜 가지 않으면 새 글이 사라진다.
NEW = "휘몰아쳐XYZ 뛟퓨"
NORM2 = {0: [{"text_box": True, "rect": [0.1, 0.5, 0.8, 0.6], "text": NEW, "size_pt": 14}]}
import viewer.pdf_font as _pf


def rebake(tag, subset_impl=None):
    first = save_with(_fx.text_pdf(), f"re_{tag}_1.pdf", subset_impl)
    _out["path"] = str(root / f"re_{tag}_2.pdf")
    orig = fitz.Document.subset_fonts
    if subset_impl is not None:
        fitz.Document.subset_fonts = subset_impl
    try:
        _Host()._apply_drawings_to_pdf(NORM2, first, with_hyperlinks=False)
    finally:
        fitz.Document.subset_fonts = orig
    return first, _out["path"]


a_only, re_real = rebake("real")
_, re_full = rebake("full", _noop)
s_a, s_re, s_full = snapshot(a_only), snapshot(re_real), snapshot(re_full)
chk(NEW in s_re[1][0] and "검색어" in s_re[1][0], "⑥ 다시 저장해도 새 글·옛 글이 모두 추출된다")
chk(s_re[0] == s_full[0], "⑥ 다시 저장한 렌더 픽셀 = 글꼴 전체로 저장한 것")
chk(s_re[0][0] != s_a[0][0], "⑥ 새 글이 실제로 그려졌다(첫 저장과 픽셀이 다르다)")
chk(os.path.getsize(re_real) < os.path.getsize(re_full) / 5, "⑥ 다시 저장해도 작다",
    f"({os.path.getsize(re_full):,} → {os.path.getsize(re_real):,} B)")
# 261011-2(§4.7.16): 꾸밈은 이제 **보이는 크기 임시 쪽**에 그려 XObject 로 얹는다 — 새 글꼴은 그 XObject 의 자기
#   리소스에 들어가 원본 쪽의 부분집합 krfont 와 이름이 부딪히지 않는다(종전 함정이 이 길에서는 생기지 않는다).
#   위 ⑥ 세 줄(새 글·옛 글 추출, 픽셀 = 글꼴 전체, 새 글이 그려짐)이 그대로 지킨다.
with fitz.open(re_real) as _d:
    _xo = [x for x in _d[0].get_xobjects()]
chk(len(_xo) >= 2, "⑥ 두 번 구운 꾸밈은 서로 다른 XObject(각자 글꼴 리소스)", str(len(_xo)))

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
