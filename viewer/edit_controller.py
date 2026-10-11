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
from viewer.i18n import tr

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
        box.setWindowTitle(tr("선긋기 적용"))
        box.setText(tr('전체화면에서 그린 선을 적용할까요?\n({n}개 페이지)').format(n=len(norm)))
        b_main = box.addButton(tr("본화면에 적용"), QMessageBox.ButtonRole.AcceptRole)
        b_pdf = box.addButton(tr("PDF로 저장"), QMessageBox.ButtonRole.ActionRole)
        b_both = box.addButton(tr("둘 다"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("적용 안 함"), QMessageBox.ButtonRole.RejectRole)
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
        self.status.showMessage(tr("선긋기를 본화면에 적용했습니다."), 3000)

    # 260930-2(마스터 §4.7.13, 사용자 보고): 삽입 이미지(주석)도 **굽는다**.
    #   종전에는 인쇄('문서 + 주석·꾸미기')도 'PDF 꾸밈 저장' 도 선·도형·글·하이퍼링크만
    #   굽고 **사진은 빠뜨렸다** — 화면과 썸네일에는 보이는데 인쇄물·저장본에는 없었다.
    IMG_BAKE_DPI = 200          # 굽는 해상도(인쇄 200dpi 와 같게)

    def _bake_images_into_doc(self, doc, path):
        """이 파일의 삽입 이미지를 열린 `doc` 에 굽는다 (인쇄·꾸밈 저장 공용).

        **화면과 같은 규칙으로 그린다** — 자리(정규화 `rect`)·회전(`rot`)·투명도(`alpha`)·
        모양(`shape`)을 Qt 로 합성한 뒤 그 결과를 한 장으로 넣는다. fitz 로 따로 흉내 내면
        (회전은 90° 배수만, 투명도·둥근 모양은 없다) 화면과 달라진다.

        회전한 그림은 **축에 나란한 테두리 상자**에 맞춰 넣는다 — 그래야 돌린 모서리가
        잘리지 않는다.
        """
        import math, base64
        import fitz
        from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPixmap
        from PyQt6.QtCore import QRectF
        st = self._ensure_page_meta_store()
        if not st:
            return 0
        done = 0
        for page0 in sorted(st.pages_with_images(path)):
            if page0 < 0 or page0 >= doc.page_count:
                continue
            page = doc[page0]
            W, H = float(page.rect.width), float(page.rect.height)
            for d in (st.get_images(path, page0) or []):
                pm = QPixmap()
                try:
                    pm.loadFromData(base64.b64decode(d.get("data", "")), "PNG")
                except Exception:
                    continue
                if pm.isNull():
                    continue
                fx, fy, fw, fh = d.get("rect", [0.1, 0.1, 0.3, 0.3])
                w_pt, h_pt = float(fw) * W, float(fh) * H
                if w_pt <= 0 or h_pt <= 0:
                    continue
                rot = float(d.get("rot", 0.0) or 0.0)
                alpha = max(0, min(100, int(d.get("alpha", 100))))
                shape = d.get("shape", "rect")
                # 돌린 뒤의 테두리 상자(pt)
                th = math.radians(rot)
                bw = abs(w_pt * math.cos(th)) + abs(h_pt * math.sin(th))
                bh = abs(w_pt * math.sin(th)) + abs(h_pt * math.cos(th))
                sc = self.IMG_BAKE_DPI / 72.0
                iw, ih = max(1, int(bw * sc)), max(1, int(bh * sc))
                canvas = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
                canvas.fill(0)                       # 투명 — 본문 글자를 가리지 않는다
                pr = QPainter(canvas)
                pr.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                pr.translate(iw / 2.0, ih / 2.0)
                if rot:
                    pr.rotate(rot)
                pr.setOpacity(alpha / 100.0)
                local = QRectF(-w_pt * sc / 2.0, -h_pt * sc / 2.0, w_pt * sc, h_pt * sc)
                if shape in ("round", "circle"):      # 화면과 같은 모양 자르기
                    path_ = QPainterPath()
                    if shape == "circle":
                        path_.addEllipse(local)
                    else:
                        rr = min(local.width(), local.height()) * 0.18
                        path_.addRoundedRect(local, rr, rr)
                    pr.setClipPath(path_)
                pr.drawPixmap(local.toRect(), pm)
                pr.end()
                from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
                ba = QByteArray(); qb = QBuffer(ba)
                qb.open(QIODevice.OpenModeFlag.WriteOnly)
                canvas.save(qb, "PNG")
                qb.close()
                cx = (float(fx) + float(fw) / 2.0) * W
                cy = (float(fy) + float(fh) / 2.0) * H
                rect = fitz.Rect(cx - bw / 2.0, cy - bh / 2.0,
                                 cx + bw / 2.0, cy + bh / 2.0)
                try:
                    page.insert_image(rect, stream=bytes(ba), overlay=True)
                    done += 1
                except Exception:
                    continue
        return done

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
        """평탄화해서 내보내기(옛 '저장(일반뷰어용)') — **새 파일로만** (261011-2, 마스터 §4.7.16 '저장 메뉴').

        꾸밈·사진·하이퍼링크를 쪽 내용으로 굽고(보이는 자리 그대로 — `_bake_decorations`), 크롭 바깥을 실제로 지우고(§4.7.15),
        저장 전 회전을 `/Rotate` 에 넣고, '저장' 사본(레이어·링크)은 지운다. 정리(`garbage=4`)·글꼴 줄이기.
        서명된 원본은 내용만 굽고 같은 자리에 자동으로 다시 서명한다(보안 SOT §4.1 — `_resign_*`).
        굽기 그림(Qt)은 메인, 크롭 지우기·글꼴·저장·서명은 배경(응답성 SOT §4.4)."""
        import os as _os
        src = Path(file_path)
        from PyQt6.QtWidgets import QFileDialog
        out, _ = QFileDialog.getSaveFileName(
            self, tr("평탄화해서 내보내기 — 새 PDF로"),
            str(src.with_name(tr('{stem}_평탄화.pdf').format(stem=src.stem))), "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        if _os.path.normcase(_os.path.abspath(out)) == _os.path.normcase(_os.path.abspath(str(src))):
            QMessageBox.information(self, tr("평탄화해서 내보내기"),
                                    tr("원본과 다른 이름으로 내보내세요 — 원본은 PolyPDF 에서 계속 고칠 수 있게 그대로 둡니다."))
            return
        plan = self._resign_prepare(str(src))          # 서명된 원본: 확인·키 열기(보안 SOT §4.1). None = 취소
        if plan is None:
            return
        import fitz
        from viewer import page_crop as _pc, page_rotate as _pr, pdf_mirror as _pm
        try:
            doc = fitz.open(str(src))
            _pr.apply_pending(doc, src)                # 저장 전 회전 → /Rotate (바로 세우지 않는다, 261011-2)
            _pc.apply_pending(doc, src)                # 저장 전 크롭
            _pm.remove_layer(doc)                      # '저장' 사본은 지운다 — 구운 것과 두 번 보이지 않게
            _pm.remove_links(doc)
            self._resign_mark(doc, plan)               # 서명 칸은 굽지 않는다 — 자리만 표식으로
            self._bake_decorations(doc, file_path, norm=norm, links=with_hyperlinks)
        except Exception as e:
            QMessageBox.warning(self, tr("저장 실패"), str(e))
            return
        tmp = str(Path(out).with_name("~" + Path(out).stem + ".polypdf-tmp"))
        got = {}

        def _job(progress):
            progress(0, 3, tr("크롭 바깥 지우는 중"))
            cut = 0
            for i in range(doc.page_count):
                try:
                    cut += 1 if _pc.cut_outside(doc[i]) else 0
                except Exception:
                    pass
            got["cut"] = cut
            got["boxes"] = self._resign_take(doc, plan)
            # 260913-3(SOT §4.5.10): 글쓰기 굽기는 fontfile= 로 글꼴 **전체**(맑은 고딕 13MB)를
            #   넣는다 → 쓴 글자만 남겨 저장. 실패해도 저장은 한다(PyMuPDF 1.23 은 fontTools 필요).
            progress(1, 3, tr("글꼴 줄이는 중"))
            from viewer.pdf_font import subset_fonts_safely
            subset_fonts_safely(doc)
            progress(2, 3, tr("저장 중"))
            doc.save(tmp, garbage=4, deflate=True)
            progress(3, 3, tr("완료"))
        res = self._run_merge_job(_job, tr("평탄화해서 내보내기"), cancellable=False)
        doc.close()
        if not res.get("ok"):
            self._sign_unlink(tmp)
            QMessageBox.warning(self, tr("저장 실패"), res.get("err") or tr("알 수 없는 오류"))
            return
        signed, lost = self._resign_apply(tmp, plan, got.get("boxes") or {})
        err = self._file_op_bg(lambda: _os.replace(tmp, out), tr("저장 중: {name}").format(name=Path(out).name))
        if err is not None:
            self._sign_unlink(tmp)
            QMessageBox.warning(self, tr("저장 실패"), str(err))
            return
        cut = int(got.get("cut") or 0)
        self.status.showMessage(tr('평탄화해서 내보냈습니다: {name}').format(name=Path(out).name), 4000)
        QMessageBox.information(self, tr("평탄화해서 내보내기"),
                                tr('꾸밈·사진·하이퍼링크를 구운 PDF를 저장했습니다. 다른 프로그램에서도 그대로 보이고, 글자 검색·복사도 됩니다.\n{out}').format(out=str(out))
                                + (tr("\n크롭한 {n}쪽은 바깥 내용을 지우고 쪽 크기를 줄였습니다.").format(n=cut) if cut else "")
                                + (tr("\n서명 {n}개를 같은 자리에 다시 했습니다(서명 시각은 지금).").format(n=signed) if signed else "")
                                + (tr("\n서명 {n}개는 넣지 못했습니다(다른 사람의 서명·취소·크롭 바깥).").format(n=lost) if lost else ""))

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
        # 260907-1: 글자 크기 단위가 pt 가 됐다. PDF 좌표도 pt 라 **그대로** 넣으면 된다
        #   (인쇄물의 실제 크기 = 화면에서 보던 크기). 옛 자료의 `size`(페이지 대비 비율)는
        #   그 페이지 높이를 곱해 환산한다 — 보이던 크기가 유지된다.
        _spt = stk.get("size_pt")
        if _spt is None:
            _spt = float(stk.get("size", 0.022)) * ph
        fs = max(5.0, min(200.0, float(_spt)))
        # 260913-7(SOT §4.5.11): 글꼴은 맑은 고딕 하나 — 옛 자료의 `family` 는 무시한다.
        from viewer.pdf_font import fresh_font_name, insert_textbox_styled, text_font_file
        ff = text_font_file()
        bold = bool(stk.get("bold", False)); italic = bool(stk.get("italic", False))
        kw = dict(fontsize=fs, color=trgb, align=int(stk.get("align", 0)))
        if ff:
            # 260913-5(SOT §4.5.10 ②): 한 번 저장한 쪽의 krfont 는 이미 부분집합 — 같은 이름이면
            #   insert_font 가 그것을 재사용해 새 글자가 사라진다. 그런 이름은 비켜 간다.
            kw.update(fontfile=ff, fontname=fresh_font_name(page, "krfont"))
        pad = 2
        box = fitz.Rect(x0 + pad, y0 + pad, x1 - pad, y1 - pad)
        # 260907-3: **화면과 같은 자리에서 줄을 바꾼다.** `insert_textbox` 는 띄어쓰기에서만
        #   줄을 바꿔, 띄어쓰기 없는 한글이 박스를 넘치면 아래 '3배 박스' 폴백으로 빠져
        #   화면과 전혀 다른 모양이 됐다. 화면이 쓰는 것과 같은 배치기로 미리 줄을 나눠
        #   넣는다(줄바꿈 문자는 `insert_textbox` 가 그대로 지킨다).
        txt = self._wrap_like_screen(txt, fs, box.width, bold=bold, italic=italic)
        try:
            # 260913-7: 굵게·기울임도 굽는다 — 같은 글꼴로 흉내(글꼴 파일이 늘지 않음).
            rcv = insert_textbox_styled(fitz, page, box, txt, bold=bold, italic=italic, **kw)
            if rcv < 0:   # 안 들어가면 박스를 넉넉히 넓혀 재시도
                big = fitz.Rect(x0, y0, x0 + (x1 - x0) * 3 + fs * len(txt),
                                y0 + (y1 - y0) * 3 + fs * 4)
                insert_textbox_styled(fitz, page, big, txt, bold=bold, italic=italic, **kw)
        except Exception:
            try:
                page.insert_textbox(box, txt, fontsize=fs, color=trgb)
            except Exception:
                pass

    @staticmethod
    def _wrap_like_screen(text: str, fs: float, width_pt: float, family=None, *,
                          bold=False, italic=False) -> str:
        """260907-3: 화면과 같은 배치기(`QTextDocument`)로 줄을 미리 나눈다.

        화면의 `MainView._text_doc` 과 같은 규칙(`WrapAtWordBoundaryOrAnywhere`)을 쓰므로
        **띄어쓰기가 없어도** 같은 자리에서 줄이 바뀐다. 좌표 단위가 양쪽 모두 pt 라
        글자 크기·폭을 그대로 넣으면 된다. 실패하면 원문 그대로(종전 동작).
        260913-7(§4.5.11): 글꼴은 맑은 고딕 하나(`family` 는 무시), 굵게·기울임은 화면처럼 켜고 잰다."""
        try:
            from PyQt6.QtGui import QTextDocument, QTextOption, QFont
            from PyQt6.QtCore import Qt as _Qt
            from viewer.pdf_font import TEXT_FAMILY
            doc = QTextDocument()
            doc.setDocumentMargin(0.0)
            f = QFont(TEXT_FAMILY)
            f.setPixelSize(max(1, int(round(float(fs)))))
            f.setBold(bool(bold)); f.setItalic(bool(italic))
            doc.setDefaultFont(f)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(opt)
            doc.setPlainText(text)
            doc.setTextWidth(max(8.0, float(width_pt)))
            _ = doc.size()          # ★ 배치를 실제로 시키는 한 줄 — 이게 없으면
            #    가 0 이라 '한 줄' 로 나오고 줄이 안 나뉜다(실측).
            out = []
            b = doc.firstBlock()
            while b.isValid():
                lay = b.layout()
                t = b.text()
                n = lay.lineCount() if lay is not None else 0
                if n <= 1:
                    out.append(t)
                else:
                    for i in range(n):
                        ln = lay.lineAt(i)
                        out.append(t[ln.textStart():ln.textStart() + ln.textLength()])
                b = b.next()
            return "\n".join(out) if out else text
        except Exception:
            return text

    def _bake_hyperlinks_into_doc(self, doc, cur, links_into=None, kinds=None):
        """260615-3: 등록 하이퍼링크를 열린 doc 에 라벨 버튼+링크 주석으로 삽입.
        외부 리더에서도 클릭 동작(파일=Launch, URL=URI).

        261011-2(§4.7.16): `links_into` 를 주면 `doc` 은 **보이는 크기 임시 문서**(단추를 그린다)이고 링크 주석은
        `links_into` 의 같은 쪽에 **회전 전 좌표**로 넣는다(`insert_link` 는 회전 전 좌표를 받는다, 실측).
        `kinds` 를 주면 그 종류만(사본은 url·pdf)."""
        import fitz
        from viewer import pdf_mirror as _pm
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
            links = [ln for ln in st.links_for(cur, p0) if kinds is None or self._hl_kind(ln) in kinds]
            if not links:
                continue
            lp = links_into[p0] if links_into is not None else page
            before = _pm.link_xrefs(lp) if links_into is not None else set()
            items = []
            for ln in links:
                label = str(ln.get("name", "") or tr("링크"))
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
                    lr = _pm.to_unrotated(lp, rect) if links_into is not None else rect
                    if ln.get("kind") == "url":
                        lp.insert_link({"kind": fitz.LINK_URI, "from": lr,
                                        "uri": str(ln.get("target", ""))})
                    elif self._hl_kind(ln) == "pdf" and kinds is not None:
                        # 사본(§4.7.16)은 폴더 안 PDF 만 — 이 PDF 기준 상대 경로(폴더째 옮겨도 맞게)
                        import os as _os
                        tgt = str(ln.get("target", ""))
                        if not _os.path.isabs(tgt):
                            tgt = _os.path.join(str(getattr(st, "base", "") or ""), tgt)
                        try:
                            tgt = _os.path.relpath(tgt, str(Path(cur).parent))
                        except ValueError:
                            pass
                        lp.insert_link({"kind": fitz.LINK_GOTOR, "from": lr, "page": 0,
                                        "file": tgt.replace("\\", "/")})
                    else:
                        lp.insert_link({"kind": fitz.LINK_LAUNCH, "from": lr,
                                        "file": str(ln.get("target", ""))})
                    x += w + gap
                y += btn_h + 4
            if links_into is not None:
                _pm.tag_links(lp, before)

    @staticmethod
    def _hl_kind(ln) -> str:
        """하이퍼링크 종류 — url / pdf(폴더 안 PDF) / file(그 밖의 파일)."""
        if ln.get("kind") == "url":
            return "url"
        return "pdf" if str(ln.get("target", "")).lower().endswith(".pdf") else "file"

    def _bake_decorations(self, doc, path, *, norm=None, links=False, link_kinds=None, oc=0) -> int:
        """261011-2(§4.7.16): 꾸밈·사진(·하이퍼링크 단추)을 `doc` 에 보이는 자리 그대로 얹는다. 얹은 쪽 수.

        그 쪽의 **보이는 크기** 빈 쪽에 지금 굽기 그대로 그린 뒤 회전에 맞춰 얹는다(`pdf_mirror.place`) — 종전에는
        `/Rotate` 쪽에 보이는 좌표를 그대로 그려 꾸밈이 어긋났다(PyMuPDF 는 회전 전 좌표로 그린다, 실측).
        `oc` 를 주면 그 레이어에 묶는다(저장 사본), 0 이면 쪽 내용(평탄화·인쇄)."""
        from viewer import pdf_mirror as _pm
        norm = self._decorations_norm_for(path) if norm is None else norm
        ov = _pm.overlay_doc(doc)
        try:
            self._bake_drawings_into_doc(ov, norm or {})
            try:
                self._bake_images_into_doc(ov, path)
            except Exception:
                pass
            if links:
                try:
                    self._bake_hyperlinks_into_doc(ov, path, links_into=doc, kinds=link_kinds)
                except Exception:
                    pass
            return _pm.place(doc, ov, oc=oc)
        finally:
            ov.close()

    def _action_save_decorated_pdf(self, checked: bool = False, file_path=None):
        """평탄화해서 내보내기(옛 '저장(일반뷰어용)') — 꾸밈·사진·하이퍼링크를 **쪽 내용으로 구워** 새 PDF 로.
        261011-2(§4.7.16): 새 파일로만 — '저장' 이 이미 다른 뷰어에 보이는 사본을 현재 파일에 넣는다.

        260615-3 '(PDF 꾸밈 저장)' 을 260930-2(마스터 §4.7.13, 사용자 요청)에 이름과 범위를
        넓혔다. PolyPDF 가 따로 들고 있던 꾸밈·삽입 사진은 **다른 프로그램에서는 보이지
        않는다** — 구워야 어디서든 같게 보인다. 글자는 그대로 두므로 검색·복사도 된다.

        `file_path` 를 주면 그 파일을(책갈피창 우클릭), 없으면 본문에 열린 파일을 쓴다.
        """
        cur = str(file_path) if file_path else (
            self.main_view.current_file() if self.main_view else None)
        if not cur or not str(cur).lower().endswith(".pdf"):
            QMessageBox.information(self, tr("안내"), tr("먼저 PDF를 표시하세요."))
            return
        # 이 파일의 모든 페이지 꾸밈(선긋기) 수집
        norm = self._decorations_norm_for(cur)
        st_hl = self._ensure_hyperlink_store()
        has_hl = bool(st_hl and st_hl.pages_with_links(cur))
        # 260930-2: **사진만 있어도** 구울 것이 있다 — 종전에는 여기서 돌아서 버렸다.
        st_im = self._ensure_page_meta_store()
        has_img = bool(st_im and st_im.pages_with_images(cur))
        # 261010-13(§4.7.15): 크롭(저장 전 포함)만 있어도 평탄화해서 내보낸다 — 바깥 내용을 실제로 지운다
        has_crop = False
        try:
            from viewer import page_crop as _pc
            has_crop = _pc.has_pending(cur)
            if not has_crop:
                import fitz
                with fitz.open(str(cur)) as _d:
                    has_crop = any(_pc.is_cropped(_d[i]) for i in range(_d.page_count))
        except Exception:
            pass
        # 261011-2(§4.7.16): 저장 전 회전만 있어도 내보낸다(`/Rotate` 로). PDF `/Rotate` 는 이미 다른 뷰어에 보인다
        from viewer import page_rotate as _pr
        has_rot = _pr.has_pending(cur)
        if not norm and not has_hl and not has_img and not has_crop and not has_rot:
            QMessageBox.information(
                self, tr("안내"),
                tr("이 파일에 구울 꾸밈(선·도형·글)·사진·하이퍼링크·크롭·회전이 없습니다."))
            return
        # 260930-2: 아직 저장하지 않은 쪽 편집이 있으면 알린다 — 구운 파일은 **원본 쪽**
        #   기준이라 그 편집이 빠진다.
        try:
            tp = self.page_thumbs
            same = (getattr(tp, "_doc", None) is not None
                    and str(tp._doc.path) == str(cur))
            if same and tp.is_page_dirty():
                if QMessageBox.question(
                        self, tr("평탄화해서 내보내기"),
                        tr("저장하지 않은 쪽 편집(순서·삭제·끼워 넣은 쪽)이 있습니다. "
                        "지금 구우면 그 편집은 빠집니다. 계속할까요?")
                ) != QMessageBox.StandardButton.Yes:
                    return
        except Exception:
            pass
        self._apply_drawings_to_pdf(norm, cur, with_hyperlinks=True)

    # ===== 261011-2(마스터 §4.7.16): '저장' 이 다른 뷰어용 사본을 PDF 에 ============
    def _mirror_payload(self, path) -> dict:
        """옆 파일에 있는 이 파일의 꾸밈·사진·하이퍼링크(url·pdf)·태그 — 사본의 원본."""
        path = str(path)
        out = {"v": 1, "deco": {}, "img": {}, "link": {}, "tags": []}
        try:
            out["deco"] = {str(k): v for k, v in (self._decorations_norm_for(path) or {}).items() if v}
        except Exception:
            pass
        st_im = self._ensure_page_meta_store()
        if st_im:
            for p in sorted(st_im.pages_with_images(path)):
                im = st_im.get_images(path, p)
                if im:
                    out["img"][str(p)] = im
        st_hl = self._ensure_hyperlink_store()
        if st_hl:
            for p in sorted(st_hl.pages_with_links(path)):
                ls = [ln for ln in st_hl.links_for(path, p) if self._hl_kind(ln) in ("url", "pdf")]
                if ls:
                    out["link"][str(p)] = ls
        try:
            out["tags"] = list(self.bookmark_tree._tags.get(path) or []) if self.bookmark_tree._tags else []
        except Exception:
            pass
        return out

    def _mirror_open(self, path):
        """사본을 읽고 쓸 수 있게 연 문서, 또는 (None, 까닭) — 'signed' | 'locked' | 'error'."""
        import fitz
        try:
            d = fitz.open(str(path))
        except Exception:
            return None, "error"
        if d.needs_pass:
            from viewer import secure_store
            pw = secure_store.recall_any(str(path))
            if not (pw and d.authenticate(pw)):
                d.close()
                return None, "locked"
        try:
            perm = int(getattr(d, "permissions", -1))
            if perm != -1 and not (perm & fitz.PDF_PERM_MODIFY):
                d.close()
                return None, "locked"
        except Exception:
            pass
        from viewer import sign_core
        if sign_core.doc_is_signed(d):
            d.close()
            return None, "signed"
        return d, ""

    def _mirror_state(self, path):
        """(해야 하나, 까닭, 지문). 까닭: '' | 'signed' | 'locked' | 'error'."""
        from viewer import pdf_mirror as _pm
        if not str(path).lower().endswith(".pdf") or not Path(str(path)).exists():
            return False, "error", ""
        payload = self._mirror_payload(path)
        has = bool(payload["deco"] or payload["img"] or payload["link"] or payload["tags"])
        d, why = self._mirror_open(path)
        if d is None:
            return False, why if has else "", ""
        try:
            old = _pm.stored_hash(d)
            if not has and not old:
                return False, "", ""
            h = _pm.fingerprint(dict(payload, geom=_pm.geometry(d)))
            return h != old, "", h
        finally:
            d.close()

    def _mirror_needed(self, path) -> bool:
        try:
            return bool(self._mirror_state(path)[0])
        except Exception:
            return False

    def _mirror_to_pdf(self, path, page=None) -> bool:
        """사본이 낡았으면 원본 사본 + **증분 저장**으로 임시 파일을 만들어 `_finalize_save` 로 놓는다. 넣었으면 True.
        Qt 굽기(임시 쪽 그리기)는 메인, 파일 복사·저장은 배경(응답성 SOT §4.4)."""
        import os as _os
        import shutil as _sh
        from viewer import pdf_mirror as _pm
        try:
            need, why, h = self._mirror_state(path)
        except Exception:
            return False
        if why == "signed":
            self.status.showMessage(tr("서명된 문서라 다른 뷰어용 사본(꾸밈·링크·태그)은 넣지 않았습니다 — 평탄화해서 내보내기를 쓰세요."), 8000)
            return False
        if why == "locked":
            self.status.showMessage(tr("편집 권한이 없는 암호 문서라 다른 뷰어용 사본은 넣지 않았습니다."), 8000)
            return False
        if not need:
            return False
        src = Path(str(path))
        tmp = src.with_name("~" + src.stem + ".polypdf-tmp")
        err = self._file_op_bg(lambda: _sh.copyfile(str(src), str(tmp)), tr("저장 중: {name}").format(name=src.name))
        if err is not None:
            self._sign_unlink(str(tmp))
            return False
        doc = None
        try:
            import fitz
            doc = fitz.open(str(tmp))
            if doc.needs_pass:
                from viewer import secure_store
                doc.authenticate(secure_store.recall_any(str(src)) or "")
            payload = self._mirror_payload(src)
            _pm.remove_layer(doc)
            _pm.remove_links(doc)
            if payload["deco"] or payload["img"] or payload["link"]:
                oc = _pm.ensure_layer(doc)
                self._bake_decorations(doc, str(src), links=bool(payload["link"]), link_kinds=("url", "pdf"), oc=oc)
            if payload["tags"]:
                _pm.set_keywords(doc, ", ".join(str(t) for t in payload["tags"]))
            _pm.store_hash(doc, _pm.fingerprint(dict(payload, geom=_pm.geometry(doc))))
        except Exception:
            if doc is not None:
                doc.close()
            self._sign_unlink(str(tmp))
            return False
        res = self._run_merge_job(lambda progress: (progress(0, 1, tr("저장 중")), doc.saveIncr(), progress(1, 1, tr("완료"))),
                                  tr("저장"), cancellable=False)
        doc.close()
        if not res.get("ok"):
            self._sign_unlink(str(tmp))
            return False
        # `_finalize_save` 가 본문 문서를 닫는다 — 본문이 이 파일이었는지는 **그 전에** 본다
        mv = self.main_view
        was_open = bool(mv is not None and mv.current_file()
                        and _os.path.normcase(str(mv.current_file())) == _os.path.normcase(str(src)))
        cur_page = mv.current_page() if (was_open and page is None) else (page or 0)
        try:
            final = self._finalize_save(str(src), str(tmp), False)
        except Exception as e:
            self._sign_unlink(str(tmp))
            from viewer.file_overwrite import SaveCancelled
            if not isinstance(e, SaveCancelled):
                QMessageBox.warning(self, tr("저장 실패"), str(e))
            return False
        if was_open:
            try:
                self._open_saved_file(final, cur_page)
            except Exception:
                pass
        return True

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
        """260905(발표 SOT §4.2.1): (top%, bottom%, left%, right%) 4원소."""
        st = self._ensure_page_meta_store()
        return st.get_crop(path, page0) if st else (0.0, 0.0, 0.0, 0.0)

    def _hidden_for(self, path):
        st = self._ensure_page_meta_store()
        return st.hidden_pages(path) if st else set()

    def _rotation_for(self, path, page0):
        """발표 보기의 화면 회전 — 261011-2(§4.7.16)부터 0: 회전은 `PdfDocument` 가 문서 `/Rotate` 에 덧입혀 그린다."""
        return 0

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
            self.status.showMessage(tr("편집 내용을 저장했습니다."), 3000)
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
        try:                             # 261010-13(§4.7.15): 저장 전 크롭도 되돌린다
            cur = self.main_view.current_file() if self.main_view else None
            if cur:
                if not self._discard_crop(cur):
                    self._reload_rotation(cur)   # 261011-2: 되돌린 회전(page_meta)을 문서 `/Rotate` 에도
        except Exception:
            pass
        try:
            self.status.showMessage(tr("편집 수정 사항을 취소(되돌리기)했습니다."), 3000)
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
        box.setWindowTitle(tr("편집 변경사항"))
        box.setText(tr('저장하지 않은 편집 변경사항이 있습니다.\n{v}').format(v=tr('다른 파일로 이동하기 전에 어떻게 할까요?') if switching else tr('편집을 종료하기 전에 어떻게 할까요?')))
        b_save = box.addButton(tr("저장"), QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton(tr("되돌리기(저장 안 함)"), QMessageBox.ButtonRole.DestructiveRole)
        b_keep = box.addButton(tr("계속 편집"), QMessageBox.ButtonRole.RejectRole)
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
            # 261010-13(§4.7.15): 저장 전 크롭도 미저장 변경이다 — 저장하면 쪽 편집 저장 길로 원본에, 버리면 되돌린다
            from viewer import page_crop as _pc
            _cur = self.main_view.current_file() if self.main_view else None
            from viewer import page_rotate as _pr       # 261011-2(§4.7.16): 저장 전 회전도 같은 미저장 변경
            crop_dirty = bool(_cur and (_pc.has_pending(_cur) or _pr.has_pending(_cur)))
            if (self._edit_snap is not None and self._edit_dirty) or crop_dirty:
                choice = self._confirm_edit_save(switching=False)
                if choice == "cancel":
                    # 편집 유지 — 버튼 다시 켜기(정상 toggled 로 모든 핸들러 복원)
                    self.bookmark_tree.btn_edit.setChecked(True)
                    return
                if choice == "save":
                    if self._edit_snap is not None and self._edit_dirty:
                        self._commit_edit()
                    if crop_dirty:
                        self._save_page_edits_for(_cur)
                else:
                    if self._edit_snap is not None and self._edit_dirty:
                        self._restore_edit()
                    if crop_dirty:
                        if not self._discard_crop(_cur):
                            self._reload_rotation(_cur)
            self._edit_snap = None
            self._edit_dirty = False
        for mv in self._mv:
            try:
                self._init_draw_config(mv)
                mv.set_draw_mode(bool(on))
            except Exception:
                pass

    def _reload_rotation(self, path):
        """261011-2(§4.7.16): page_meta 회전이 바뀐 뒤(되돌리기) 문서를 다시 열어 `/Rotate` 덧입히기를 맞춘다."""
        from viewer import page_rotate as _pr
        _pr.bump(path)
        self._crop_reload(path)
        self._refresh_hidden_ui(path)

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
        # 261011-2(§4.7.16): 회전은 쪽 `/Rotate` — 열린 문서에 덧입혀 다시 연다(저장 전 크롭과 같은 길). 💾 저장이 PDF 에 넣는다
        from viewer import page_rotate as _pr
        _pr.bump(cur)
        self._crop_reload(cur)
        self._refresh_hidden_ui(cur)
        if _pr.has_pending(cur):
            self.status.showMessage(tr("회전 — [저장] 을 누르면 PDF 에 들어가 다른 뷰어에서도 바로 보입니다."), 6000)

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
            # 260915-1(마스터 §4.7.7): 저장 전 쪽 이동·삭제가 있으면 본문 넘김도 **썸네일 순서**를
            #   따른다(지운 쪽은 건너뛴다). 썸네일이 이 창의 문서일 때만.
            seq = None
            try:
                same = (getattr(tp, "_doc", None) is not None
                        and str(tp._doc.path) == str(mv.current_file()))
                if same and tp.is_page_dirty():
                    # 260930-2(§4.7.12): 넘김은 **보이는 대로** 간다 — 끼워 둔 쪽도 자리를
                    #   차지한다. 저장용 목록(`current_page_sequence`)은 자체 쪽만이라 다르다.
                    seq = tp.current_nav_ids()
            except Exception:
                seq = None
            if getattr(tp, "_filter", "all") == "all" and not seq:
                mv.set_nav_pages(None)
                return
            n = mv._doc.page_count
            base = seq if seq else range(n)
            # 스테이징 쪽에는 필터(보임/꾸밈/숨김)가 없다 — 늘 보인다.
            pages = [p for p in base
                     if tp.is_staged_page(p) or tp.page_visible_in_filter(p)]
            if not pages:
                pages = [mv._current_page]   # 빈 필터 → 현재 페이지에 고정
            mv.set_nav_pages(pages, ordered=bool(seq))
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
        rots = {}                 # 261011-2(§4.7.16): 회전은 문서 `/Rotate` 로 그린다 — 화면 픽스맵 돌리기(보기 회전)는 쓰지 않는다
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
