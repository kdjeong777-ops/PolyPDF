"""260628(감사 F-4): 편집모드·페이지 메타 컨트롤러 — MainWindow 에서 분리한 믹스인.

app.py 분할 4단계(§11.11, 마지막). 담당:
  - **선긋기 반영/베이크**: `_apply_drawings_to_meta`/`_bake_drawings_into_doc`/
    `_apply_drawings_to_pdf`/`_bake_text_stroke`, `_bake_hyperlinks_into_doc`/
    `_action_save_decorated_pdf`(꾸미기 포함 저장)
  - **페이지 메타**: 크롭·숨김·회전·선긋기·이미지 접근자와 저장소(`_ensure_page_meta_store`)
  - **선긋기 설정 공유**: `_draw_pens`/`_init_draw_config`/`_apply_draw_config_all`/`_text_styles`
  - **편집모드 트랜잭션**: `_snapshot_edit`/`_restore_edit`/`_commit_edit`/`_confirm_edit_save`/
    `_on_edit_mode_toggled`, 회전·숨김·크롭 조작과 UI 갱신

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(EditMixin, ...)`).
`self.*` 참조가 모두 그대로 동작하므로 **호출부(툴바·썸네일·본문뷰 시그널)는 변경 없음**.
모듈 수준 헬퍼 `_smooth_dense_norm` 은 이 블록에서만 쓰이므로 함께 옮겼다(순환 import 방지).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

__all__ = ["EditMixin"]


def _smooth_dense_norm(pn, steps=12):
    """260611-84: 자유곡선 베이크용 — 화면(2차 베지어 중점 스무딩)과 동일한 곡선을
    촘촘한 폴리라인으로 샘플링(정규화 좌표). pn: [[x,y],...], 점 3개 이상."""
    n = len(pn)
    if n < 3:
        return pn
    out = [list(pn[0])]
    start = pn[0]
    for i in range(1, n - 1):
        c = pn[i]
        e = ((pn[i][0] + pn[i + 1][0]) / 2.0, (pn[i][1] + pn[i + 1][1]) / 2.0)
        for s in range(1, steps + 1):
            t = s / steps; mt = 1.0 - t
            out.append([mt * mt * start[0] + 2 * mt * t * c[0] + t * t * e[0],
                        mt * mt * start[1] + 2 * mt * t * c[1] + t * t * e[1]])
        start = e
    out.append(list(pn[-1]))
    return out


class EditMixin:
    """MainWindow 에 믹스인되는 편집모드·페이지 메타 메서드 모음."""

    def _on_apply_presentation_drawings(self, norm, file_path):
        """260609-25(I4): 발표에서 그린 선을 본화면(page_meta)·새 PDF에 적용."""
        # 발표 종료 흐름 중이므로 약간 미뤄 실행
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._apply_presentation_drawings_now(norm, file_path))

    def _apply_presentation_drawings_now(self, norm, file_path):
        if not norm:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("선긋기 적용")
        box.setText(f"전체화면에서 그린 선을 적용할까요?\n({len(norm)}개 페이지)")
        b_main = box.addButton("본화면에 적용", QMessageBox.ButtonRole.AcceptRole)
        b_pdf = box.addButton("PDF로 저장", QMessageBox.ButtonRole.ActionRole)
        b_both = box.addButton("둘 다", QMessageBox.ButtonRole.ActionRole)
        box.addButton("적용 안 함", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c not in (b_main, b_pdf, b_both):
            return
        if c in (b_main, b_both):
            self._apply_drawings_to_meta(norm, file_path)
        if c in (b_pdf, b_both):
            self._apply_drawings_to_pdf(norm, file_path)

    def _apply_drawings_to_meta(self, norm, file_path):
        st = self._ensure_page_meta_store()
        if not st:
            return
        for page0, strokes in norm.items():
            existing = st.get_drawings(file_path, page0)
            st.set_drawings(file_path, page0, list(existing) + list(strokes))
        st.save()
        self._refresh_hidden_ui(str(file_path))
        try:
            for mv in self._mv:
                if mv.current_file() and str(Path(mv.current_file())) == str(Path(file_path)):
                    mv._load_page_strokes()
        except Exception:
            pass
        self.status.showMessage("선긋기를 본화면에 적용했습니다.", 3000)

    def _bake_drawings_into_doc(self, doc, norm):
        """260615-3: 정규화 선긋기(선·도형·텍스트박스·지시선·하이라이트)를 열린 doc 에 베이크.
        norm: {page0: [stroke, ...]}. (인쇄/PDF꾸밈저장 공용)"""
        import fitz
        from PyQt6.QtGui import QColor
        for page0, strokes in norm.items():
            if page0 < 0 or page0 >= doc.page_count:
                continue
            page = doc[page0]
            pw, ph = page.rect.width, page.rect.height
            for stk in strokes:
                qc = QColor(stk.get("color", "#ff3030"))
                rgb = (qc.redF(), qc.greenF(), qc.blueF())
                op = max(0.1, min(1.0, float(stk.get("alpha", 100)) / 100.0))
                # 260611-69(Stage1): 도형(직사각형/둥근/원형) 베이크
                if stk.get("shape"):
                    lw = max(0.6, int(stk.get("width", 3)) * 0.6)
                    fk = stk.get("fill", "none")
                    f_rgb = rgb if fk != "none" else None
                    f_op = op * (0.30 if fk == "semi" else 1.0)
                    kind = stk.get("shape")
                    try:
                        if kind == "circle":
                            cx = stk.get("cx", 0.5) * pw; cy = stk.get("cy", 0.5) * ph
                            r = stk.get("r", 0.0) * pw
                            sh = page.new_shape()
                            sh.draw_oval(fitz.Rect(cx - r, cy - r, cx + r, cy + r))
                            sh.finish(color=rgb, width=lw, fill=f_rgb,
                                      fill_opacity=f_op, stroke_opacity=op)
                            sh.commit()
                        else:
                            rc = stk.get("rect", [0, 0, 0, 0])
                            rot = float(stk.get("rot", 0.0))
                            kw = dict(color=rgb, width=lw, fill=f_rgb,
                                      fill_opacity=f_op, stroke_opacity=op)
                            if rot:     # 회전 도형 → 회전한 사각형 폴리곤
                                import math
                                cx = (rc[0] + rc[2]) / 2 * pw; cy = (rc[1] + rc[3]) / 2 * ph
                                hw = abs(rc[2] - rc[0]) / 2 * pw; hh = abs(rc[3] - rc[1]) / 2 * ph
                                a = math.radians(rot); ca = math.cos(a); sa = math.sin(a)
                                pts = [fitz.Point(cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)
                                       for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
                                sh = page.new_shape(); sh.draw_polyline(pts + [pts[0]])
                                sh.finish(color=rgb, width=lw, fill=f_rgb,
                                          fill_opacity=f_op, stroke_opacity=op, closePath=True)
                                sh.commit()
                            else:
                                rect = fitz.Rect(min(rc[0], rc[2]) * pw, min(rc[1], rc[3]) * ph,
                                                 max(rc[0], rc[2]) * pw, max(rc[1], rc[3]) * ph)
                                if kind == "round":
                                    page.draw_rect(rect, radius=0.18, **kw)
                                else:
                                    page.draw_rect(rect, **kw)
                    except Exception:
                        pass
                    continue
                # 260611-74(Phase2): 텍스트 박스 / 지시선 베이크
                if stk.get("text_box") or stk.get("leader"):
                    try:
                        self._bake_text_stroke(fitz, QColor, page, stk, pw, ph)
                    except Exception:
                        pass
                    continue
                pn = stk.get("points", [])
                if len(pn) < 2:
                    continue
                # 260611-1: 하이라이트 = 텍스트 줄 높이만큼 채운 사각형
                if stk.get("hl"):
                    bh = float(stk.get("h", 0.0)) * ph
                    (x0, yc), (x1, _y) = pn[0], pn[-1]
                    rect = fitz.Rect(min(x0, x1) * pw, yc * ph - bh / 2.0,
                                     max(x0, x1) * pw, yc * ph + bh / 2.0)
                    try:
                        page.draw_rect(rect, color=None, fill=rgb, fill_opacity=op)
                    except Exception:
                        page.draw_rect(rect, fill=rgb)
                    continue
                # 260611-84: 자유곡선(점 3개 이상)은 화면과 동일하게 부드러운 곡선으로 저장
                pn2 = _smooth_dense_norm(pn) if len(pn) > 2 else pn
                pts = [fitz.Point(fx * pw, fy * ph) for fx, fy in pn2]
                wpt = max(0.6, int(stk.get("width", 3)) * 0.6)
                try:
                    page.draw_polyline(pts, color=rgb, width=wpt, stroke_opacity=op,
                                       linecap=1, linejoin=1)
                except Exception:
                    page.draw_polyline(pts, color=rgb, width=wpt)

    def _decorations_norm_for(self, file_path):
        """260615-3: 파일의 모든 페이지 선긋기(꾸밈) {page0: strokes} — 인쇄/저장 공용."""
        norm = {}
        st = self._ensure_page_meta_store()
        if st:
            for p in st.pages_with_drawings(file_path):
                dr = st.get_drawings(file_path, p)
                if dr:
                    norm[int(p)] = dr
        return norm

    def _apply_drawings_to_pdf(self, norm, file_path, *, with_hyperlinks: bool = True):
        src = Path(file_path)
        from PyQt6.QtWidgets import QFileDialog
        out, _ = QFileDialog.getSaveFileName(
            self, "PDF 꾸밈 저장 — 새 PDF로 저장",
            str(src.with_name(src.stem + "_꾸밈.pdf")), "PDF (*.pdf)")
        if not out:
            return
        try:
            import fitz
            from PyQt6.QtGui import QColor
            doc = fitz.open(str(src))
            self._bake_drawings_into_doc(doc, norm)
            # 260615-3: ② 하이퍼링크도 함께 PDF 에 베이크(꾸밈 저장)
            if with_hyperlinks:
                try:
                    self._bake_hyperlinks_into_doc(doc, file_path)
                except Exception:
                    pass
            doc.save(out, garbage=4, deflate=True)
            doc.close()
            self.status.showMessage(f"PDF 꾸밈 저장: {Path(out).name}", 4000)
            QMessageBox.information(self, "저장 완료",
                                   f"선·도형·글·하이퍼링크를 삽입한 PDF를 저장했습니다.\n{out}")
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    # 260611-76: 글꼴 이름 → Windows TTF/TTC 경로
    _FONT_FILES = {
        "맑은 고딕": [r"C:\Windows\Fonts\malgun.ttf"],
        "굴림": [r"C:\Windows\Fonts\gulim.ttc"],
        "바탕": [r"C:\Windows\Fonts\batang.ttc"],
        "돋움": [r"C:\Windows\Fonts\dotum.ttc", r"C:\Windows\Fonts\gulim.ttc"],
    }

    def _korean_fontfile(self, family=None):
        """260611-74/76: 글꼴 이름에 맞는 TTF/TTC 경로. 없으면 맑은고딕→폴백."""
        import os
        cands = list(self._FONT_FILES.get(family or "맑은 고딕", []))
        cands += [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
                  r"C:\Windows\Fonts\batang.ttc", r"C:\Windows\Fonts\NanumGothic.ttf"]
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    def _bake_text_stroke(self, fitz, QColor, page, stk, pw, ph):
        """260611-74/76: 텍스트 박스/지시선 굽기 — 배경(투명도)·박스선·지시선(색상버튼 스타일)·텍스트."""
        import math

        def _rgb_op(color, alpha_pct):
            q = QColor(color)
            return (q.redF(), q.greenF(), q.blueF()), max(0.05, min(1.0, float(alpha_pct) / 100.0))

        rc = stk.get("rect", [0, 0, 0.1, 0.05])
        x0 = min(rc[0], rc[2]) * pw; y0 = min(rc[1], rc[3]) * ph
        x1 = max(rc[0], rc[2]) * pw; y1 = max(rc[1], rc[3]) * ph
        rect = fitz.Rect(x0, y0, x1, y1)
        trgb, _ = _rgb_op(stk.get("color", "#111111"), 100)
        bg = stk.get("bg")
        if bg:
            brgb, bop = _rgb_op(bg, stk.get("bg_alpha", 100))
            page.draw_rect(rect, color=None, fill=brgb, fill_opacity=bop)
        if stk.get("box_line"):
            drgb, dop = _rgb_op(stk.get("border_color", "#333333"), stk.get("border_alpha", 100))
            page.draw_rect(rect, color=drgb, width=max(0.6, int(stk.get("border_w", 1)) * 0.7),
                           stroke_opacity=dop)
        if stk.get("leader"):
            # 지시선이 가리키는 문자 하이라이트(반투명, 선 색상)
            hrgb, _ = _rgb_op(stk.get("line_color", "#ffcc00"), 100)
            hop = max(0.05, min(1.0, float(stk.get("line_alpha", 100)) / 100.0) * 0.40)
            for r in stk.get("hl_rects", []):
                try:
                    page.draw_rect(fitz.Rect(r[0] * pw, r[1] * ph, r[2] * pw, r[3] * ph),
                                   color=None, fill=hrgb, fill_opacity=hop)
                except Exception:
                    pass
            an = stk.get("anchor", [0.5, 0.5]); ax = an[0] * pw; ay = an[1] * ph
            cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
            hw = (x1 - x0) / 2; hh = (y1 - y0) / 2
            dx = ax - cx; dy = ay - cy
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                sx, sy = cx, cy
            else:
                tt = min(hw / abs(dx) if abs(dx) > 1e-6 else 1e9,
                         hh / abs(dy) if abs(dy) > 1e-6 else 1e9)
                sx, sy = cx + dx * tt, cy + dy * tt
            lrgb, lop = _rgb_op(stk.get("line_color", stk.get("color", "#111111")),
                                stk.get("line_alpha", 100))
            lw = max(0.6, int(stk.get("line_w", 2)) * 0.7)
            page.draw_line(fitz.Point(sx, sy), fitz.Point(ax, ay), color=lrgb, width=lw,
                           stroke_opacity=lop)
            tip = stk.get("tip", "arrow")
            if tip == "circle":
                page.draw_circle(fitz.Point(ax, ay), 5, color=lrgb, fill=lrgb,
                                 stroke_opacity=lop, fill_opacity=lop)
            elif tip == "arrow":
                ang = math.atan2(ay - sy, ax - sx); sz = 11
                for da in (math.radians(150), math.radians(-150)):
                    page.draw_line(fitz.Point(ax, ay),
                                   fitz.Point(ax + sz * math.cos(ang + da),
                                              ay + sz * math.sin(ang + da)),
                                   color=lrgb, width=lw, stroke_opacity=lop)
        txt = stk.get("text", "")
        if not txt.strip():
            return
        fs = max(5.0, float(stk.get("size", 0.022)) * ph)
        ff = self._korean_fontfile(stk.get("family"))
        kw = dict(fontsize=fs, color=trgb, align=int(stk.get("align", 0)))
        if ff:
            kw.update(fontfile=ff, fontname="krfont")
        pad = 2
        box = fitz.Rect(x0 + pad, y0 + pad, x1 - pad, y1 - pad)
        try:
            rcv = page.insert_textbox(box, txt, **kw)
            if rcv < 0:   # 안 들어가면 박스를 넉넉히 넓혀 재시도
                big = fitz.Rect(x0, y0, x0 + (x1 - x0) * 3 + fs * len(txt),
                                y0 + (y1 - y0) * 3 + fs * 4)
                page.insert_textbox(big, txt, **kw)
        except Exception:
            try:
                page.insert_textbox(box, txt, fontsize=fs, color=trgb)
            except Exception:
                pass

    def _bake_hyperlinks_into_doc(self, doc, cur):
        """260615-3: 등록 하이퍼링크를 열린 doc 에 라벨 버튼+링크 주석으로 삽입.
        외부 리더에서도 클릭 동작(파일=Launch, URL=URI)."""
        import fitz
        st = self._ensure_hyperlink_store()
        if not st:
            return
        off_pt = float(self._prefs.get("hyperlink_top_offset_px", 10))
        fs = 9.0
        pad_x, gap, btn_h = 6.0, 6.0, fs + 8.0
        for p0 in sorted(st.pages_with_links(cur)):
            if p0 < 0 or p0 >= doc.page_count:
                continue
            page = doc[p0]
            pw = page.rect.width
            links = st.links_for(cur, p0)
            items = []
            for ln in links:
                label = str(ln.get("name", "") or "링크")
                tw = fitz.get_text_length(label, fontsize=fs) + 2 * pad_x
                items.append((label, min(tw, pw - 20), ln))
            avail = pw - 20
            rows, cur_w = [[]], 0.0
            for it in items:
                w = it[1]
                if rows[-1] and cur_w + gap + w > avail:
                    rows.append([]); cur_w = 0.0
                rows[-1].append(it); cur_w += (gap if cur_w else 0) + w
            y = 10.0 + off_pt
            for row in rows:
                total = sum(w for _, w, _ in row) + gap * (len(row) - 1)
                x = (pw - total) / 2.0
                for label, w, ln in row:
                    rect = fitz.Rect(x, y, x + w, y + btn_h)
                    page.draw_rect(rect, color=(1, 1, 1), fill=(0.08, 0.40, 0.75),
                                   width=0.5, radius=0.2)
                    page.insert_textbox(rect, label, fontsize=fs,
                                        color=(1, 1, 1), align=fitz.TEXT_ALIGN_CENTER)
                    if ln.get("kind") == "url":
                        page.insert_link({"kind": fitz.LINK_URI, "from": rect,
                                          "uri": str(ln.get("target", ""))})
                    else:
                        page.insert_link({"kind": fitz.LINK_LAUNCH, "from": rect,
                                          "file": str(ln.get("target", ""))})
                    x += w + gap
                y += btn_h + 4

    def _action_save_decorated_pdf(self):
        """260615-3: ② 'PDF 꾸밈 저장' — 선·도형·텍스트박스·지시선 + 하이퍼링크를
        새 PDF 에 삽입 저장. (구 '하이퍼링크 삽입 저장' 확장)"""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            QMessageBox.information(self, "안내", "먼저 PDF를 표시하세요.")
            return
        # 이 파일의 모든 페이지 꾸밈(선긋기) 수집
        norm = self._decorations_norm_for(cur)
        st_hl = self._ensure_hyperlink_store()
        has_hl = bool(st_hl and st_hl.pages_with_links(cur))
        if not norm and not has_hl:
            QMessageBox.information(self, "안내",
                                   "이 파일에 저장할 꾸밈(선·도형·글)이나 하이퍼링크가 없습니다.")
            return
        self._apply_drawings_to_pdf(norm, cur, with_hyperlinks=True)

    def _ensure_page_meta_store(self):
        from viewer.page_meta import PageMetaStore
        if not self._folder:
            self._page_meta = None
            return None
        st = self._page_meta
        if st is None or str(getattr(st, "base", "")) != str(self._folder):
            self._page_meta = PageMetaStore(self._folder)
        return self._page_meta

    def _crop_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_crop(path, page0) if st else (0.0, 0.0)

    def _hidden_for(self, path):
        st = self._ensure_page_meta_store()
        return st.hidden_pages(path) if st else set()

    def _rotation_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_rotation(path, page0) if st else 0

    # ===== 260609-22(J3): 본화면 선긋기 =================================
    def _drawings_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_drawings(path, page0) if st else []

    def _set_drawings(self, path, page0, strokes):
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_drawings(path, page0, strokes)
        self._persist_meta(st)               # 260609-23(J2): 편집모드면 보류
        self._refresh_hidden_ui(path)        # 꾸밈 갱신(썸네일 색·필터)

    # 260611-15: 삽입 이미지(주석) page_meta 연동
    def _images_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_images(path, page0) if st else []

    def _thumb_images_for(self, page0):
        """260611-18(A5): 썸네일 베이킹용 — 현재 표시 파일의 page0 삽입 이미지."""
        try:
            f = self.main_view.current_file() if self.main_view else None
        except Exception:
            f = None
        if not f or not str(f).lower().endswith(".pdf"):
            return []
        return self._images_for(str(f), int(page0))

    def _set_images(self, path, page0, images):
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_images(path, page0, images)
        self._persist_meta(st)
        self._refresh_hidden_ui(path)        # 꾸밈 갱신(이미지 있는 페이지도 꾸밈)

    # ===== 260611-2: 본문·발표 공유 선긋기 설정 =========================
    def _draw_pens(self):
        from viewer.widgets.main_view import MV_DEFAULT_PENS
        pens = list(self._prefs.get("draw_pens") or MV_DEFAULT_PENS)
        while len(pens) < len(MV_DEFAULT_PENS):     # 260611-5: 5개로 보충
            pens.append(dict(MV_DEFAULT_PENS[len(pens)]))
        return pens

    def _draw_eraser_widths(self):
        return self._prefs.get("draw_eraser_widths") or [12, 30]

    def _draw_highlight_alpha(self):
        return int(self._prefs.get("draw_highlight_alpha", 35))

    def _init_draw_config(self, mv):
        # 260611-2: 본문·발표 공유 5펜 + 선 종류(직선/하이라이트/자유) + 지우개폭 + 하이라이트 투명도
        mv.set_draw_config(
            self._draw_pens(),
            int(self._prefs.get("draw_line_mode", 0)),
            self._draw_eraser_widths(),
            self._draw_highlight_alpha(),
            self._drawings_for, self._set_drawings)
        mv.set_image_config(self._images_for, self._set_images)   # 260611-15
        try:
            mv.set_text_styles(self._text_styles())               # 260611-78
        except Exception:
            pass

    def _apply_draw_config_all(self):
        """260611-2: 공유 펜/지우개/하이라이트 설정을 두 메인뷰·발표창에 즉시 반영."""
        for mv in self._mv:
            try:
                mv.set_main_pens(self._draw_pens())
                mv._draw_eraser_widths = list(self._draw_eraser_widths())
                mv._draw_highlight_alpha = self._draw_highlight_alpha()
            except Exception:
                pass
        if getattr(self, "_present", None) is not None:
            try:
                self._present.set_pens(self._draw_pens())
                self._present.set_eraser_widths(self._draw_eraser_widths())
                self._present.set_highlight_alpha(self._draw_highlight_alpha())
            except Exception:
                pass

    def _open_main_pen_settings(self):
        """260611-2: 공유 선긋기 설정(5펜 색·굵기·투명도 + 지우개 면적) → 저장·전체 반영."""
        from viewer.widgets.pen_settings_dialog import MainDrawSettingsDialog
        dlg = MainDrawSettingsDialog(self._draw_pens(), self,
                                     eraser_widths=self._draw_eraser_widths(),
                                     highlight_alpha=self._draw_highlight_alpha())
        if dlg.exec():
            self._prefs["draw_pens"] = dlg.result_pens()
            self._prefs["draw_eraser_widths"] = dlg.result_eraser_widths()
            self._prefs["draw_highlight_alpha"] = dlg.result_highlight_alpha()
            self._apply_draw_config_all()
            self._save_settings_now()

    def _text_styles(self):
        """260611-78: 저장된 사용자 글쓰기 스타일. 없으면 기본(본문/제목/메모/강조)."""
        styles = self._prefs.get("text_styles")
        if not styles:
            try:
                styles = self._mv[0]._seed_text_styles()
            except Exception:
                styles = []
        return styles

    def _open_line_text_settings(self):
        """260611-78: '선과 텍스트 입력 설정' — 선긋기 + 글쓰기(사용자 스타일) 통합 설정."""
        from viewer.widgets.line_text_settings_dialog import LineTextSettingsDialog
        dlg = LineTextSettingsDialog(self._draw_pens(), self._draw_eraser_widths(),
                                     self._draw_highlight_alpha(), self._text_styles(), self)
        if dlg.exec():
            self._prefs["draw_pens"] = dlg.result_pens()
            self._prefs["draw_eraser_widths"] = dlg.result_eraser_widths()
            self._prefs["draw_highlight_alpha"] = dlg.result_highlight_alpha()
            self._prefs["text_styles"] = dlg.result_styles()
            self._apply_draw_config_all()
            for mv in self._mv:
                try:
                    mv.set_text_styles(self._text_styles())
                except Exception:
                    pass
            self._save_settings_now()

    # ===== 260609-23(J2): 편집모드 트랜잭션 =============================
    def _in_edit(self) -> bool:
        try:
            return self.bookmark_tree.is_edit_mode()
        except Exception:
            return False

    def _persist_meta(self, store):
        """편집모드면 디스크 저장을 보류하고 dirty 표시, 아니면 즉시 저장."""
        if store is None:
            return
        if self._in_edit():
            self._edit_dirty = True
        else:
            store.save()

    def _snapshot_edit(self):
        import copy
        if self._edit_snap is not None:
            return                       # 이미 세션 진행 중(계속 편집 등)
        self._edit_dirty = False
        pm = self._ensure_page_meta_store()
        hl = self._ensure_hyperlink_store()
        self._edit_snap = {
            "pm": copy.deepcopy(pm._data) if pm else None,
            "hl": copy.deepcopy(hl._data) if hl else None,
        }

    def _restore_edit(self):
        import copy
        snap = self._edit_snap or {}
        pm = self._page_meta
        hl = self._hyperlinks
        if pm is not None and snap.get("pm") is not None:
            pm._data = copy.deepcopy(snap["pm"])
        if hl is not None and snap.get("hl") is not None:
            hl._data = copy.deepcopy(snap["hl"])
        self._refresh_all_meta_ui()

    def _commit_edit(self):
        if self._page_meta is not None:
            self._page_meta.save()
        if self._hyperlinks is not None:
            self._hyperlinks.save()

    def _save_meta_from_button(self):
        """260611-18(A4·A5): '저장' 버튼 — 편집모드 page_meta 변경을 디스크에 저장하고
        썸네일(개체 베이킹 포함)을 갱신. 편집모드는 유지하되 저장된 상태를 새 기준으로."""
        if not self._edit_dirty:
            return
        self._commit_edit()
        self._edit_dirty = False
        # 저장된 상태를 새 스냅샷 기준으로(이후 '취소'는 저장 시점으로 되돌림)
        self._edit_snap = None
        try:
            self._snapshot_edit()
        except Exception:
            pass
        # 썸네일 재렌더 → 삽입 개체가 썸네일에 반영(A5)
        try:
            cur = self.main_view.current_file() if self.main_view else None
            if cur:
                self._refresh_hidden_ui(str(cur))
        except Exception:
            pass
        try:
            self.status.showMessage("편집 내용을 저장했습니다.", 3000)
        except Exception:
            pass

    def _on_edit_cancelled(self):
        """260611-9: 책갈피 '취소' — 편집모드 유지한 채 미저장 수정(숨김/회전/선긋기/
        하이퍼링크)을 스냅샷으로 되돌리고, 이후 편집을 위해 스냅샷을 새로 찍는다."""
        try:
            if self._edit_snap is not None:
                self._restore_edit()
        except Exception:
            pass
        self._edit_snap = None
        self._edit_dirty = False
        try:
            self._snapshot_edit()        # 되돌린 상태를 새 기준으로
        except Exception:
            pass
        try:
            self.status.showMessage("편집 수정 사항을 취소(되돌리기)했습니다.", 3000)
        except Exception:
            pass

    def _refresh_all_meta_ui(self):
        cur = self.main_view.current_file() if self.main_view else None
        if cur and str(cur).lower().endswith(".pdf"):
            self._refresh_hidden_ui(str(cur))
            self._refresh_page_hyperlinks(self._active_pane)
            try:
                for mv in self._mv:
                    if mv.current_file() and str(Path(mv.current_file())) == str(Path(cur)):
                        mv._load_page_strokes()
                        mv._load_page_images()      # 260611-15: 취소 시 이미지도 복원
            except Exception:
                pass

    def _confirm_edit_save(self, switching=False) -> str:
        """미저장 변경 확인. 반환: 'save'/'discard'/'cancel'."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("편집 변경사항")
        box.setText("저장하지 않은 편집 변경사항이 있습니다.\n"
                    + ("다른 파일로 이동하기 전에 어떻게 할까요?" if switching
                       else "편집을 종료하기 전에 어떻게 할까요?"))
        b_save = box.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton("되돌리기(저장 안 함)", QMessageBox.ButtonRole.DestructiveRole)
        b_keep = box.addButton("계속 편집", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_save:
            return "save"
        if c is b_disc:
            return "discard"
        return "cancel"

    def _on_edit_mode_toggled(self, on: bool):
        if on:
            self._snapshot_edit()
        else:
            # 종료 시 미저장 변경 처리
            if self._edit_snap is not None and self._edit_dirty:
                choice = self._confirm_edit_save(switching=False)
                if choice == "cancel":
                    # 편집 유지 — 버튼 다시 켜기(정상 toggled 로 모든 핸들러 복원)
                    self.bookmark_tree.btn_edit.setChecked(True)
                    return
                if choice == "save":
                    self._commit_edit()
                else:
                    self._restore_edit()
            self._edit_snap = None
            self._edit_dirty = False
        for mv in self._mv:
            try:
                self._init_draw_config(mv)
                mv.set_draw_mode(bool(on))
            except Exception:
                pass

    def _rotations_for(self, path):
        st = self._ensure_page_meta_store()
        return st.rotations(path) if st else {}

    def _rotate_pages(self, pages, delta):
        """260609-15(A1): 썸네일 선택 페이지 90° 회전 — 저장 + 갱신."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf") or not pages:
            return
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.rotate_pages(cur, pages, delta)
        self._persist_meta(st)           # 260609-23(J2)
        self._refresh_hidden_ui(cur)

    def _on_crop_settings(self):
        """발표 우클릭 '크롭 설정…' → 다이얼로그 → 저장·재렌더."""
        w = getattr(self, "_present", None)
        st = self._ensure_page_meta_store()
        if not w or not st:
            return
        path = str(w._path); page0 = int(w._page)
        from viewer.widgets.crop_dialog import CropDialog
        g = st.get_global_crop(path)
        pg = st.get_crop(path, page0)
        dlg = CropDialog(page0 + 1, g, pg, st.has_page_crop(path, page0), w)
        if not dlg.exec():
            return
        r = dlg.result()
        if r["reset"]:
            st.reset_crop(path)
        else:
            st.set_global_crop(path, *r["global"])
            if r["page_enabled"]:
                st.set_page_crop(path, page0, *r["page"])
            else:
                st.clear_page_crop(path, page0)
        st.save()
        w.refresh()

    def _set_pages_hidden(self, pages, hidden: bool):
        """260609-14(D5): 페이지 숨김/해제 — 저장 + 썸네일·뷰어·발표 갱신."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            return
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_hidden(cur, pages, hidden)
        self._persist_meta(st)           # 260609-23(J2): 편집모드면 보류
        self._refresh_hidden_ui(cur)

    def _reset_hidden(self):
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            return
        st = self._ensure_page_meta_store()
        if st and st.clear_hidden(cur):
            self._persist_meta(st)       # 260609-23(J2)
            self._refresh_hidden_ui(cur)

    def _push_nav_filter(self):
        """260609-26: 썸네일 필터(보임/꾸밈/숨김)를 활성 뷰어 페이지 이동에 반영."""
        mv = self.main_view
        try:
            if not mv or mv._is_image or mv._doc is None:
                if mv:
                    mv.set_nav_pages(None)
                return
            tp = self.page_thumbs
            if getattr(tp, "_filter", "all") == "all":
                mv.set_nav_pages(None)
                return
            n = mv._doc.page_count
            pages = [p for p in range(n) if tp.page_visible_in_filter(p)]
            if not pages:
                pages = [mv._current_page]   # 빈 필터 → 현재 페이지에 고정
            mv.set_nav_pages(pages)
        except Exception:
            pass

    def _decorated_for(self, file_path):
        """260609-21/22(J4·J3): 꾸밈 페이지 = 하이퍼링크 ∪ 선긋기 페이지."""
        deco = set()
        try:
            st = self._ensure_hyperlink_store()
            if st and str(file_path).lower().endswith(".pdf"):
                deco |= set(st.pages_with_links(file_path))
        except Exception:
            pass
        try:
            pm = self._ensure_page_meta_store()
            if pm:
                deco |= set(pm.pages_with_drawings(file_path))
                deco |= set(pm.pages_with_images(file_path))   # 260611-15
        except Exception:
            pass
        return deco

    def _refresh_hidden_ui(self, file_path):
        hidden = self._hidden_for(file_path)
        rots = self._rotations_for(file_path)              # 260609-15(A1)
        deco = self._decorated_for(file_path)              # 260609-21(J4)
        try:
            self.page_thumbs.set_hidden_pages(hidden)
            self.page_thumbs.set_rotations(rots)
            self.page_thumbs.set_decorated_pages(deco)
            # 260609-28: 새 파일의 숨김/꾸밈 메타 기준으로 필터 재적용(목록만, 이동 없음)
            #   → 보임/꾸밈/숨김 필터가 파일을 바꿔도 동일 상태로 유지됨
            if getattr(self.page_thumbs, "_filter", "all") != "all":
                self.page_thumbs._apply_filter(jump=False)
        except Exception:
            pass
        self._push_nav_filter()      # 260609-26: 숨김/꾸밈 변동 → 필터 페이지 갱신
        try:
            for mv in self._mv:
                if mv.current_file() and str(Path(mv.current_file())) == str(Path(file_path)):
                    mv.set_hidden_pages(hidden)
                    mv.set_rotations(rots)
        except Exception:
            pass
        if getattr(self, "_present", None) is not None:
            try:
                self._present.refresh()
            except Exception:
                pass
