# -*- coding: utf-8 -*-
"""서명 자리(초안) → 일괄 확정 → 서명 편집 — `MainWindow` 믹스인 (보안 SOT §3.3·§3.4·§3.10·§3.11).

  자리 놓기(`_sign_add_draft`) → 본문 위 위젯으로 옮기기·크기·지우기(`SignDraftLayer`)
  → [서명 확정…](`action_sign_confirm`): 바탕 → 그림만(증분) → 새 자리 전자서명 → 빈 칸 채우기 → 별도 파일 `<이름>_서명.pdf`
  → [서명 편집](`action_sign_edit`): 서명 파일의 바탕을 되살려 자리를 다시 놓는다 → 다시 확정하면 그 서명 파일을 바꾼다.

원본 파일에는 아무것도 쓰지 않는다(§3.4). 무거운 일(서명·그림 넣기·바탕 자르기·미리보기)은 배경(§10).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SignDraftMixin:
    # ---- 본문에 붙이기 ----------------------------------------------------------
    def _sign_drafts_attach(self, mv, idx: int) -> None:
        from viewer.widgets.sign_draft_layer import SignDraftLayer
        lay = SignDraftLayer(mv, self._sign_draft_items)
        lay.changed.connect(lambda i, r, v=mv: self._sign_draft_moved(v, i, r))
        lay.removed.connect(lambda i, v=mv: self._sign_draft_remove(v, i))
        lay.menuRequested.connect(lambda i, g, v=mv: self._sign_draft_menu(v, i, g))
        mv.sign_draft_band.confirmRequested.connect(lambda i=idx: (self._set_active_pane(i), self.action_sign_confirm()))
        mv.sign_draft_band.clearRequested.connect(lambda v=mv: self._sign_drafts_clear(v))

    def _sign_view_fp(self) -> str:
        """자리 미리보기에 쓸 ID — 서명을 시작할 때 연 ID(고른 것), 아직 안 열었으면 기본 ID(없으면 첫 ID)."""
        from viewer import sign_store
        fp = self._sign_current_fp() if hasattr(self, "_sign_current_fp") else ""
        if fp:
            return fp
        d = sign_store.load()
        e = next((x for x in d["ids"] if x.get("fp") == d.get("default_id")), None) or (d["ids"][0] if d["ids"] else {})
        return str(e.get("fp", ""))

    def _sign_view_appearance(self):
        """자리 미리보기·확정 기본값 — 기억한 겉모양 + **그 ID 의** 서명 그림(켰을 때, 261031-1) + 그 ID 이름 줄."""
        from viewer import sign_core, sign_store
        d = sign_store.load()
        a = d.get("appearance") or {}
        fp = self._sign_view_fp()
        app = sign_core.Appearance(image_path=sign_store.id_image_path(fp) if a.get("show_image", True) else "",
                                   show_name=bool(a.get("show_name", True)), show_date=bool(a.get("show_date", True)),
                                   show_reason=bool(a.get("show_reason", False)), font_path=sign_core.default_font(),
                                   layout=str(a.get("layout") or sign_core.LAYOUT_DEFAULT))
        e = sign_store.get_id(fp) or {}
        return app, sign_core.signer_label(e.get("name", ""), e.get("email", "")), str(d.get("last_reason", "") or "")

    @staticmethod
    def _sign_draft_image(d: dict) -> str:
        """그림만 자리의 그림 — 그 자리의 ID 의 서명 그림(261031-1). 옛 기록(그림 이름)은 그 그림."""
        from viewer import sign_store
        if d.get("fp"):
            return sign_store.id_image_path(d["fp"])
        return sign_store.image_path(d.get("image", "")) if d.get("image") else ""

    def _sign_draft_items(self, path: str, page: int) -> list:
        """`SignDraftLayer` 의 provider — 그 쪽 자리 + 글자 줄 높이 + 미리보기(없으면 배경에서 그리기 시작)."""
        from viewer import sign_drafts, sign_store, sign_core
        items = [d for d in sign_drafts.drafts(path) if d["page"] == int(page)]
        if not items:
            return []
        app, label, reason = self._sign_view_appearance()
        out = []
        for d in items:
            x0, y0, x1, y1 = d["rect"]
            w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
            if d["kind"] == "image":
                ip = self._sign_draft_image(d) or sign_store.id_image_path(self._sign_view_fp())
                key = ("image", ip)
                strip = 0.0
                pix = self._sign_pix_cache().get(key)
                if pix is None and ip:
                    from PyQt6.QtGui import QPixmap
                    pix = QPixmap(ip)
                    self._sign_pix_cache()[key] = pix
            else:
                if d["field"]:
                    tw, th = w, h
                else:
                    tw, th = sign_core.stamp_size(app, label, reason, w, h)
                strip = th - h
                key = ("sign", round(tw, 1), round(th, 1), app.image_path, app.layout, app.show_name, app.show_date,
                       app.show_reason, label, reason)
                pix = self._sign_pix_cache().get(key)
                if pix is None:
                    self._sign_preview_start(key, (app, label, reason, tw, th, 110))
            out.append({"id": d["id"], "rect": d["rect"], "strip": strip, "pix": pix, "kind": d["kind"],
                        "fixed": bool(d["field"])})
        return out

    def _sign_pix_cache(self) -> dict:
        c = getattr(self, "_sign_pix", None)
        if c is None:
            c = self._sign_pix = {}
        if len(c) > 64:
            c.clear()
        return c

    def _sign_preview_start(self, key, args) -> None:
        busy = getattr(self, "_sign_pv_busy", None)
        if busy is None:
            busy = self._sign_pv_busy = {}
        if key in busy:
            return
        # 261012-16(응답성 SOT §4.3): 서명 자리 미리보기 — 워커 + `run_in_thread`
        from viewer.workers import SignPreviewWorker, run_in_thread
        w = SignPreviewWorker(key, args)
        busy[key] = True

        def _got(k, res):
            busy.pop(k, None)
            self._sign_preview_done(k, res)
        w.done.connect(_got)
        run_in_thread(w, self._thread_keep)

    def _sign_preview_done(self, key, res) -> None:
        from PyQt6.QtGui import QPixmap
        pm = QPixmap()
        if isinstance(res, (bytes, bytearray)):
            pm.loadFromData(bytes(res), "PNG")
        self._sign_pix_cache()[key] = pm                     # 그리지 못했으면 빈 그림 — 점선 상자만
        for mv in getattr(self, "_mv", []) or [self.main_view]:
            lay = getattr(mv, "sign_draft_layer", None)
            if lay is not None:
                lay.refresh()

    def _sign_drafts_sync(self, mv=None) -> None:
        """자리 띠·위젯을 지금 파일에 맞춘다."""
        from viewer import sign_drafts
        for v in ([mv] if mv is not None else (getattr(self, "_mv", None) or [self.main_view])):
            if v is None:
                continue
            cur = v.current_file()
            ds = sign_drafts.drafts(cur) if cur else []
            out = sign_drafts.out_of(cur) if (cur and ds) else ""
            v.sign_draft_band.show_counts(sum(1 for d in ds if d["kind"] == "sign"),
                                          sum(1 for d in ds if d["kind"] == "image"),
                                          Path(out).name if out else "")
            lay = getattr(v, "sign_draft_layer", None)
            if lay is not None:
                lay.refresh()

    # ---- 자리 놓기·다듬기 ------------------------------------------------------
    @staticmethod
    def _sign_tools_off(mv) -> None:
        """그리기 도구를 끈다 — 글쓰기 도구가 켜져 있으면 본문 누르기를 글상자 만들기가 먼저 가져가
        서명 자리가 정해지지 않았다(261012-1 사용자 보고, SOT §3.3)."""
        try:
            mv._commit_text_editor()
        except Exception:
            pass
        try:
            if getattr(mv, "_draw_tool", None) is not None or getattr(mv, "_draw_kind", None):
                mv.set_draw_tool(None)
        except Exception:
            pass

    def _sign_add_draft(self, mv, cur: str, page: int, rect, kind: str = "sign", field: str = "", auto: bool = False) -> str:
        """자리 하나를 기록에 더한다. 전자서명 자리는 아래 글자 줄까지 쪽 안에 들게 위로 민다."""
        from viewer import sign_drafts, sign_core, sign_store
        import fitz
        r = fitz.Rect(rect)
        if kind == "sign" and not field:
            pr = mv._doc.doc[page].rect
            app, label, reason = self._sign_view_appearance()
            _tw, th = sign_core.stamp_size(app, label, reason, r.width, r.height)
            over = r.y0 + th - pr.y1
            if over > 0:
                r = fitz.Rect(r.x0, max(pr.y0, r.y0 - over), r.x1, max(pr.y0, r.y0 - over) + r.height)
        ds = sign_drafts.drafts(cur)
        d = {"id": sign_drafts.new_id(), "page": int(page), "rect": [r.x0, r.y0, r.x1, r.y1], "kind": kind,
             "image": "", "field": field, "fp": self._sign_view_fp() if kind == "image" else "",
             "auto": bool(auto and not field)}
        ds.append(d)
        sign_drafts.set_drafts(cur, ds)
        self._sign_drafts_sync(mv)
        lay = getattr(mv, "sign_draft_layer", None)
        b = lay.box_for(d["id"]) if lay is not None else None
        if b is not None:
            b.setFocus()
        self.status.showMessage(tr("서명 자리를 놓았습니다 — 옮기거나 크기를 바꾼 뒤 [서명 확정…] 을 누르세요."), 8000)
        return d["id"]

    def _sign_draft_moved(self, mv, draft_id: str, rect) -> None:
        from viewer import sign_drafts
        cur = mv.current_file()
        if not cur:
            return
        ds = sign_drafts.drafts(cur)
        for d in ds:
            if d["id"] == draft_id and not d["field"]:
                new = [float(v) for v in rect]
                ow, oh = d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1]
                if abs((new[2] - new[0]) - ow) > 0.5 or abs((new[3] - new[1]) - oh) > 0.5:
                    d["auto"] = False            # 손잡이로 크기를 정했다 — 이제 실제 크기를 따르지 않는다(261031-6)
                d["rect"] = new
        sign_drafts.set_drafts(cur, ds)
        self._sign_drafts_sync(mv)
        lay = getattr(mv, "sign_draft_layer", None)
        b = lay.box_for(draft_id) if lay is not None else None
        if b is not None:
            b.setFocus()

    def _sign_draft_remove(self, mv, draft_id: str) -> None:
        from viewer import sign_drafts
        cur = mv.current_file()
        if not cur:
            return
        left = [d for d in sign_drafts.drafts(cur) if d["id"] != draft_id]
        sign_drafts.set_drafts(cur, left)
        if not left:
            self._sign_lock()                    # 자리를 모두 지웠다 = 서명 취소 — 연 열쇠를 버린다(261031-1)
        self._sign_drafts_sync(mv)

    def _sign_drafts_clear(self, mv) -> None:
        from viewer import sign_drafts
        cur = mv.current_file()
        if not cur or not sign_drafts.drafts(cur):
            return
        if QMessageBox.question(self, tr("서명 자리"), tr("이 파일의 서명 자리를 모두 지울까요?")) != QMessageBox.StandardButton.Yes:
            return
        sign_drafts.clear(cur)
        self._sign_lock()
        self._sign_drafts_sync(mv)

    def _sign_draft_menu(self, mv, draft_id: str, gpos) -> None:
        from PyQt6.QtWidgets import QMenu
        from viewer import sign_drafts, sign_store
        cur = mv.current_file()
        ds = sign_drafts.drafts(cur) if cur else []
        d = next((x for x in ds if x["id"] == draft_id), None)
        if d is None:
            return
        # 261031-1(사용자 지시): 확정 전에 자리 옵션으로 디지털 ID(연 것)·서명 그림·겉모양 글자를 바꾼다 — 고른 것은 다음에도 그대로
        st = sign_store.load()
        ap = st.get("appearance") or {}
        creds = self._sign_creds()
        cur_fp = d.get("fp") if d["kind"] == "image" and d.get("fp") else self._sign_view_fp()
        from PyQt6.QtGui import QActionGroup
        m = QMenu(self)
        # 261031-6(사용자 지시): 하나만 고르는 것은 옵션 단추 — 배타 묶음(QActionGroup)이면 메뉴가 동그라미 표시로 그린다
        g_kind = QActionGroup(m)
        g_kind.setExclusive(True)
        a_sign = m.addAction(tr("전자서명"))
        a_img = m.addAction(tr("그림만(전자서명 아님)"))
        for a, k in ((a_sign, "sign"), (a_img, "image")):
            a.setCheckable(True)
            g_kind.addAction(a)
            a.setChecked(d["kind"] == k)
            a.setEnabled(not d["field"])
        m.addSeparator()
        sub = m.addMenu(tr("디지털 ID"))
        g_id = QActionGroup(sub)
        g_id.setExclusive(True)
        id_acts = {}
        for e in st["ids"]:
            if e.get("fp") not in creds:
                continue
            a = sub.addAction(e.get("name", "") + (f" <{e['email']}>" if e.get("email") else ""))
            a.setCheckable(True)
            g_id.addAction(a)
            a.setChecked(e.get("fp") == cur_fp)
            id_acts[a] = e["fp"]
        sub.addSeparator()
        a_more = sub.addAction(tr("다른 디지털 ID 열기…"))
        # 261031-10(사용자 지시): 서명 그림·폭·ID 내용은 디지털 ID 관리에서만 — 지금 ID 를 골라 연다(닫으면 이 서명에 반영)
        a_manage = sub.addAction(tr("디지털 ID 관리…"))
        has_img = bool(sign_store.id_image_path(cur_fp))
        a_show_img = m.addAction(tr("서명 그림"))
        a_show_img.setCheckable(True)
        a_show_img.setChecked(has_img and (d["kind"] == "image" or bool(ap.get("show_image", True))))
        a_show_img.setEnabled(has_img and d["kind"] == "sign")
        txt_acts = {}
        for k, label in (("show_name", tr("이름")), ("show_date", tr("날짜"))):
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(ap.get(k, True)))
            a.setEnabled(d["kind"] == "sign")
            txt_acts[a] = k
        m.addSeparator()
        a_copy = m.addAction(tr("다른 쪽에도 놓기…"))
        a_copy.setEnabled(not d["field"])
        m.addSeparator()
        a_del = m.addAction(tr("지우기"))
        got = m.exec(gpos)
        if got is None:
            return
        if got is a_del:
            self._sign_draft_remove(mv, draft_id)
            return
        if got is a_copy:
            self._sign_draft_copy(mv, cur, d)
            return
        if got is a_more:
            if self._sign_unlock(more=True):
                self._sign_draft_use_id(cur, ds, d, self._sign_current_fp())
            return
        if got in id_acts:
            self._sign_draft_use_id(cur, ds, d, id_acts[got])
            return
        if got is a_manage:
            self._sign_manage_ids(cur_fp)                     # 그림·폭이 바뀌었으면 클릭 자리는 새 실제 크기로(그 안에서)
            return
        if got is a_show_img or got in txt_acts:
            key = "show_image" if got is a_show_img else txt_acts[got]
            new = {"show_image": bool(ap.get("show_image", True)), "show_name": bool(ap.get("show_name", True)),
                   "show_date": bool(ap.get("show_date", True)), "show_reason": bool(ap.get("show_reason", False))}
            new[key] = got.isChecked()
            from viewer import sign_core
            app, label, reason = self._sign_view_appearance()
            app.image_path = sign_store.id_image_path(cur_fp) if new["show_image"] else ""
            app.show_name, app.show_date, app.show_reason = new["show_name"], new["show_date"], new["show_reason"]
            if not sign_core.has_content(app, label, reason):
                from viewer.widgets.sign_dialogs import empty_appearance_text
                QMessageBox.information(self, tr("서명 자리"), empty_appearance_text())
                return
            from viewer.widgets.sign_dialogs import remember_appearance
            remember_appearance(**{key: new[key]})
            self._sign_drafts_sync()
            return
        if got is a_sign:
            d["kind"] = "sign"
        elif got is a_img:
            d["kind"] = "image"
            d["fp"] = d.get("fp") or cur_fp
            if not sign_store.id_image_path(d["fp"]):
                if QMessageBox.question(self, tr("그림만 넣기"), tr("이 디지털 ID 에 서명 그림이 없습니다. 디지털 ID 관리에서 넣을까요?")
                                        ) != QMessageBox.StandardButton.Yes:
                    return
                d["fp"] = self._sign_manage_ids(d["fp"])
                if not sign_store.id_image_path(d["fp"]):
                    return
                ds = sign_drafts.drafts(cur)                  # 관리 창이 자리 기록을 고쳤을 수 있다 — 다시 읽어 종류만 바꾼다
                for x in ds:
                    if x["id"] == d["id"]:
                        x["kind"], x["fp"] = "image", d["fp"]
        else:
            return
        sign_drafts.set_drafts(cur, ds)
        self._sign_drafts_sync(mv)

    def _sign_draft_use_id(self, cur: str, ds: list, d: dict, fp: str) -> None:
        """자리 옵션에서 디지털 ID 를 바꾼다 — 전자서명 자리는 모두 그 ID 로(확정 창도 같은 ID), 그림만 자리는 그 자리만.
        고른 ID 는 다음에도 그대로(기본 ID 로 기억, 261031-1)."""
        from viewer import sign_drafts
        if not fp:
            return
        if d["kind"] == "image":
            d["fp"] = fp
            sign_drafts.set_drafts(cur, ds)
            self._sign_resize_auto(self.main_view, cur, fp, only=d["id"])
        else:
            self._sign_cur_fp = fp
            from viewer.widgets.sign_dialogs import remember_appearance
            remember_appearance(fp=fp)
            self._sign_resize_auto(self.main_view, cur, fp)
        self._sign_drafts_sync()

    def _sign_resize_auto(self, mv, cur: str, fp: str, only: str = "") -> None:
        """클릭으로 놓은 자리(`auto`)를 그 ID 의 **실제 크기**로 다시 맞춘다 — 왼쪽 위 그대로(보안 SOT §3.3, 261031-6).
        `only` 가 없으면 그 ID 를 쓰는 자리 모두(전자서명 자리 = 지금 ID, 그림만 자리 = 자리의 `fp`)."""
        from viewer import sign_drafts, sign_core
        import fitz
        if not cur or mv is None or getattr(mv, "_doc", None) is None:
            return
        ds = sign_drafts.drafts(cur)
        sign_fp = self._sign_view_fp()
        w, h = self._sign_real_size(fp)
        changed = False
        for d in ds:
            if not d.get("auto") or d["field"] or (only and d["id"] != only):
                continue
            uses = d.get("fp") if d["kind"] == "image" else sign_fp
            if not only and uses != fp:
                continue
            try:
                pr = mv._doc.doc[d["page"]].rect
            except Exception:
                continue
            r = self._sign_fit_real(pr, d["rect"][0], d["rect"][1], w, h)
            if d["kind"] == "sign":
                app, label, reason = self._sign_view_appearance()
                _tw, th = sign_core.stamp_size(app, label, reason, r.width, r.height)
                over = r.y0 + th - pr.y1
                if over > 0:
                    y0 = max(pr.y0, r.y0 - over)
                    r = fitz.Rect(r.x0, y0, r.x1, y0 + r.height)
            d["rect"] = [r.x0, r.y0, r.x1, r.y1]
            changed = True
        if changed:
            sign_drafts.set_drafts(cur, ds)

    def _sign_draft_copy(self, mv, cur: str, d: dict) -> None:
        """'다른 쪽에도 놓기…' — 모든 쪽 / 쪽 범위(SOT §3.6). 같은 자리·종류·그림, 쪽 밖이면 쪽 안으로."""
        from PyQt6.QtWidgets import QInputDialog
        from viewer import sign_drafts
        from viewer.page_crop import parse_range
        import fitz
        n = mv._doc.doc.page_count
        txt, ok = QInputDialog.getText(self, tr("다른 쪽에도 놓기"),
                                       tr("쪽 범위(예: 1-3, 5) — 비우면 모든 쪽({n}쪽)").format(n=n))
        if not ok:
            return
        try:
            pages = sorted(set(parse_range(txt, n))) if txt.strip() else list(range(n))
        except Exception:
            pages = []
        if not pages:
            QMessageBox.information(self, tr("다른 쪽에도 놓기"), tr("쪽 범위를 읽지 못했습니다. 예: 1-3, 5"))
            return
        if len(pages) > 30 and QMessageBox.question(
                self, tr("다른 쪽에도 놓기"), tr("{n}쪽에 서명 자리를 놓습니다 — 확정하면 쪽마다 서명이 하나씩 들어가 시간이 걸리고 파일이 커집니다. 계속할까요?").format(n=len(pages))
        ) != QMessageBox.StandardButton.Yes:
            return
        ds = sign_drafts.drafts(cur)
        have = {(x["page"], tuple(round(v, 1) for v in x["rect"])) for x in ds}
        for p in pages:
            pr = mv._doc.doc[p].rect
            r = fitz.Rect(d["rect"])
            dx = max(0, pr.x0 - r.x0) - max(0, r.x1 - pr.x1)
            dy = max(0, pr.y0 - r.y0) - max(0, r.y1 - pr.y1)
            r = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy) & pr
            k = (p, tuple(round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1)))
            if k in have:
                continue
            have.add(k)
            ds.append({"id": sign_drafts.new_id(), "page": p, "rect": [r.x0, r.y0, r.x1, r.y1], "kind": d["kind"],
                       "image": d["image"], "field": "", "fp": d.get("fp", ""), "auto": bool(d.get("auto"))})
        sign_drafts.set_drafts(cur, ds)
        self._sign_drafts_sync(mv)

    # ---- 일괄 확정 — SOT §3.10 -------------------------------------------------
    def action_sign_confirm(self):
        from viewer import sign_drafts, sign_core, sign_store
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if not (cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None):
            QMessageBox.information(self, tr("서명 확정"), tr("서명할 PDF를 먼저 여세요."))
            return
        cur = str(cur)
        ds = sign_drafts.drafts(cur)
        if not ds:
            QMessageBox.information(self, tr("서명 확정"), tr("이 파일에 서명 자리가 없습니다. 도구 → 서명... 으로 자리를 먼저 놓으세요."))
            return
        doc = mv._doc.doc
        signs = [d for d in ds if d["kind"] == "sign"]
        images = [d for d in ds if d["kind"] == "image"]
        level = sign_core.doc_certify_level(doc)
        if images and level:
            QMessageBox.information(self, tr("서명 확정"), tr("작성자가 인증한 문서에는 그림을 넣을 수 없습니다(인증이 허용하지 않는 변경)."))
            return
        if level and any(not d["field"] for d in signs):
            QMessageBox.information(self, tr("서명 확정"), tr("작성자가 인증한 문서입니다 — 새 자리에는 서명할 수 없고 빈 서명 칸에만 서명할 수 있습니다."))
            return
        if not self._sign_preflight(cur):
            return
        if mv.current_file() and str(mv.current_file()) != cur:
            return
        others = sign_core.doc_is_signed(doc)
        # 261031-1: 자리를 놓을 때 연 열쇠가 없으면(앱을 다시 켰다 등) 여기서 한 번 확인 — 그림만 자리도(사용자 결정)
        if not self._sign_unlock():
            return
        if not signs:
            text = tr("그림 {n}개를 넣은 새 파일을 만듭니다(전자서명은 넣지 않습니다). 원본은 그대로입니다.").format(n=len(images))
            if others:
                text += "\n" + tr("이 문서의 기존 전자서명은 그림을 넣은 새 파일에서 '서명 후 변경됨' 이 됩니다.")
            if QMessageBox.question(self, tr("그림만 넣기"), text) != QMessageBox.StandardButton.Yes:
                self._sign_lock()
                return
            self._sign_confirm_do(cur, ds, None)
            self._sign_lock()
            return
        empties = {f.name: f for f in sign_core.empty_fields(doc)}
        for d in signs:
            if d["field"] and d["field"] not in empties:
                QMessageBox.warning(self, tr("서명 확정"), tr("빈 서명 칸을 찾지 못했습니다(이미 서명됐거나 지워졌습니다): {name}").format(name=d["field"]))
                return
        pages = sorted({d["page"] + 1 for d in ds})
        summary = tr("전자서명 {a}개 · 그림만 {b}개 (p.{pages})").format(
            a=len(signs), b=len(images), pages=", ".join(str(p) for p in pages[:12]) + ("…" if len(pages) > 12 else ""))
        for d in signs:
            f = empties.get(d["field"]) if d["field"] else None
            if f is not None:
                summary += "\n" + tr("서명 칸: {name} (p.{page})").format(name=f.name, page=f.page + 1)
                if f.signer_names:
                    summary += " · " + tr("서명할 사람: {names}").format(names=", ".join(f.signer_names))
                if f.lock:
                    summary += " · " + tr("서명하면 문서의 모든 칸이 잠깁니다")
        out = sign_drafts.out_of(cur) or sign_drafts.default_out(cur)
        first = signs[0]
        x0, y0, x1, y1 = first["rect"]
        from viewer.widgets.sign_dialogs import SignDialog
        dlg = SignDialog(self, file_name=Path(cur).name,
                         box_size=(x1 - x0, y1 - y0), page_count=doc.page_count, current_page=first["page"],
                         can_certify=not others, summary=summary, out_name=Path(out).name,
                         box_is_field=bool(first["field"]), ids=list(self._sign_creds()), cur_fp=self._sign_current_fp())
        try:
            while True:
                dlg.save_as = False
                if dlg.exec() != dlg.DialogCode.Accepted:
                    return
                self._sign_cur_fp = dlg.fp()
                if self._sign_confirm_do(cur, ds, dlg) != "retry":
                    return
        finally:
            dlg.stop_preview()
            dlg.deleteLater()
            self._sign_lock()                    # 확정·취소까지만 — 연 열쇠는 여기서 버린다(사용자 결정 261031-1, SOT §6.4)

    def _sign_confirm_do(self, cur: str, ds: list, dlg) -> str:
        """배경에서 바탕 → 그림만 → 전자서명 → 저장(별도 파일) → 기록 → 열기. 'ok' | 'retry' | 'fail'.
        열쇠는 서명을 시작할 때 연 것(`_sign_creds`, 261031-1) — 여기서 비밀번호를 묻지 않는다."""
        from viewer import sign_core, sign_drafts, sign_store
        mv = self.main_view
        doc = mv._doc.doc
        signs = [d for d in ds if d["kind"] == "sign"]
        images = [d for d in ds if d["kind"] == "image"]
        pfx, signer, fp, pw = b"", None, "", ""
        app = tsa = None
        reason = loc = ""
        certify = 0
        if signs:
            fp = dlg.fp()
            entry = sign_store.get_id(fp) or {}
            empties = {f.name: f for f in sign_core.empty_fields(doc)}
            for d in signs:
                f = empties.get(d["field"]) if d["field"] else None
                if f is not None and f.signer_fps and fp not in f.signer_fps:
                    QMessageBox.information(self, tr("서명"), tr("이 칸은 지정된 사람의 인증서로만 서명할 수 있습니다: {names}").format(
                        names=", ".join(f.signer_names) or "?"))
                    return "retry"
            if entry.get("kind") == "win":
                from viewer import sign_winstore
                try:
                    thumb, hwnd = entry.get("thumb", ""), int(self.winId())
                    signer = self._sign_bg(lambda: sign_winstore.make_signer(thumb, hwnd=hwnd), tr("인증서 준비 중"))
                except sign_winstore.StoreError as e:
                    QMessageBox.warning(self, tr("서명"), self._sign_store_msg(e))
                    return "fail"
            else:
                cred = self._sign_creds().get(fp)
                if not cred or cred[0] != "pfx":
                    QMessageBox.warning(self, tr("서명"), tr("이 디지털 ID 를 열지 않았습니다. 서명을 다시 시작하세요."))
                    return "fail"
                pfx, pw = cred[1], cred[2]
            certify = dlg.certify()
            if certify == 1 and len(signs) > 1:
                QMessageBox.information(self, tr("서명"), tr("'인증 — 변경 금지' 는 서명 하나에만 할 수 있습니다(뒤따르는 서명도 변경이 됩니다)."))
                return "retry"
            app = dlg.appearance()
            tsa = dlg.tsa_url() or None
            reason, loc = dlg.ed_reason.text(), dlg.ed_loc.text()
            e_ = sign_store.get_id(fp) or {}
            label = sign_core.signer_label(e_.get("name", ""), e_.get("email", ""))
            # 새 자리: 그림 상자 + 아래 글자 줄 = 서명 영역(§3.6), 쪽 안으로. PDF 사용자 공간으로
            targets = []
            for d in signs:
                if d["field"]:
                    continue
                page = doc[d["page"]]
                import fitz
                r = fitz.Rect(d["rect"])
                tw, th = sign_core.stamp_size(app, label, reason, r.width, r.height)
                tot = fitz.Rect(r.x0, r.y0, r.x0 + tw, r.y0 + th)
                over = tot.y1 - page.rect.y1
                if over > 0:
                    tot = fitz.Rect(tot.x0, tot.y0 - over, tot.x1, tot.y1 - over)
                targets.append((d["page"], sign_core.page_box_to_pdf(page, tot & page.rect)))
            locks = [d for d in signs if d["field"] and empties[d["field"]].lock]
            fields = [d["field"] for d in signs if d["field"] and d not in locks] + [d["field"] for d in locks]
        else:
            targets, fields = [], []
        doc_pw, remembered = self._sign_doc_password(cur, doc)
        img_items = [(d["page"], tuple(d["rect"]), self._sign_draft_image(d) or sign_store.id_image_path(self._sign_current_fp()))
                     for d in images]
        if any(not ip for _p, _r, ip in img_items):
            QMessageBox.information(self, tr("그림만 넣기"), tr("서명 그림이 없는 그림만 자리가 있습니다 — 자리 우클릭 '디지털 ID ▸ 디지털 ID 관리…' 에서 넣은 뒤 다시 확정하세요."))
            return "fail"
        tmps = []

        def _job():
            with open(cur, "rb") as fh:
                base = fh.read()
            src = cur
            if img_items:
                t = self._sign_tmp(cur)
                tmps.append(t)
                sign_core.insert_images(src, t, img_items, doc_password=doc_pw)
                src = t
            first = True
            if targets:
                t = self._sign_tmp(cur)
                tmps.append(t)
                sign_core.sign_pdf(src, t, pfx, pw, targets=targets, appearance=app, reason=reason, location=loc,
                                   doc_password=doc_pw, certify=certify, tsa=tsa, signer=signer)
                src = t
                first = False
            for name in fields:
                t = self._sign_tmp(cur)
                tmps.append(t)
                sign_core.sign_pdf(src, t, pfx, pw, appearance=app, reason=reason, location=loc,
                                   doc_password=doc_pw, certify=certify if first else 0, tsa=tsa, field=name,
                                   signer=signer)
                src = t
                first = False
            if src == cur:                       # 넣을 것이 없다(있을 수 없음) — 그래도 원본은 건드리지 않는다
                t = self._sign_tmp(cur)
                tmps.append(t)
                with open(t, "wb") as fh:
                    fh.write(base)
                src = t
            return src, len(base), _sha(base)

        n_all = len(targets) + len(fields) + (1 if img_items else 0)
        try:
            final_tmp, base_len, base_sha = self._sign_bg(
                _job, tr("서명 중") if n_all <= 1 else tr("서명 중 ({n}개)").format(n=len(targets) + len(fields) or len(img_items)))
        except sign_core.WrongPassword:
            for t in tmps:
                self._sign_unlink(t)
            QMessageBox.warning(self, tr("서명"), tr("비밀번호가 맞지 않습니다."))
            return "retry"
        except sign_core.SignError as e:
            for t in tmps:
                self._sign_unlink(t)
            QMessageBox.warning(self, tr("서명"), self._sign_error_msg(e))
            return "fail"
        except Exception as e:                   # noqa: BLE001
            for t in tmps:
                self._sign_unlink(t)
            from viewer import sign_winstore
            if isinstance(e, sign_winstore.StoreCancelled):
                self.status.showMessage(tr("Windows 가 물은 PIN·확인을 취소했습니다."), 6000)
                return "retry"
            if isinstance(e, sign_winstore.StoreError):
                QMessageBox.warning(self, tr("서명"), self._sign_store_msg(e))
                return "fail"
            QMessageBox.warning(self, tr("서명"), tr("서명하지 못했습니다: {e}").format(e=type(e).__name__))
            return "fail"
        for t in tmps:
            if t != final_tmp:
                self._sign_unlink(t)
        out = sign_drafts.out_of(cur) or sign_drafts.default_out(cur)
        final = self._sign_place_out(cur, final_tmp, out, bool(dlg is not None and dlg.save_as))
        if not final:
            return "fail"
        if doc_pw:
            self._sign_carry_password(final, doc_pw, remembered)
        # 기록 — 확정한 자리는 결과 파일로(서명 편집용), 원본에서는 지운다(SOT §3.10)
        try:
            sign_drafts.set_signed(final, cur, base_len, base_sha, ds)
            sign_drafts.clear(cur)
        except Exception:
            pass
        page0 = int(ds[0]["page"]) if ds else 0
        try:
            self.bookmark_tree.add_or_refresh_file(final, after=str(cur))
            self._open_saved_file(final, page0)
        except Exception:
            pass
        self._sign_drafts_sync()
        self.status.showMessage(tr("서명했습니다: {name}").format(name=Path(final).name) if signs
                                else tr("그림을 넣었습니다: {name}").format(name=Path(final).name), 6000)
        return "ok"

    def _sign_error_msg(self, e) -> str:
        return {"certified": tr("작성자가 서명 뒤 변경을 금지한 문서입니다 — 서명을 더할 수 없습니다."),
                "certified_new_field": tr("작성자가 인증한 문서입니다 — 새 서명 칸을 더하면 인증이 허용하지 않은 변경이 됩니다. 문서에 빈 서명 칸이 있으면 그 칸에만 서명할 수 있습니다."),
                "wrong_signer": tr("고른 디지털 ID 는 이 칸에 서명할 사람으로 지정된 인증서가 아닙니다."),
                "no_field": tr("빈 서명 칸을 찾지 못했습니다(이미 서명됐거나 지워졌습니다): {name}").format(name=e.detail),
                "certify_not_first": tr("이미 서명이 있는 문서에는 인증 서명을 할 수 없습니다(인증은 첫 서명만)."),
                "certify_one_page": tr("'인증 — 변경 금지' 는 서명 하나에만 할 수 있습니다(뒤따르는 서명도 변경이 됩니다)."),
                "tsa_failed": tr("타임스탬프 기관에서 시각을 받지 못해 서명하지 않았습니다. 주소·인터넷을 확인하거나 타임스탬프를 끄고 서명하세요.\n({d})").format(d=e.detail[:120]),
                "need_doc_password": tr("암호 문서의 암호를 모릅니다. 권한 암호로 연 뒤 서명하세요."),
                "unreadable": tr("이 PDF 는 그대로 서명할 수 없습니다(파일 구조 손상). 먼저 PolyPDF 로 저장(다른 이름으로 저장)해 정리한 뒤 그 파일에 서명하세요."),
                "no_font": tr("겉모양 글자에 쓸 한글 글꼴이 없습니다. 서명 그림을 고르거나 겉모양 글자를 끄세요.")
                }.get(e.reason, tr("서명하지 못했습니다: {e}").format(e=e.detail or e.reason))

    def _sign_place_out(self, cur: str, tmp: str, out: str, save_as: bool) -> str:
        """결과를 별도 파일로(SOT §3.4). 있으면 [바꾸기]/[다른 이름으로…]/취소. 원본 경로는 받지 않는다."""
        import shutil
        from PyQt6.QtWidgets import QFileDialog

        def _same(a, b):
            return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

        def _ask_name(default):
            got, _ = QFileDialog.getSaveFileName(self, tr("다른 이름으로 저장"), default, tr("PDF 파일 (*.pdf)"))
            if got and not got.lower().endswith(".pdf"):
                got += ".pdf"
            return got
        if save_as:
            out = _ask_name(out)
        while True:
            if not out:
                self._sign_unlink(tmp)
                return ""
            if _same(out, cur):
                QMessageBox.information(self, tr("서명 확정"), tr("원본 파일에는 서명을 저장하지 않습니다 — 다른 이름을 고르세요."))
                out = _ask_name(out)
                continue
            if os.path.exists(out):
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(tr("서명 확정"))
                box.setText(tr("'{name}' 이(가) 이미 있습니다 — 바꿀까요?").format(name=Path(out).name))
                b_rep = box.addButton(tr("바꾸기"), QMessageBox.ButtonRole.AcceptRole)
                b_as = box.addButton(tr("다른 이름으로…"), QMessageBox.ButtonRole.ActionRole)
                box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(b_rep)
                box.exec()
                c = box.clickedButton()
                if c is b_as:
                    out = _ask_name(out)
                    continue
                if c is not b_rep:
                    self._sign_unlink(tmp)
                    return ""
                self._sign_saving = True         # 사용자가 방금 [바꾸기] 로 답했다 — §4 가드는 건너뛴다
                try:
                    return str(self._finalize_save(out, tmp, shift=False))
                except Exception as e:           # noqa: BLE001
                    self._sign_unlink(tmp)
                    from viewer.file_overwrite import SaveCancelled
                    if isinstance(e, SaveCancelled):
                        self.status.showMessage(str(e), 5000)
                    else:
                        QMessageBox.warning(self, tr("서명"), tr("저장하지 못했습니다: {e}").format(e=e))
                    return ""
                finally:
                    self._sign_saving = False
            err = self._file_op_bg(lambda: shutil.move(tmp, out),       # 다른 드라이브여도(261011-1)
                                   tr("저장 중: {name}").format(name=Path(out).name))
            if err is not None:
                self._sign_unlink(tmp)
                QMessageBox.warning(self, tr("서명"), tr("저장하지 못했습니다: {e}").format(e=err))
                return ""
            return out

    # ---- 서명 편집 — SOT §3.10 -------------------------------------------------
    def _sign_editable(self, path: str, rep=None) -> bool:
        """검증 띠의 [서명 편집] 을 보일지 — 내 디지털 ID 서명이 있으면."""
        from viewer import sign_store
        try:
            mine = {str(e.get("fp", "")).lower() for e in sign_store.load()["ids"]}
            return bool(rep is not None and any(str(s.fp or "").lower() in mine for s in rep.sigs))
        except Exception:
            return False

    def action_sign_edit(self):
        from viewer import sign_core, sign_drafts, sign_store
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if not (cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None):
            QMessageBox.information(self, tr("서명 편집"), tr("서명된 PDF를 먼저 여세요."))
            return
        cur = str(cur)
        if not sign_core.doc_is_signed(mv._doc.doc):
            QMessageBox.information(self, tr("서명 편집"), tr("이 문서에는 전자서명이 없습니다."))
            return
        doc_pw, remembered = self._sign_doc_password(cur, mv._doc.doc)
        mine = {str(e.get("fp", "")).lower() for e in sign_store.load()["ids"]}
        rec = sign_drafts.signed(cur)

        def _plan():
            with open(cur, "rb") as fh:
                data = fh.read()
            fields = sign_core.signed_fields(cur, doc_pw)
            base_len, drafts, from_rec = 0, [], False
            if rec and 0 < rec["base_len"] < len(data) and _sha(data[:rec["base_len"]]) == rec["base_sha"]:
                tail = [f for f in fields if f.end > rec["base_len"]]
                if all(f.fp.lower() in mine for f in tail):
                    base_len, drafts, from_rec = rec["base_len"], rec["drafts"], True
                else:
                    return {"err": "others"}
            if not from_rec:
                k = len(fields)
                while k > 0 and fields[k - 1].fp.lower() in mine:
                    k -= 1
                if k == len(fields):
                    return {"err": "none" if not any(f.fp.lower() in mine for f in fields) else "others"}
                base_len = fields[k].start
                # 서명 겉모양 영역 = 그림 상자 + 아래 글자 줄 — 지금 겉모양으로 글자 줄을 빼 그림 상자로 되돌린다
                app, label, reason = self._sign_view_appearance()
                drafts = []
                for f in fields[k:]:
                    x0, y0, x1, y1 = f.rect
                    _tw, th = sign_core.stamp_size(app, label, reason, x1 - x0, 100.0)
                    y1 = max(y0 + 8.0, y1 - (th - 100.0))
                    drafts.append({"id": sign_drafts.new_id(), "page": f.page, "rect": [x0, y0, x1, y1], "kind": "sign",
                                   "image": "", "field": ""})
            return {"data": data[:base_len], "base_len": base_len, "drafts": drafts, "from_rec": from_rec}
        try:
            plan = self._sign_bg(_plan, tr("서명 확인 중"))
        except Exception as e:                   # noqa: BLE001
            QMessageBox.warning(self, tr("서명 편집"), tr("서명을 읽지 못했습니다: {e}").format(e=type(e).__name__))
            return
        if plan.get("err") == "none":
            QMessageBox.information(self, tr("서명 편집"), tr("고칠 수 있는 내 서명이 없습니다(내 디지털 ID 로 한 서명만 고칠 수 있습니다)."))
            return
        if plan.get("err") == "others":
            QMessageBox.information(self, tr("서명 편집"), tr("다른 사람의 서명이 뒤에 있어 고칠 수 없습니다."))
            return
        text = tr("서명을 자리로 되돌려 옮기기·크기·지우기를 한 뒤 다시 확정합니다. 다시 확정할 때까지 이 파일은 그대로입니다.")
        if not plan["from_rec"]:
            text += "\n" + tr("이 파일의 서명 기록이 없어 서명 자리만 되살립니다 — 확정 때 넣은 '그림만' 은 바탕에 남습니다.")
        if QMessageBox.question(self, tr("서명 편집"), text) != QMessageBox.StandardButton.Yes:
            return
        # 바탕을 열 파일 — 기록의 원본이 그 바이트 그대로면 원본, 아니면 새 파일 `<이름>_서명전.pdf`
        target = ""
        src = (rec or {}).get("src", "") if plan["from_rec"] else ""
        if src and os.path.exists(src):
            try:
                same = self._sign_bg(lambda: open(src, "rb").read() == plan["data"], tr("서명 확인 중"))
            except Exception:
                same = False
            if same:
                target = src
        if not target:
            p = Path(cur)
            stem = p.stem
            suf = tr("_서명")
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
            target = str(p.with_name(tr("{stem}_서명전.pdf").format(stem=stem)))
            k = 2
            while os.path.exists(target):
                target = str(p.with_name(tr("{stem}_서명전 ({n}).pdf").format(stem=stem, n=k)))
                k += 1

            def _write(t=target, b=plan["data"]):
                with open(t, "wb") as fh:
                    fh.write(b)
            err = self._file_op_bg(_write, tr("저장 중: {name}").format(name=Path(target).name))
            if err is not None:
                QMessageBox.warning(self, tr("서명 편집"), tr("저장하지 못했습니다: {e}").format(e=err))
                return
            if doc_pw:
                self._sign_carry_password(target, doc_pw, remembered)
        sign_drafts.set_drafts(target, plan["drafts"], out=cur)
        page0 = int(plan["drafts"][0]["page"]) if plan["drafts"] else 0
        try:
            self.bookmark_tree.add_or_refresh_file(target, after=cur)
            self._open_saved_file(target, page0)
        except Exception:
            pass
        self._sign_drafts_sync()
        self.status.showMessage(tr("서명 자리를 되살렸습니다 — 고친 뒤 [서명 확정…] 을 누르면 '{name}' 을 바꿉니다.").format(name=Path(cur).name), 10000)
