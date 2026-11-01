# -*- coding: utf-8 -*-
"""이미지 넣기 · 등록 이미지 — 앱 쪽 (261101-3, 마스터 §4.6.11).

방식은 §11.11 표준: 믹스인(`class MainWindow(…, StampMixin, …)`).
본문 단추·도구는 `MainView`(이미지 ▾ → `imageMenuRequested`, 영역 → `stampRegionSelected`), 보관은 `stamp_store`,
그림 만들기·자리 계산은 `stamp_core`, 창은 `widgets/stamp_dialog`.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QInputDialog

from viewer.i18n import tr

MULTI_ASK = 30            # 이보다 많은 쪽에 넣으면 묻는다


class StampMixin:
    def _wire_stamp(self, mv) -> None:
        mv.imageMenuRequested.connect(lambda k, v=mv: self._on_image_menu(k, v))
        mv.stampRegionSelected.connect(lambda r, v=mv: self._on_stamp_region(r, v))

    def _on_image_menu(self, key: str, mv=None) -> None:
        mv = mv or self.main_view
        if key == "file":
            self._insert_image_from_file()
        elif key == "clip":
            if not mv.paste_image_from_clipboard():
                self.status.showMessage(tr("클립보드에 그림이 없습니다."), 4000)
        elif key == "region":
            if mv.is_two_page_mode():
                QMessageBox.information(self, tr("등록 이미지"), tr("2쪽 보기에서는 영역을 정할 수 없습니다. 1쪽 보기로 바꾼 뒤 다시 하세요."))
                return
            mv.set_draw_tool(None)                    # 글쓰기 등이 켜져 있으면 누르기를 먼저 가져간다(보안 SOT §3.3 과 같은 이유)
            mv.view.arm_block_select(True, purpose="stamp")
            self.status.showMessage(tr("등록할 영역을 끌어 고르세요 — 글자층이 있으면 선명하게(PDF 그대로) 등록합니다."), 8000)
        elif key == "manage":
            self._stamp_manage()

    def _stamp_manage(self) -> None:
        from viewer.widgets.stamp_dialog import StampManagerDialog
        StampManagerDialog(self, shots=self._shot_image_paths).exec()

    def _on_stamp_region(self, scene_rect, mv=None) -> None:
        import fitz
        from viewer.widgets import stamp_dialog
        mv = mv or self.main_view
        if mv is None or mv._doc is None:
            return
        z = mv._zoom or 1.0
        pidx = int(mv.current_page())
        doc = mv._doc.doc
        r = fitz.Rect(scene_rect.left() / z, scene_rect.top() / z, scene_rect.right() / z, scene_rect.bottom() / z)
        r &= doc[pidx].rect
        if r.width < 4 or r.height < 4:
            self.status.showMessage(tr("영역이 너무 작습니다 — 끌어서 고르세요."), 4000)
            return
        e = stamp_dialog.register(stamp_dialog.edit_from_pdf_region(self, doc, pidx, r, name=Path(str(mv.current_file() or "")).stem))
        if e:
            mv.pick_stamp(e["id"])
            self.status.showMessage(tr("'{name}' 을(를) 등록했습니다 — 본문을 누르면 그 자리에 실제 크기로 넣습니다.").format(name=e["name"]), 6000)

    def _stamp_register_selected(self, mv=None) -> None:
        """사진 꾸밈 우클릭 '등록 이미지로 등록…'."""
        from viewer.widgets import stamp_dialog
        import base64, io
        from PIL import Image
        mv = mv or self.main_view
        o = mv.selected_image_object()
        if o is None:
            return
        pdf = (o.get("extra") or {}).get("pdf")
        sz = mv.page_size_pt()
        w_mm = (o["rect"][2] * sz[0] / (72.0 / 25.4)) if sz else None
        try:
            if pdf:
                dlg = stamp_dialog.StampEditDialog(self, name=(o.get("extra") or {}).get("stamp", ""),
                                                   pdf=base64.b64decode(pdf), width_mm=w_mm, kind="pdf")
                res = dlg.result_value() if dlg.exec() else None
            else:
                data = o.get("data") or mv._pix_to_b64(o["pix"])
                res = stamp_dialog.edit_from_image(self, Image.open(io.BytesIO(base64.b64decode(data))), width_mm=w_mm)
        except Exception:
            res = None
        e = stamp_dialog.register(res)
        if e:
            self.status.showMessage(tr("'{name}' 을(를) 등록했습니다.").format(name=e["name"]), 5000)

    def _stamp_to_pages(self, mv=None) -> None:
        """'다른 쪽에도 넣기…' — 모든 쪽 / 쪽 범위. 같은 mm 크기, 가까운 모서리로부터 같은 거리(§4.6.11)."""
        from viewer import stamp_core
        from viewer.page_crop import parse_range
        mv = mv or self.main_view
        o = mv.selected_image_object()
        path = str(mv.current_file() or "")
        sz = mv.page_size_pt()
        st = self._ensure_page_meta_store()
        if o is None or not path or sz is None or st is None or mv._doc is None:
            return
        doc = mv._doc.doc
        n = doc.page_count
        txt, ok = QInputDialog.getText(self, tr("다른 쪽에도 넣기"),
                                       tr("쪽 범위(예: 1-3, 5) — 비우면 모든 쪽({n}쪽)").format(n=n))
        if not ok:
            return
        try:
            pages = sorted(set(parse_range(txt, n))) if txt.strip() else list(range(n))
        except Exception:
            pages = []
        src = int(mv.current_page())
        pages = [p for p in pages if p != src]
        if not pages:
            QMessageBox.information(self, tr("다른 쪽에도 넣기"), tr("넣을 다른 쪽이 없습니다. 예: 1-3, 5"))
            return
        if len(pages) > MULTI_ASK and QMessageBox.question(
                self, tr("다른 쪽에도 넣기"), tr("{n}쪽에 넣습니다. 계속할까요?").format(n=len(pages))) != QMessageBox.StandardButton.Yes:
            return
        mv._commit_text_editor()
        mv._save_page_images()
        base = dict(o.get("extra") or {}, data=o["data"] or mv._pix_to_b64(o["pix"]), shape=o["shape"],
                    alpha=int(o["alpha"]), rot=round(float(o.get("rot", 0.0)), 2))
        rots = getattr(mv, "_rotations", {}) or {}
        done = 0
        for p in pages:
            r = doc[p].rect
            pw, ph = (r.height, r.width) if rots.get(p, 0) % 180 == 90 else (r.width, r.height)
            rect = [round(v, 5) for v in stamp_core.same_corner_rect(o["rect"], sz[0], sz[1], pw, ph)]
            cur = st.get_images(path, p)
            if any(d.get("data") == base["data"] and all(abs(a - b) < 1e-3 for a, b in zip(d.get("rect", []), rect))
                   for d in cur):
                continue                                  # 같은 자리에 같은 그림 — 건너뛴다
            new = list(cur) + [dict(base, rect=rect)]
            self._hist_record(path, "images", p, cur, new)
            st.set_images(path, p, new)
            done += 1
        if done:
            self._persist_meta(st)
            self._refresh_hidden_ui(path)
        self.status.showMessage(tr("{n}쪽에 넣었습니다(미저장) — 💾 ‘저장’ 을 눌러 반영하세요.").format(n=done), 6000)
