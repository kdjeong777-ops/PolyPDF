# -*- coding: utf-8 -*-
"""260905(발표 SOT §4.1·§4.2): 좌우 2쪽 보기·맞쪽 / 크롭 4방향·홀짝 / 중앙겹침 상부 띠."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QPoint, QEvent
from PyQt6.QtGui import QMouseEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_dual_"))
d = fitz.open()
for i in range(6):
    pg = d.new_page(width=400, height=600)
    pg.insert_text((40, 100), f"page {i}")
d.save(str(tmp / "D.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.presentation import PresentationWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS

pw = PresentationWindow(str(tmp / "D.pdf"), 0, None,
                        pens=[dict(p) for p in MV_DEFAULT_PENS],
                        eraser_widths=[12, 30], line_mode=2)
pw.resize(1200, 700); pw.show(); app.processEvents()

# --- 1) 상호배타 -------------------------------------------------------------
chk(pw._split_mode, "세로 페이지 → 상하2분할 기본 ON")
dual_emit, split_emit = [], []
pw.dualModeChanged.connect(lambda v: dual_emit.append(v))
pw.splitModeChanged.connect(lambda v: split_emit.append(v))
pw.set_dual(True)
chk(pw._dual_mode and not pw._split_mode, "좌우 2쪽 ON → 상하2분할 자동 해제")
chk(not pw._page_is_split(), "좌우 2쪽 중에는 _page_is_split() False")
chk(dual_emit == [True] and split_emit == [False], "토글 시그널 발신",
    f"dual={dual_emit} split={split_emit}")
pw.set_split(True)
chk(pw._split_mode and not pw._dual_mode, "상하2분할 ON → 좌우 2쪽 자동 해제")
pw.set_dual(True)

# --- 2) 펼침 산정 ------------------------------------------------------------
pw._go(0); app.processEvents()
chk(pw._dual_pages() == (0, 1), "맞쪽 OFF: 0쪽 → (0,1)", str(pw._dual_pages()))
pw._next(); app.processEvents()
chk(pw._dual_pages() == (2, 3), "다음 → (2,3)", str(pw._dual_pages()))
pw._next(); app.processEvents()
chk(pw._dual_pages() == (4, 5), "다음 → (4,5)", str(pw._dual_pages()))
pw._prev(); app.processEvents()
chk(pw._dual_pages() == (2, 3), "이전 → (2,3)", str(pw._dual_pages()))

face_emit = []
pw.facingChanged.connect(lambda v: face_emit.append(v))
pw.set_facing(True); pw._go(0); app.processEvents()
chk(face_emit == [True], "맞쪽 시그널 발신", str(face_emit))
chk(pw._dual_pages() == (None, 0), "맞쪽 ON: 첫 펼침은 (빈칸, 0)", str(pw._dual_pages()))
pw._next(); app.processEvents()
chk(pw._dual_pages() == (1, 2), "맞쪽 다음 → (1,2)", str(pw._dual_pages()))
pw._next(); app.processEvents()
chk(pw._dual_pages() == (3, 4), "맞쪽 다음 → (3,4)", str(pw._dual_pages()))
pw._prev(); app.processEvents()
chk(pw._dual_pages() == (1, 2), "맞쪽 이전 → (1,2)", str(pw._dual_pages()))
pw._prev(); app.processEvents()
chk(pw._dual_pages() == (None, 0), "맞쪽 이전 → 첫 펼침", str(pw._dual_pages()))
pw.set_facing(False)

# --- 3) 렌더 + 쪽별 화면 사각형 ----------------------------------------------
pw._go(0); pw._render(); app.processEvents()
chk(set(pw._dual_rects.keys()) == {0, 1}, "렌더가 두 쪽 사각형 기록", str(sorted(pw._dual_rects)))
rx0 = pw._dual_rects[0]; rx1 = pw._dual_rects[1]
chk(rx0[0] + rx0[2] <= rx1[0] + 1, "좌측 쪽이 우측 쪽보다 왼쪽", f"{rx0} {rx1}")
pm = pw._label.pixmap()
chk(pm is not None and not pm.isNull() and pm.width() <= 1200 and pm.height() <= 700,
    "합성 픽스맵이 화면을 넘지 않음", f"{pm.width()}x{pm.height()}" if pm else "None")
chk(pw._shown_pages() == [0, 1], "_shown_pages = 보이는 두 쪽", str(pw._shown_pages()))

# --- 4) 그리기 귀속 + 잘림 + 정규화 ------------------------------------------
def draw(x0, y0, x1, y1):
    pw.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x0, y0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    pw.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x1, y1),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    pw.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x1, y1),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

pw._set_pen(0); pw.set_line_mode(2)
cx0 = rx0[0] + rx0[2] / 2.0; cy0 = rx0[1] + rx0[3] / 2.0
cx1 = rx1[0] + rx1[2] / 2.0
draw(cx0, cy0, cx0 + 40, cy0 + 40)
chk(len(pw._strokes.get(0, [])) == 1 and not pw._strokes.get(1),
    "좌측 칸에 그린 선 → 0쪽 귀속", str({k: len(v) for k, v in pw._strokes.items()}))
draw(cx1, cy0, cx1 + 40, cy0 + 40)
chk(len(pw._strokes.get(1, [])) == 1, "우측 칸에 그린 선 → 1쪽 귀속",
    str({k: len(v) for k, v in pw._strokes.items()}))
st = pw._strokes[0][0]
chk("rect" in st, "스트로크에 그릴 당시 사각형 저장")
# 반대 칸까지 끌어도 귀속된 쪽 영역에서 잘린다
draw(cx0, cy0 + 60, cx1 + 100, cy0 + 60)
last = pw._strokes[0][-1]
chk(max(p.x() for p in last["points"]) <= rx0[0] + rx0[2] + 1,
    "반대 칸으로 넘어간 부분은 잘림",
    f"maxx={max(p.x() for p in last['points'])} limit={rx0[0]+rx0[2]}")
norm = pw._normalized_strokes()
allpts = [c for pg in norm.values() for s2 in pg for c in s2["points"]]
chk(norm and all(0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 for a, b in allpts),
    "정규화 좌표 0..1", str(sorted(norm)))
# 우측 칸 선은 좌측 근처가 아니라 자기 쪽 안에서 정규화된다(반쪽 크기로 어긋나지 않음)
chk(0.2 <= norm[1][0]["points"][0][0] <= 0.8, "우측 쪽 선이 제 쪽 안에서 정규화",
    str(norm[1][0]["points"][0]))
# 지우개는 커서가 있는 쪽만 건드린다
pw._set_eraser(1)
pw._erase_at(QPoint(int(cx1), int(cy0)))
chk(not pw._strokes.get(1) and len(pw._strokes.get(0, [])) == 2,
    "우측 칸 지우기가 좌측 쪽 선을 건드리지 않음",
    str({k: len(v) for k, v in pw._strokes.items()}))

# --- 5) 크롭 4방향 + 홀짝 ----------------------------------------------------
pw.set_dual(False)
crop = {"v": (0.0, 0.0, 0.0, 0.0)}
pw._crop_resolver = lambda path, page0: crop["v"]
pw._pm_cache = {}
pw._go(0); pw._render(); app.processEvents()
base = pw._label.pixmap()
bw, bh = base.width(), base.height()
crop["v"] = (10.0, 10.0, 20.0, 20.0)
pw._pm_cache = {}
pw._render(); app.processEvents()
cut = pw._label.pixmap()
chk(cut.width() <= 1200 and cut.height() <= 700, "크롭 후에도 화면 안",
    f"{cut.width()}x{cut.height()}")
# 크롭한 만큼 실제로 커진다(§4.2.2): 남는 비율이 세로로 길어져 화면 높이를 꽉 채운다
chk(cut.height() >= bh - 2, "크롭해도 화면을 계속 채움(확대 적용)",
    f"base={bw}x{bh} cut={cut.width()}x{cut.height()}")
chk(abs(cut.width() / cut.height() - (400 * 0.6) / (600 * 0.8)) < 0.02,
    "크롭 후 비율이 남은 영역과 일치", str(round(cut.width() / cut.height(), 4)))

from viewer.page_meta import PageMetaStore
st2 = PageMetaStore(tmp)
f = str(tmp / "D.pdf")
st2.set_global_crop(f, 5, 6, 7, 8)
chk(st2.get_global_crop(f) == (5.0, 6.0, 7.0, 8.0), "전역 4방향 크롭 왕복",
    str(st2.get_global_crop(f)))
chk(st2.get_crop(f, 0) == (5.0, 6.0, 7.0, 8.0), "홀짝 꺼짐 → 전역 좌우")
st2.set_oddeven_crop(f, True, (11, 12), (13, 14))
chk(st2.get_crop(f, 0) == (5.0, 6.0, 11.0, 12.0), "1쪽(홀수) → 홀수 좌우",
    str(st2.get_crop(f, 0)))
chk(st2.get_crop(f, 1) == (5.0, 6.0, 13.0, 14.0), "2쪽(짝수) → 짝수 좌우",
    str(st2.get_crop(f, 1)))
st2.set_page_crop(f, 1, 1, 2, 3, 4)
chk(st2.get_crop(f, 1) == (1.0, 2.0, 3.0, 4.0), "페이지 개별 크롭이 홀짝보다 우선",
    str(st2.get_crop(f, 1)))
st2.reset_crop(f)
chk(st2.get_crop(f, 0) == (0.0, 0.0, 0.0, 0.0)
    and st2.get_oddeven_crop(f)[0] is False, "초기화가 홀짝까지 지움")
# v1(2원소) 사이드카 하위호환
st2._data["files"][st2._key(f)]["crop_global"] = [9, 9]
chk(st2.get_global_crop(f) == (9.0, 9.0, 0.0, 0.0), "v1 2원소 크롭 하위호환",
    str(st2.get_global_crop(f)))

# --- 6) 중앙겹침 — 상·하 띠 알파가 다르다(§4) --------------------------------
chk(pw.OVERLAP_ALPHA_UPPER < pw.OVERLAP_ALPHA_LOWER,
    "상부 띠가 하부 띠보다 연함",
    f"upper={pw.OVERLAP_ALPHA_UPPER} lower={pw.OVERLAP_ALPHA_LOWER}")
crop["v"] = (0.0, 0.0, 0.0, 0.0)
pw._pm_cache = {}
pw.set_split(True); pw.set_overlap_pct(20)
pw._split_half = 0; pw._render(); app.processEvents()
up = pw._label.pixmap().toImage()
pw._split_half = 1; pw._render(); app.processEvents()
lo = pw._label.pixmap().toImage()

def mean_lum(img, y):
    xs = range(0, img.width(), max(1, img.width() // 40))
    vals = [img.pixelColor(x, y).lightness() for x in xs]
    return sum(vals) / len(vals)

ub, uc = mean_lum(up, up.height() - 3), mean_lum(up, up.height() // 2)
lb, lc = mean_lum(lo, 3), mean_lum(lo, lo.height() // 2)
chk(ub < uc, "상부 반쪽 맨 아래에 겹침 띠(어두움)", f"band={ub:.1f} mid={uc:.1f}")
chk(lb < lc, "하부 반쪽 맨 위에 겹침 띠(어두움)", f"band={lb:.1f} mid={lc:.1f}")
chk(lb < ub, "하부 띠가 상부 띠보다 진함", f"upper={ub:.1f} lower={lb:.1f}")

# --- 7) 보기 설정 다이얼로그 -------------------------------------------------
from viewer.widgets.view_settings_dialog import ViewSettingsDialog
dlg = ViewSettingsDialog(page_no=1, global_crop=(5, 6, 7, 8), page_crop=(5, 6, 7, 8),
                         has_page_crop=False, oddeven=(True, (11, 12), (13, 14)),
                         preview_pages=[0, 1],
                         renderer=(lambda p, dpi: pw._render_pixmap(dpi, p)))
chk(dlg.effective_crop(0) == (5, 6, 11, 12), "다이얼로그 홀수쪽 유효크롭",
    str(dlg.effective_crop(0)))
chk(dlg.effective_crop(1) == (5, 6, 13, 14), "다이얼로그 짝수쪽 유효크롭",
    str(dlg.effective_crop(1)))
chk(not dlg.sp_gl.isEnabled(), "홀짝 켜짐 → 전역 좌·우 입력 비활성")
dlg.chk_page.setChecked(True)
dlg.sp_pt.setValue(30)
chk(dlg.effective_crop(0)[0] == 30, "페이지 개별 크롭이 우선", str(dlg.effective_crop(0)))
dlg.resize(800, 600); dlg.show(); app.processEvents()
pv = dlg.preview.pixmap()
chk(pv is not None and not pv.isNull(), "미리보기 픽스맵 생성",
    f"{pv.width()}x{pv.height()}" if pv else "None")
chk(pv.width() <= dlg.preview.width() and pv.height() <= dlg.preview.height(),
    "미리보기가 영역 안에 비율 유지로 들어감")
r = dlg.result_values()
chk(r["oddeven_enabled"] and r["odd"] == (11, 12) and r["even"] == (13, 14)
    and r["page_enabled"], "result_values 왕복", str(r))

# 미리보기 쪽 이동(§4.2.3) — 좌우 2쪽이면 펼침 단위
pw.set_split(False); pw.set_dual(True); pw.set_facing(False)
pw._crop_resolver = lambda path, page0: (0.0, 0.0, 0.0, 0.0)
pw._go(0); app.processEvents()
dlg3 = ViewSettingsDialog(page_no=1, global_crop=(0, 0, 0, 0), page_crop=(0, 0, 0, 0),
                          has_page_crop=False, oddeven=(False, (0, 0), (0, 0)),
                          preview_pages=pw.preview_pages_for(0),
                          renderer=(lambda p, dpi: pw._render_pixmap(dpi, p)),
                          pages_for=pw.preview_pages_for, step=pw.preview_step)
dlg3.resize(900, 660); dlg3.show(); app.processEvents()
chk(dlg3._preview_pages == [0, 1], "미리보기 첫 펼침", str(dlg3._preview_pages))
chk(not dlg3.btn_prev.isEnabled() and dlg3.btn_next.isEnabled(),
    "첫 펼침에서 이전 비활성·다음 활성")
dlg3._step(+1); app.processEvents()
chk(dlg3._preview_pages == [2, 3], "미리보기 다음 → 3·4쪽", str(dlg3._preview_pages))
chk("3" in dlg3.lbl_preview_title.text() and "4" in dlg3.lbl_preview_title.text(),
    "미리보기 라벨에 쪽번호 표시", dlg3.lbl_preview_title.text())
dlg3._step(-1); app.processEvents()
chk(dlg3._preview_pages == [0, 1], "미리보기 이전 → 1·2쪽", str(dlg3._preview_pages))
chk(dlg3._page0 == 0, "쪽을 옮겨도 '현재 페이지' 크롭 그룹은 고정")
w0 = dlg3.width()
dlg3._autofit_left = 3
dlg3._update_preview(); app.processEvents()
chk(dlg3.width() >= w0, "폭 자동 맞춤은 넓히기만 함", f"{w0} -> {dlg3.width()}")
chk(dlg3._autofit_left >= 0 and not dlg3._autofit_busy, "폭 자동 맞춤 되먹임 가드 정상")
dlg3.close()

# --- 8) 개별 쪽 크롭: 체크 + '적용' 버튼(§4.2.3.1) ---------------------------
stored = {}
dlg4 = ViewSettingsDialog(page_no=1, global_crop=(4, 4, 0, 0), page_crop=(4, 4, 0, 0),
                          has_page_crop=False, oddeven=(False, (0, 0), (0, 0)),
                          preview_pages=pw.preview_pages_for(0),
                          renderer=(lambda p, dpi: pw._render_pixmap(dpi, p)),
                          pages_for=pw.preview_pages_for, step=pw.preview_step,
                          page_crop_of=(lambda p: stored.get(p)))
dlg4.resize(900, 660); dlg4.show(); app.processEvents()
chk(not dlg4.btn_apply_page.isVisible(), "'적용' 버튼은 체크 전에는 숨김")
dlg4.chk_page.setChecked(True); app.processEvents()
chk(dlg4.btn_apply_page.isVisible(), "체크하면 '적용' 버튼이 보임")
chk("p.1" in dlg4.grp_page.title(), "개별 쪽 그룹 제목이 현재 쪽 표시", dlg4.grp_page.title())
dlg4.sp_pt.setValue(20); dlg4.sp_pl.setValue(10)
chk(dlg4.effective_crop(0) == (20, 4, 10, 0), "편집 중인 쪽은 스핀 값이 실시간 반영",
    str(dlg4.effective_crop(0)))
chk(dlg4.effective_crop(2) == (4, 4, 0, 0), "다른 쪽은 아직 전역")
dlg4._on_apply_page()
chk(dlg4._page_overrides == {0: (20, 4, 10, 0)}, "'적용'이 현재 쪽에 고정",
    str(dlg4._page_overrides))
chk("1" in dlg4.lbl_pinned.text(), "고정된 쪽 목록 표시", dlg4.lbl_pinned.text())
# 쪽을 옮긴 뒤 다시 '적용' → 그 쪽에도 적용
dlg4._step(+1); app.processEvents()
chk(dlg4._cur == 2 and "p.3" in dlg4.grp_page.title(), "쪽 이동 후 그룹 제목 갱신",
    dlg4.grp_page.title())
chk(dlg4.chk_page.isChecked(), "이동해도 체크 유지(연속 적용 흐름)")
dlg4.sp_pt.setValue(30)
dlg4._on_apply_page()
chk(dlg4._page_overrides == {0: (20, 4, 10, 0), 2: (30, 4, 10, 0)},
    "이동한 쪽에도 '적용' 가능", str(dlg4._page_overrides))
chk(dlg4.effective_crop(0) == (20, 4, 10, 0), "먼저 고정한 쪽 값이 보존됨",
    str(dlg4.effective_crop(0)))
r4 = dlg4.result_values()
chk(r4["page_crops"] == {0: (20, 4, 10, 0), 2: (30, 4, 10, 0)},
    "확인 시 고정분 + 편집 중인 쪽 저장", str(r4["page_crops"]))
chk(r4["page_clears"] == [], "지울 쪽 없음", str(r4["page_clears"]))
# 체크를 끄면 그 쪽은 지움 대상
dlg4.chk_page.setChecked(False); app.processEvents()
chk(not dlg4.btn_apply_page.isVisible(), "체크 해제하면 '적용' 버튼 숨김")
r4b = dlg4.result_values()
chk(2 in r4b["page_clears"] and 2 not in r4b["page_crops"],
    "체크 해제한 쪽은 개별 크롭 삭제 대상", str(r4b))
chk(r4b["page_crops"] == {0: (20, 4, 10, 0)}, "다른 고정분은 유지", str(r4b["page_crops"]))
# 저장된 개별 크롭이 있는 쪽으로 옮기면 그 값을 불러온다
stored[4] = (7, 8, 9, 10)
dlg4._step(+1); app.processEvents()
chk(dlg4._cur == 4 and dlg4.chk_page.isChecked()
    and dlg4._live_page_crop() == (7, 8, 9, 10),
    "저장된 개별 크롭이 있는 쪽으로 이동하면 불러옴", str(dlg4._live_page_crop()))
dlg4.close()

# --- 9) 홀짝 체크 시 전역 좌·우를 초기값으로(§4.2.3.2) -----------------------
dlg5 = ViewSettingsDialog(page_no=1, global_crop=(3, 3, 12, 5), page_crop=(3, 3, 12, 5),
                          has_page_crop=False, oddeven=(False, (0, 0), (0, 0)),
                          preview_pages=[0],
                          renderer=(lambda p, dpi: pw._render_pixmap(dpi, p)))
dlg5.show(); app.processEvents()
chk((dlg5.sp_ol.value(), dlg5.sp_or.value()) == (0, 0), "열 때는 저장값 그대로(0)")
dlg5.chk_oe.setChecked(True); app.processEvents()
chk((dlg5.sp_ol.value(), dlg5.sp_or.value(), dlg5.sp_el.value(), dlg5.sp_er.value())
    == (12, 5, 12, 5), "홀짝 체크 → 전역 좌·우로 채움",
    str((dlg5.sp_ol.value(), dlg5.sp_or.value(), dlg5.sp_el.value(), dlg5.sp_er.value())))
dlg5.close()
# 이미 값이 있으면 덮어쓰지 않는다
dlg6 = ViewSettingsDialog(page_no=1, global_crop=(3, 3, 12, 5), page_crop=(3, 3, 12, 5),
                          has_page_crop=False, oddeven=(True, (18, 2), (2, 18)),
                          preview_pages=[0],
                          renderer=(lambda p, dpi: pw._render_pixmap(dpi, p)))
dlg6.show(); app.processEvents()
dlg6.chk_oe.setChecked(False); app.processEvents()
dlg6.chk_oe.setChecked(True); app.processEvents()
chk((dlg6.sp_ol.value(), dlg6.sp_or.value()) == (18, 2),
    "이미 값이 있으면 껐다 켜도 덮어쓰지 않음",
    str((dlg6.sp_ol.value(), dlg6.sp_or.value())))
dlg6.close()

# 화면 채움(§4.1.3) — 세 모드 모두에서 화면을 꽉 채운다
chk(not pw._fill_screen, "화면 채움 기본 꺼짐")
crop["v"] = (0.0, 0.0, 0.0, 0.0)
for label, setup in (("단일", lambda: (pw.set_dual(False), pw.set_split(False))),
                     ("상하2분할", lambda: (pw.set_dual(False), pw.set_split(True))),
                     ("좌우2쪽", lambda: (pw.set_split(False), pw.set_dual(True)))):
    setup(); pw.set_fill_screen(False); pw._pm_cache = {}
    pw._go(0); pw._render(); app.processEvents()
    before = pw._label.pixmap()
    chk(before.width() < 1200 or before.height() < 700,
        f"{label}: 채움 전에는 여백 있음", f"{before.width()}x{before.height()}")
    pw.set_fill_screen(True); app.processEvents()
    after = pw._label.pixmap()
    chk(after.width() == 1200 and after.height() == 700,
        f"{label}: 화면 채움이 화면 전체를 채움", f"{after.width()}x{after.height()}")
    pw.set_fill_screen(False)
# 좌우 2쪽에서 채움을 켜면 쪽 사각형도 같이 늘어난다
pw.set_split(False); pw.set_dual(True); pw.set_fill_screen(True)
pw._go(0); pw._render(); app.processEvents()
rs = [pw._dual_rects[k] for k in sorted(pw._dual_rects)]
chk(len(rs) == 2 and abs((rs[1][0] + rs[1][2]) - 1200) < 12 and abs(rs[0][3] - 700) < 12,
    "채움 시 쪽 사각형도 함께 확대", str([tuple(round(v) for v in r) for r in rs]))
pw.set_fill_screen(False)

pw.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
