# -*- coding: utf-8 -*-
"""전자서명 흐름 — `MainWindow` 믹스인 (보안 SOT §3·§4·§5·§6, 마스터 §11.11 믹스인 표준).

  도구 '서명' → 사전 점검(§3.5) → 디지털 ID·서명 그림 확인 → 본문에서 자리 끌기(§3.3) → 서명 자리(초안, §3.10)
  → [서명 확정…] 창 → 비밀번호(1순위 Windows Hello · 2순위 직접 입력/붙여넣기, §6)
  → 배경에서 증분 서명 → 별도 파일 `<이름>_서명.pdf`(§3.4) → 열면 검증 띠(§5). 자리·확정·편집은 `sign_draft_controller`.

서명된 PDF 를 PolyPDF 가 다시 쓰면(전체 저장) 서명이 깨진다 — `_sign_guard` 를 `_finalize_save` 가
진입에서 부른다(§4, 가드는 한 곳).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr
from viewer.sign_draft_controller import SignDraftMixin

SIGN_MIN_SIDE_PT = 12                       # 이보다 작게 끌면 클릭으로 본다


def _sc_empty(mv):
    from viewer import sign_core
    return sign_core.empty_fields(mv._doc.doc)


class SignMixin(SignDraftMixin):
    # ---- 배경 실행 -----------------------------------------------------------
    def _sign_bg(self, fn, title: str):
        """fn() 을 배경 스레드 + 진행창에서(`_run_merge_job`, 취소 없음). 결과를 돌려주거나 예외를 그대로 낸다."""
        out = {}

        def _job(progress):
            progress(0, 1, title)
            try:
                out["r"] = fn()
            except BaseException as e:            # noqa: BLE001 — 화면 쪽에서 종류별로 다룬다
                out["e"] = e
            progress(1, 1, tr("완료"))
        self._run_merge_job(_job, title, cancellable=False)
        if "e" in out:
            raise out["e"]
        return out.get("r")

    def _sign_hello_ready(self) -> bool:
        """Windows Hello 를 쓸 수 있나 — 처음 한 번 배경에서 재고 기억한다(SOT §6.2)."""
        from viewer import sign_hello
        c = sign_hello.cached_available()
        if c is not None:
            return bool(c)
        try:
            return bool(self._sign_bg(sign_hello.available, tr("Windows Hello 확인 중")))
        except Exception:
            return False

    # ---- 메뉴 동작 -----------------------------------------------------------
    def action_digital_ids(self):
        self._sign_manage_ids()

    def _sign_manage_ids(self, fp: str = "") -> str:
        """디지털 ID 관리 창 — `fp` 를 골라 연다. 서명 그림·폭·내용은 **여기서만** 고친다(261031-7 사용자 지시).
        닫으면 지금 서명에 반영한다: '내용 고치기'(새로 발급)로 바뀐 지문은 새 지문으로 잇고, 클릭 자리는 새 실제 크기로,
        자리 미리보기는 다시 그린다. 돌려주는 값 = `fp` 의 지금 지문(바뀌었으면 새 것)."""
        from viewer import sign_drafts
        from viewer.widgets.sign_dialogs import DigitalIdDialog
        dlg = DigitalIdDialog(self, runner=self._sign_bg, hello_ok=self._sign_hello_ready(), select_fp=fp)
        try:
            dlg.exec()
            rep = dict(dlg.replaced)
        finally:
            dlg.deleteLater()        # 안의 비밀번호 칸까지 — 창마다 남겨 두지 않는다(SOT §6.4, 261011-1)

        def _now(f):
            while f in rep:
                f = rep[f]
            return f
        if getattr(self, "_sign_cur_fp", "") in rep:
            self._sign_cur_fp = _now(self._sign_cur_fp)
        self._sign_creds()                               # 지워지거나 바뀐 ID 의 열쇠는 버린다
        for mv in (getattr(self, "_mv", None) or [getattr(self, "main_view", None)]):
            cur = mv.current_file() if mv is not None else None
            if not cur or not sign_drafts.drafts(cur):
                continue
            ds = sign_drafts.drafts(cur)
            for d in ds:
                if d.get("fp") in rep:
                    d["fp"] = _now(d["fp"])
            sign_drafts.set_drafts(cur, ds)
            if hasattr(self, "_sign_resize_auto"):
                for f in {self._sign_view_fp()} | {d.get("fp") for d in ds if d["kind"] == "image" and d.get("fp")}:
                    self._sign_resize_auto(mv, str(cur), f)
        if hasattr(self, "_sign_pix_cache"):
            self._sign_pix_cache().clear()
        if hasattr(self, "_sign_drafts_sync"):
            self._sign_drafts_sync()
        return _now(fp)

    # ---- 서명 시작 확인 — 한 번 열고 확정·취소까지 (SOT §3.3·§6.4, 261031-1) -----------
    def _sign_lock(self) -> None:
        """연 디지털 ID 열쇠를 버린다 — 서명 확정·확정 창 취소·자리 모두 지우기 때(사용자 결정 261031-1 '확정·취소까지만')."""
        self._sign_unlocked = {}
        self._sign_cur_fp = ""

    def _sign_creds(self) -> dict:
        c = getattr(self, "_sign_unlocked", None) or {}
        if c:
            # 관리 창에서 지우거나 '내용 고치기'(새로 발급)로 바뀐 ID 의 열쇠는 버린다(보안 SOT §3.2, 261031-6)
            from viewer import sign_store
            have = {e.get("fp") for e in sign_store.load()["ids"]}
            gone = [fp for fp in c if fp not in have]
            for fp in gone:
                c.pop(fp, None)
        return c

    def _sign_current_fp(self) -> str:
        """지금 쓰는 ID — 연 것 중 고른 것, 없으면 기본 ID(열렸으면), 아니면 연 것 중 첫째(목록 차례)."""
        creds = self._sign_creds()
        if not creds:
            return ""
        cur = getattr(self, "_sign_cur_fp", "")
        if cur in creds:
            return cur
        from viewer import sign_store
        d = sign_store.load()
        if d.get("default_id") in creds:
            return d["default_id"]
        return next((e["fp"] for e in d["ids"] if e.get("fp") in creds), next(iter(creds)))

    def _sign_unlock(self, more: bool = False) -> bool:
        """서명을 시작할 때 한 번 — 비밀번호 또는 Windows Hello 로 쓸 수 있는 디지털 ID 를 연다.
        이미 열었으면(그리고 `more` 가 아니면) 묻지 않는다. 연 ID 가 없으면 다시 입력하거나 디지털 ID 를 만들게 한다."""
        from viewer import sign_core, sign_store
        if self._sign_creds() and not more:
            return True
        d = sign_store.load()
        if not d["ids"]:
            if QMessageBox.question(self, tr("서명"), tr("디지털 ID 가 없습니다. 지금 만들까요?")) != QMessageBox.StandardButton.Yes:
                return False
            self.action_digital_ids()
            d = sign_store.load()
            if not d["ids"]:
                return False
        creds = dict(self._sign_creds())
        # Windows 저장소 ID 는 PolyPDF 가 비밀번호를 묻지 않는다 — 서명할 때 Windows 가 PIN 을 묻는다(SOT §3.9)
        for e in d["ids"]:
            if e.get("kind") == "win":
                creds.setdefault(e["fp"], ("win", e.get("thumb", ""), None))
        pfx_ids = [e for e in d["ids"] if e.get("kind") != "win" and e["fp"] not in creds]
        if not pfx_ids:
            self._sign_unlocked = creds
            return bool(creds)
        hello_ok = self._sign_hello_ready()
        from viewer import sign_hello
        hello_ids = [e for e in pfx_ids if e.get("hello") and sign_hello.has(e["fp"])] if hello_ok else []
        hello_e = next((e for e in hello_ids if e["fp"] == d.get("default_id")), hello_ids[0] if hello_ids else None)
        from viewer.widgets.sign_dialogs import SignUnlockDialog
        while True:
            dlg = SignUnlockDialog(self, hello_ok=hello_ok, hello_name=(hello_e or {}).get("name", ""), n_ids=len(d["ids"]))
            try:
                if dlg.exec() != dlg.DialogCode.Accepted:
                    return False
                mode, pw = dlg.mode, dlg.password()
            finally:
                dlg.ed_pw.clear()                # 칸에 남기지 않는다(SOT §6.4)
                dlg.deleteLater()
            got = {}
            if mode == "hello" and hello_e is not None:
                fp = hello_e["fp"]
                try:
                    hpw = self._sign_bg(lambda: sign_hello.recall(fp), tr("Windows Hello 확인"))
                    pfx = sign_store.read_pfx(fp)
                    self._sign_bg(lambda: sign_core.load_pfx(pfx, hpw), tr("디지털 ID 확인 중"))
                    got[fp] = ("pfx", pfx, hpw)
                except sign_hello.HelloCancelled:
                    self.status.showMessage(tr("Windows Hello 를 취소했습니다 — 비밀번호를 넣을 수 있습니다."), 6000)
                    continue
                except Exception:
                    QMessageBox.information(self, tr("서명"), tr("Windows Hello 로 보관한 비밀번호를 꺼내지 못했습니다. 비밀번호를 넣으세요 — 맞으면 다시 보관할지 묻습니다."))
                    self._sign_rehello = fp
                    continue
            else:
                def _try(ids=tuple(e["fp"] for e in pfx_ids), pw_=pw):
                    ok = {}
                    for fp_ in ids:
                        try:
                            pfx_ = sign_store.read_pfx(fp_)
                            sign_core.load_pfx(pfx_, pw_)
                            ok[fp_] = ("pfx", pfx_, pw_)
                        except Exception:
                            pass
                    return ok
                got = self._sign_bg(_try, tr("디지털 ID 확인 중"))
            if got:
                creds.update(got)
                self._sign_unlocked = creds
                rh = getattr(self, "_sign_rehello", None)
                if rh and rh in got and mode != "hello":            # SOT §6.1 '꺼내지 못할 때'
                    self._sign_rehello = None
                    if QMessageBox.question(self, tr("Windows Hello"), tr("이 비밀번호를 Windows Hello 로 다시 보관할까요?")) == QMessageBox.StandardButton.Yes:
                        try:
                            self._sign_bg(lambda: sign_hello.store(rh, got[rh][2]), tr("Windows Hello 확인"))
                            sign_store.set_id_flag(rh, hello=True)
                        except Exception:
                            pass
                if more:
                    self._sign_cur_fp = next(iter(got))
                return True
            # 쓸 수 있는 ID 가 없다 — 다시 입력하거나 디지털 ID 를 만든다(261031-1, 사용자 지시)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("서명"))
            box.setText(tr("이 비밀번호로 열리는 디지털 ID 가 없습니다. 비밀번호를 다시 넣거나 디지털 ID 를 만드세요."))
            b_again = box.addButton(tr("다시 입력"), QMessageBox.ButtonRole.AcceptRole)
            b_make = box.addButton(tr("디지털 ID 관리…"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_again)
            box.exec()
            c = box.clickedButton()
            if c is b_make:
                self.action_digital_ids()
                d = sign_store.load()
                pfx_ids = [e for e in d["ids"] if e.get("kind") != "win" and e["fp"] not in creds]
                if not pfx_ids:
                    return False
            elif c is not b_again:
                return False

    def action_sign_pdf(self, at_scene=None, kind: str = "sign"):
        """도구 '서명' — 사전 점검 뒤 본문에서 서명 자리를 끌게 한다(SOT §3·§3.3·§3.10).
        `at_scene`(scene 점, 본문 우클릭 '여기에 서명…')이면 끌지 않고 그 자리에 기본 크기로 자리를 놓는다(S6).
        `kind="image"` 면 그림만 자리(§3.11) — 같은 확인 뒤 그 ID 의 서명 그림(사용자 결정 261031-1).
        자리를 놓기 전에 한 번 비밀번호·Windows Hello 로 디지털 ID 를 연다(`_sign_unlock`, 261031-1)."""
        if isinstance(at_scene, bool):           # 261031-1: 메뉴 `triggered(checked)` 가 그대로 들어온 것 — 점이 아니다
            at_scene = None
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if not (cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None):
            QMessageBox.information(self, tr("서명"), tr("서명할 PDF를 먼저 여세요."))
            return
        if not self._sign_preflight(str(cur)):
            return
        from viewer import sign_store
        if not self._sign_unlock():
            return
        fp = self._sign_current_fp()
        self._sign_cur_fp = fp
        if not sign_store.id_image_path(fp):
            name = (sign_store.get_id(fp) or {}).get("name", "")
            # 서명 그림은 디지털 ID 관리 창에서만 넣고 바꾼다(261031-7 사용자 지시)
            if kind == "image":
                if QMessageBox.question(self, tr("그림만 넣기"), tr("디지털 ID '{name}' 에 서명 그림이 없습니다. 디지털 ID 관리에서 넣을까요?").format(name=name)
                                        ) != QMessageBox.StandardButton.Yes:
                    return
                fp = self._sign_manage_ids(fp)
                if not sign_store.id_image_path(fp):
                    return
            elif bool((sign_store.load().get("appearance") or {}).get("show_image", True)):
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(tr("서명"))
                box.setText(tr("디지털 ID '{name}' 에 서명 그림이 없습니다. 디지털 ID 관리에서 종이에 한 서명을 찍은 사진으로 넣을까요?").format(name=name))
                b_make = box.addButton(tr("디지털 ID 관리…"), QMessageBox.ButtonRole.AcceptRole)
                b_skip = box.addButton(tr("그림 없이"), QMessageBox.ButtonRole.ActionRole)
                box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
                box.exec()
                c = box.clickedButton()
                if c is b_make:
                    fp = self._sign_manage_ids(fp)
                elif c is not b_skip:
                    return
            if not self._sign_creds():               # 관리 창에서 그 ID 를 새로 발급했다 — 새 ID 를 다시 연다
                if not self._sign_unlock():
                    return
                self._sign_cur_fp = self._sign_current_fp()
        # 3단계(SOT §3.7): 빈 서명 칸이 있으면 먼저 묻는다 — 끌기·우클릭은 _on_sign_region 이 칸 안인지 본다
        from viewer import sign_core as _sc
        empties = _sc.empty_fields(mv._doc.doc)
        if kind == "sign" and at_scene is None and empties:
            choice = self._sign_choose_field(empties, _sc.doc_certify_level(mv._doc.doc))
            if choice is None:
                return
            if choice != "new":
                self._sign_fill_field(str(cur), choice, mv)
                return
        self._sign_tools_off(mv)                 # 글쓰기 도구 등이 본문 누르기를 먼저 가져가지 않게(SOT §3.3, 261012-1)
        self._sign_pending = str(cur)
        self._sign_pending_mode = kind
        if at_scene is not None:
            from PyQt6.QtCore import QRectF
            self._on_sign_region(QRectF(at_scene, at_scene), view=mv)     # 크기 0 = 클릭 → 기본 크기(_sign_box_fit)
            return
        mv.view.arm_block_select(True, purpose="sign")
        self.status.showMessage(tr("서명할 자리를 본문에서 끌어 정하세요(클릭만 하면 기본 크기).") if kind == "sign"
                                else tr("그림을 넣을 자리를 본문에서 끌어 정하세요(클릭만 하면 기본 크기)."), 8000)

    def action_sign_image_only(self):
        """도구 '그림만 넣기' — 전자서명 없이 등록된 서명 그림만(SOT §3.11)."""
        self.action_sign_pdf(kind="image")

    def _sign_preflight(self, cur: str) -> bool:
        """SOT §3.5 — 저장 안 한 편집 · PolyPDF 꾸밈 · 권한 · 보기 상태."""
        # 261011-2(§3.5): 저장 안 한 편집(쪽·크롭·회전·책갈피·꾸밈)이나 PDF 에 아직 안 들어간 꾸밈·사진·하이퍼링크·태그는
        #   서명에 들어가지 않는다 — [저장하고 서명](기본) / [그대로 서명] / 취소
        dirty = False
        try:
            dirty = bool(self._page_edits_dirty() or getattr(self, "_edit_dirty", False)
                         or getattr(self.bookmark_tree, "_dirty", False))
        except Exception:
            pass
        side = False
        try:
            side = bool(self._mirror_needed(cur))
        except Exception:
            pass
        if dirty or side:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("서명"))
            box.setText(tr("저장하지 않은 편집이나 PDF 에 아직 들어가지 않은 꾸밈·사진·하이퍼링크가 있습니다. 서명은 디스크에 있는 판에 하므로 그대로면 서명에 들어가지 않습니다."))
            box.setInformativeText(tr("저장하면 다른 뷰어에서도 보이게 PDF 에 들어간 뒤 그 판에 서명합니다."))
            b_save = box.addButton(tr("저장하고 서명"), QMessageBox.ButtonRole.AcceptRole)
            b_go = box.addButton(tr("그대로 서명"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_save)
            box.exec()
            c = box.clickedButton()
            if c is b_save:
                try:
                    self.bookmark_tree._op_save(cur)
                except Exception:
                    pass
                try:
                    still = bool(self._page_edits_dirty() or self._mirror_needed(cur))
                except Exception:
                    still = False
                if still:
                    self.status.showMessage(tr("저장하지 못해 서명을 멈췄습니다."), 6000)
                    return False
            elif c is not b_go:
                return False
        # 권한 — 양식·서명/주석 권한이 없으면 서명할 수 없다(§7.4)
        try:
            import fitz
            perm = int(getattr(self.main_view._doc.doc, "permissions", -1))
            if perm != -1 and not (perm & (fitz.PDF_PERM_FORM | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_MODIFY)):
                QMessageBox.information(self, tr("서명"), tr("이 문서는 서명 권한이 없습니다. 권한 암호로 연 뒤 서명하세요(책갈피창 우클릭 → 암호 입력)."))
                return False
        except Exception:
            pass
        return True

    # ---- 자리 → 서명 ---------------------------------------------------------
    def _on_sign_region(self, scene_rect, view=None):
        cur = getattr(self, "_sign_pending", None)
        mode = getattr(self, "_sign_pending_mode", "sign")
        self._sign_pending = None
        self._sign_pending_mode = "sign"
        mv = view or self.main_view
        if not cur or mv is None or str(mv.current_file() or "") != cur:
            return
        import fitz
        if mv.is_two_page_mode():
            QMessageBox.information(self, tr("서명"), tr("2쪽 보기에서는 자리를 정할 수 없습니다. 1쪽 보기로 바꾼 뒤 다시 서명하세요."))
            return
        pidx = int(mv.current_page())
        # 회전한 쪽에도 서명한다 — 겉모양을 쪽 회전만큼 반대로 돌려 넣는다(SOT §3.3, 261011-2)
        page = mv._doc.doc[pidx]
        z = mv._zoom or 1.0
        r = fitz.Rect(scene_rect.left() / z, scene_rect.top() / z, scene_rect.right() / z, scene_rect.bottom() / z)
        from viewer import sign_core as _sc
        if mode == "sigfield":
            self._sigfield_make(cur, pidx, self._sign_box_fit(page, r), mv)
            return
        # 끌기·우클릭의 가운데가 빈 서명 칸 안이면 그 칸을 채운다(SOT §3.7)
        c_ = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) * page.derotation_matrix   # 칸 자리는 회전 전 좌표
        hit = _sc.field_at(_sc.empty_fields(mv._doc.doc), pidx, c_.x, c_.y) if mode == "sign" else None
        if hit is not None:
            self._sign_fill_field(cur, hit, mv)
            return
        if mode == "sign" and _sc.doc_certify_level(mv._doc.doc):
            QMessageBox.information(self, tr("서명"), tr("작성자가 인증한 문서입니다 — 새 자리에는 서명할 수 없고 빈 서명 칸에만 서명할 수 있습니다."))
            return
        auto = self._sign_is_click(r)              # 클릭 = 실제 크기를 따르는 자리(ID·그림을 바꾸면 다시 맞춘다, 261031-6)
        r = self._sign_box_fit(page, r)
        self._sign_add_draft(mv, cur, pidx, r, kind="image" if mode == "image" else "sign", auto=auto)

    # ---- 빈 서명 칸 — SOT §3.7 -----------------------------------------------
    def _sign_choose_field(self, empties, certified: int):
        """빈 칸이 있을 때 [빈 칸에 서명] / [새 자리 끌기] / 취소. 반환: EmptyField | "new" | None."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("서명"))
        box.setText(tr("이 문서에 빈 서명 칸이 {n}개 있습니다.").format(n=len(empties)))
        if certified:
            box.setInformativeText(tr("인증된 문서라 새 자리에는 서명할 수 없고 빈 칸에만 서명할 수 있습니다."))
        b_fill = box.addButton(tr("빈 칸에 서명"), QMessageBox.ButtonRole.AcceptRole)
        b_new = None if certified else box.addButton(tr("새 자리 끌기"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_fill)
        box.exec()
        c = box.clickedButton()
        if b_new is not None and c is b_new:
            return "new"
        if c is not b_fill:
            return None
        if len(empties) == 1:
            return empties[0]
        from PyQt6.QtWidgets import QInputDialog
        labels = [tr("{name} — p.{page}").format(name=f.name, page=f.page + 1) for f in empties]
        got, ok = QInputDialog.getItem(self, tr("서명"), tr("서명할 칸"), labels, 0, False)
        if not ok:
            return None
        return empties[labels.index(got)]

    def _sign_fill_field(self, cur: str, field, mv):
        """빈 칸 하나를 채운다 — 그 쪽으로 가서 칸 크기 그대로 서명 자리를 놓는다(SOT §3.7·§3.10)."""
        import fitz
        if mv.is_two_page_mode():
            QMessageBox.information(self, tr("서명"), tr("2쪽 보기에서는 자리를 정할 수 없습니다. 1쪽 보기로 바꾼 뒤 다시 서명하세요."))
            return
        page = mv._doc.doc[field.page]
        if field.lock:
            others = [f for f in _sc_empty(mv) if f.name != field.name]
            if others and QMessageBox.question(
                    self, tr("서명"), tr("이 칸에 서명하면 문서의 모든 칸이 잠겨 남은 빈 서명 칸 {n}개에 더 서명할 수 없습니다. 계속할까요?").format(n=len(others))
            ) != QMessageBox.StandardButton.Yes:
                return
        if int(mv.current_page()) != field.page:
            try:
                mv.go_to_page(field.page)
            except Exception:
                pass
        from viewer import sign_drafts
        if any(d["field"] == field.name for d in sign_drafts.drafts(cur)):
            self.status.showMessage(tr("이 빈 서명 칸에는 이미 서명 자리가 있습니다: {name}").format(name=field.name), 6000)
            return
        # 칸 자리는 회전 전 좌표 — 서명 자리는 보이는 쪽 좌표로 적는다(SOT §3.10)
        r = fitz.Rect(*field.rect)
        if int(page.rotation) % 360:
            r = r * page.rotation_matrix
            r.normalize()
        self._sign_add_draft(mv, cur, field.page, r, kind="sign", field=field.name)

    def action_sign_field(self):
        """도구 '빈 서명 칸 만들기' — 사전 점검 뒤 본문에서 칸 자리를 끈다(SOT §3.7)."""
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if not (cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None):
            QMessageBox.information(self, tr("빈 서명 칸"), tr("서명 칸을 만들 PDF를 먼저 여세요."))
            return
        from viewer import sign_core as _sc
        if _sc.doc_certify_level(mv._doc.doc):
            QMessageBox.information(self, tr("빈 서명 칸"), tr("작성자가 인증한 문서입니다 — 서명 칸을 더하면 인증이 허용하지 않은 변경이 됩니다."))
            return
        if not self._sign_preflight(str(cur)):
            return
        self._sign_tools_off(mv)                 # SOT §3.3 — 그리기 도구가 끌기를 가져가지 않게
        self._sign_pending = str(cur)
        self._sign_pending_mode = "sigfield"
        mv.view.arm_block_select(True, purpose="sign")
        self.status.showMessage(tr("빈 서명 칸 자리를 본문에서 끌어 정하세요(클릭만 하면 기본 크기)."), 8000)

    def _sigfield_make(self, cur: str, pidx: int, r, mv):
        from viewer import sign_core
        from viewer.widgets import sign_dialogs
        doc = mv._doc.doc
        used = {f.name for f in sign_core.empty_fields(doc)}
        try:
            for page in doc:
                for w in page.widgets() or []:
                    used.add(str(w.field_name or ""))
        except Exception:
            pass
        k = 1
        while f"Signature{k}" in used:
            k += 1
        fdlg = sign_dialogs.SigFieldDialog(self, default_name=f"Signature{k}", used=used)
        if fdlg.exec() != fdlg.DialogCode.Accepted:
            return
        name, lock, certs = fdlg.name(), fdlg.chk_lock.isChecked(), ([fdlg.cert_der] if fdlg.cert_der else [])
        box = sign_core.page_box_to_pdf(doc[pidx], r)
        doc_pw, remembered = self._sign_doc_password(cur, doc)
        tmp = self._sign_tmp(cur)
        try:
            got = self._sign_bg(lambda: sign_core.add_empty_field(cur, tmp, page_index=pidx, box_pdf=box,
                                                                  name=name, doc_password=doc_pw,
                                                                  lock=lock, signer_certs=certs),
                                tr("빈 서명 칸 만드는 중"))
        except sign_core.SignError as e:
            self._sign_unlink(tmp)
            msg = {"field_exists": tr("같은 이름의 서명 칸이 이미 있습니다: {name}").format(name=e.detail),
                   "bad_cert": tr("인증서 파일을 읽지 못했습니다."),
                   "certified": tr("작성자가 서명 뒤 변경을 금지한 문서입니다 — 서명을 더할 수 없습니다."),
                   "certified_new_field": tr("작성자가 인증한 문서입니다 — 서명 칸을 더하면 인증이 허용하지 않은 변경이 됩니다."),
                   "need_doc_password": tr("암호 문서의 암호를 모릅니다. 권한 암호로 연 뒤 서명하세요."),
                   "unreadable": tr("이 PDF 는 그대로 서명할 수 없습니다(파일 구조 손상). 먼저 PolyPDF 로 저장(다른 이름으로 저장)해 정리한 뒤 그 파일에 서명하세요.")
                   }.get(e.reason, tr("서명 칸을 만들지 못했습니다: {e}").format(e=e.detail or e.reason))
            QMessageBox.warning(self, tr("빈 서명 칸"), msg)
            return
        except Exception as e:                   # noqa: BLE001
            self._sign_unlink(tmp)
            QMessageBox.warning(self, tr("빈 서명 칸"), tr("서명 칸을 만들지 못했습니다: {e}").format(e=type(e).__name__))
            return
        final = self._sigfield_place(cur, tmp)
        if not final:
            return
        if doc_pw:
            self._sign_carry_password(final, doc_pw, remembered)
        try:
            self.bookmark_tree.add_or_refresh_file(final, after=str(cur))
            self._open_saved_file(final, pidx)
        except Exception:
            pass
        self.status.showMessage(tr("빈 서명 칸을 만들었습니다: {name}").format(name=got), 6000)

    @staticmethod
    def _sign_doc_password(cur, doc):
        """암호 문서면 (세션·기억 암호, 기억해 둔 것인지) — 서명은 같은 암호화를 유지해 덧붙인다(SOT §3.5)."""
        try:
            if getattr(doc, "is_encrypted", False) or str((doc.metadata or {}).get("encryption") or ""):
                from viewer import secure_store
                return secure_store.recall_any(cur) or "", bool(secure_store.recall_password(cur))
        except Exception:
            pass
        return "", False

    @staticmethod
    def _sign_is_click(r) -> bool:
        return r.width < SIGN_MIN_SIDE_PT or r.height < SIGN_MIN_SIDE_PT

    @staticmethod
    def _sign_real_size(fp: str) -> tuple:
        """그 ID 의 서명 그림 **실제 크기**(쪽 단위 pt) — 폭 mm(`image_mm`)·그림 비율(보안 SOT §3.3, 261031-6)."""
        from viewer import sign_core, sign_store
        iw = ih = 0
        try:
            ip = sign_store.id_image_path(fp)
            if ip:
                from PIL import Image
                with Image.open(ip) as im:
                    iw, ih = im.size
        except Exception:
            pass
        mm = sign_store.id_image_mm(fp) if fp else sign_store.IMAGE_MM_DEFAULT
        return sign_core.real_box_pt(mm, iw, ih)

    @staticmethod
    def _sign_fit_real(pr, x0: float, y0: float, w: float, h: float):
        """실제 크기 상자를 누른 자리(왼쪽 위)에 — 쪽보다 크면 비율대로 줄이고 쪽 안으로 민다."""
        import fitz
        k = min(1.0, pr.width / max(w, 1e-6), pr.height / max(h, 1e-6))
        w, h = w * k, h * k
        r = fitz.Rect(x0, y0, x0 + w, y0 + h)
        dx = max(0, pr.x0 - r.x0) - max(0, r.x1 - pr.x1)
        dy = max(0, pr.y0 - r.y0) - max(0, r.y1 - pr.y1)
        return fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)

    def _sign_box_fit(self, page, r):
        """클릭(작은 상자)이면 **실제 크기** — 지금 ID 의 서명 그림 폭 mm·비율로, **누른 자리를 왼쪽 위**로
        (261031-6 사용자 지시 — 종전 폭 50mm 고정, 261031-1 왼쪽 위). 쪽 안으로 맞춘다."""
        import fitz
        pr = page.rect
        if self._sign_is_click(r):
            w, h = self._sign_real_size(self._sign_current_fp())
            return self._sign_fit_real(pr, r.x0, r.y0, w, h)
        dx = max(0, pr.x0 - r.x0) - max(0, r.x1 - pr.x1)
        dy = max(0, pr.y0 - r.y0) - max(0, r.y1 - pr.y1)
        r = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy) & pr
        return r

    @staticmethod
    def _sign_store_msg(e) -> str:
        if getattr(e, "reason", "") == "not_found":
            return tr("Windows 인증서 저장소에서 이 인증서를 찾지 못했습니다 — 스마트카드·USB 토큰을 꽂았는지 확인하세요.")
        if getattr(e, "reason", "") == "no_key":
            return tr("이 인증서의 개인 키를 쓸 수 없습니다(개인 키가 없거나 CNG 키가 아닙니다).")
        return tr("Windows 인증서 저장소로 서명하지 못했습니다: {e}").format(e=getattr(e, "detail", "") or str(e))

    @staticmethod
    def _sign_carry_password(final: str, doc_pw: str, remembered: bool) -> None:
        """암호 문서에 서명하면 파일 크기가 늘어 암호 기억 키(경로+크기, 보안 SOT §7.2)가 바뀐다 —
        세션 암호(와 기억해 둔 암호)를 서명한 파일로 옮겨, 다시 열 때 암호를 또 묻지 않게(261010-27)."""
        try:
            from viewer import secure_store
            secure_store.set_session(final, doc_pw)
            if remembered:
                secure_store.remember_password(final, doc_pw)
        except Exception:
            pass

    @staticmethod
    def _sign_tmp(cur: str) -> str:
        """서명 결과 임시 파일 — 원본과 같은 폴더(바꿔치기가 원자적이게), `.pdf` 로 끝나지 않게(목록·색인에 안 뜬다 —
        마스터 §4.7.5 백업과 같은 규칙). 그 폴더에 쓸 수 없으면(읽기 전용 공유 폴더 등) 시스템 임시 폴더 —
        '다른 이름으로 서명' 은 그래도 된다(261011-1)."""
        for d in (str(Path(cur).parent), None):
            try:
                fd, tmp = tempfile.mkstemp(suffix=".polypdf-sign", prefix="~", dir=d)
                os.close(fd)
                return tmp
            except OSError:
                if d is None:
                    raise
        raise OSError(cur)

    @staticmethod
    def _sign_unlink(p):
        try:
            os.remove(p)
        except Exception:
            pass

    def _sigfield_place(self, cur: str, tmp: str) -> str:
        """빈 서명 칸 만들기는 서명이 아니다 — 종전대로 현재 파일에(`_finalize_save`, SOT §3.4·§3.7)."""
        self._sign_saving = True
        try:
            return str(self._finalize_save(cur, tmp, shift=False))
        except Exception as e:                   # noqa: BLE001
            self._sign_unlink(tmp)
            from viewer.file_overwrite import SaveCancelled
            if isinstance(e, SaveCancelled):
                self.status.showMessage(str(e), 5000)
            else:
                QMessageBox.warning(self, tr("빈 서명 칸"), tr("저장하지 못했습니다: {e}").format(e=e))
            return ""
        finally:
            self._sign_saving = False

    # ---- 저장 가드 — SOT §4 --------------------------------------------------
    def _sign_guard(self, dst) -> str:
        """서명된 파일을 덮어쓰려 할 때 묻는다. 'new' | 'overwrite' | 'cancel'. 서명 자체의 저장은 건너뛴다."""
        if getattr(self, "_sign_saving", False):
            return "overwrite"
        signed = False
        try:
            from viewer import sign_core
            mv = self.main_view
            if mv and getattr(mv, "_doc", None) is not None and str(mv.current_file() or "") == str(dst):
                signed = sign_core.doc_is_signed(mv._doc.doc)
            if not signed:
                signed = sign_core.is_signed_file(dst)
        except Exception:
            signed = False
        if not signed:
            return "overwrite"
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication
        # 호출측이 바쁨 포인터를 걸어 둔 채 부른다 — 묻는 동안만 보통 포인터
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.ArrowCursor))
        try:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("서명된 문서"))
            box.setText(tr("'{name}' 에는 전자서명이 있습니다. 이 파일에 덮어쓰면 서명이 무효가 됩니다.").format(name=Path(dst).name))
            box.setInformativeText(tr("새 파일로 저장하면 서명한 원본은 그대로 유효합니다."))
            b_new = box.addButton(tr("새 파일로 저장(권장)"), QMessageBox.ButtonRole.AcceptRole)
            b_over = box.addButton(tr("서명을 무효로 하고 덮어쓰기"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_new)
            box.exec()
            c = box.clickedButton()
        finally:
            QApplication.restoreOverrideCursor()
        if c is b_new:
            return "new"
        if c is b_over:
            return "overwrite"
        return "cancel"

    # ---- 평탄화 내보내기 — 자동 재서명 (SOT §4.1, 261011-2) -----------------------
    def _resign_prepare(self, src: str):
        """서명된 원본이면 확인·키 열기. 반환 None = 취소, 아니면 계획 {sigs, mine, creds}.
        내 ID 의 키를 열지 않으면(취소) 그 ID 서명은 빼고 내보낸다(사용자 지시)."""
        from viewer import sign_core, sign_store
        plan = {"sigs": [], "mine": [], "creds": {}}
        try:
            if not sign_core.is_signed_file(src):
                return plan
        except Exception:
            return plan
        doc_pw = ""
        try:
            from viewer import secure_store
            doc_pw = secure_store.recall_any(src) or ""
        except Exception:
            pass
        try:
            rep = self._sign_bg(lambda: sign_core.verify_pdf(src, sign_store.trusted(), doc_pw), tr("서명 확인 중"))
        except Exception:
            rep = None
        ids = {str(e.get("fp", "")).lower(): e for e in sign_store.load()["ids"]}
        sigs = [{"field": s.field, "fp": str(s.fp or "").lower(), "certify": int(s.certify or 0),
                 "reason": s.reason, "location": s.location, "name": s.signer} for s in (rep.sigs if rep else [])]
        plan["sigs"] = sigs
        mine = [s for s in sigs if s["fp"] in ids]
        others = len(sigs) - len(mine)
        if others:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("평탄화해서 내보내기"))
            box.setText(tr("이 문서에는 전자서명 {n}개가 있습니다. 평탄화하면 파일을 새로 쓰므로 서명을 그대로 둘 수 없습니다.").format(n=len(sigs)))
            box.setInformativeText(
                (tr("내 디지털 ID 로 한 {m}개는 내보낸 파일의 같은 자리에 다시 서명합니다(서명 시각은 지금, 겉모양은 지금 서명 설정).\n").format(m=len(mine)) if mine else "")
                + tr("다른 사람의 서명 {k}개는 내보낸 파일에 남지 않습니다.").format(k=others))
            b_go = box.addButton(tr("계속"), QMessageBox.ButtonRole.AcceptRole)
            b_no = box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_no)
            box.exec()
            if box.clickedButton() is not b_go:
                return None
        # 키 열기 — ID 마다 한 번(SOT §4.1)
        for fp in dict.fromkeys(s["fp"] for s in mine):
            cred = self._resign_unlock(fp, ids[fp])
            if cred is not None:
                plan["creds"][fp] = cred
        plan["mine"] = [s for s in mine if s["fp"] in plan["creds"]]
        return plan

    def _resign_unlock(self, fp: str, entry: dict):
        """('pfx', pfx, 비밀번호) | ('win', 지문, None) | None(취소·실패 — 그 ID 서명은 뺀다)."""
        from viewer import sign_core, sign_store
        if entry.get("kind") == "win":
            return ("win", entry.get("thumb", ""), None)        # Windows 가 서명할 때 PIN 을 묻는다(SOT §3.9)
        try:
            pfx = sign_store.read_pfx(fp)
        except Exception:
            return None
        name = str(entry.get("name", "") or fp[:12])
        if entry.get("hello") and self._sign_hello_ready():
            from viewer import sign_hello
            try:
                return ("pfx", pfx, self._sign_bg(lambda: sign_hello.recall(fp), tr("Windows Hello 확인")))
            except Exception:
                pass                                            # 취소·꺼내기 실패 → 비밀번호 창
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        for _ in range(3):
            pw, ok = QInputDialog.getText(self, tr("다시 서명"), tr("'{name}' 디지털 ID 의 비밀번호 — 취소하면 이 ID 의 서명은 빼고 내보냅니다.").format(name=name),
                                          QLineEdit.EchoMode.Password)
            if not ok or not pw:
                return None
            try:
                self._sign_bg(lambda: sign_core.load_pfx(pfx, pw), tr("디지털 ID 확인 중"))
                return ("pfx", pfx, pw)
            except sign_core.WrongPassword:
                QMessageBox.warning(self, tr("다시 서명"), tr("비밀번호가 맞지 않습니다."))
            except Exception:
                return None
        return None

    @staticmethod
    def _resign_mark(doc, plan) -> None:
        """서명 칸은 굽지 않는다 — 지우고, 다시 서명할 칸은 자리를 숨은 표식으로(SOT §4.1)."""
        if not plan or not plan.get("sigs"):
            return
        from viewer import pdf_mirror as _pm
        _pm.mark_signatures(doc, [s["field"] for s in plan.get("mine") or []])

    @staticmethod
    def _resign_take(doc, plan) -> dict:
        if not plan or not plan.get("mine"):
            from viewer import pdf_mirror as _pm
            _pm.take_marks(doc)                  # 남은 표식이 있어도 지운다
            return {}
        from viewer import pdf_mirror as _pm
        return _pm.take_marks(doc)

    def _resign_appearance(self, fp: str = ""):
        """다시 서명할 겉모양 — 지금 서명 설정 + **그 ID 의** 서명 그림(261031-1)."""
        from viewer import sign_core, sign_store
        d = sign_store.load()
        a = d.get("appearance") or {}
        return sign_core.Appearance(image_path=sign_store.id_image_path(fp) if a.get("show_image", True) else "",
                                    show_name=bool(a.get("show_name", True)), show_date=bool(a.get("show_date", True)),
                                    show_reason=bool(a.get("show_reason", False)), font_path=sign_core.default_font(),
                                    layout=str(a.get("layout") or sign_core.LAYOUT_DEFAULT)), \
            (str(d.get("tsa_url", "") or "") if d.get("tsa_on") else "")

    def _resign_apply(self, path: str, plan, boxes: dict):
        """내보낸 파일 `path` 의 같은 자리에 원래 순서대로 다시 서명한다(증분). (다시 한 수, 빠진 수)."""
        total = len((plan or {}).get("sigs") or [])
        mine = (plan or {}).get("mine") or []
        if not total:
            return 0, 0
        if not mine:
            return 0, total
        from viewer import sign_core
        groups = []                                  # 같은 ID 가 이어지면 한 번에(targets)
        for s in mine:
            if s["field"] not in boxes:
                continue
            if groups and groups[-1][0]["fp"] == s["fp"] and not s["certify"]:
                groups[-1].append(s)
            else:
                groups.append([s])
        done = 0
        first = True
        out = path + ".sig"
        for g in groups:
            fp = g[0]["fp"]
            kind, a1, pw = plan["creds"][fp]
            app, tsa = self._resign_appearance(fp)
            if not sign_core.has_content(app, "x"):                 # 그림·글자가 모두 꺼져 있으면 이름 줄이라도
                app.show_name = True
            certify = g[0]["certify"] if (first and g[0]["certify"]) else 0
            targets = [boxes[s["field"]] for s in g]
            if certify == 1:
                targets = targets[:1]
            signer, pfx = None, b""
            try:
                if kind == "win":
                    from viewer import sign_winstore
                    hwnd = int(self.winId())
                    signer = self._sign_bg(lambda: sign_winstore.make_signer(a1, hwnd=hwnd), tr("인증서 준비 중"))
                else:
                    pfx = a1
                self._sign_bg(lambda: sign_core.sign_pdf(path, out, pfx, pw or "", targets=targets, appearance=app,
                                                         reason=g[0]["reason"], location=g[0]["location"],
                                                         certify=certify, tsa=tsa or None, signer=signer),
                              tr("다시 서명 중 ({n}개)").format(n=len(targets)))
            except Exception:
                self._sign_unlink(out)
                continue
            err = self._file_op_bg(lambda: os.replace(out, path), tr("저장 중"))
            if err is not None:
                self._sign_unlink(out)
                continue
            done += len(targets)
            first = False
        return done, total - done

    # ---- 검증 띠 — SOT §5 ----------------------------------------------------
    def _sign_on_doc_loaded(self):
        mv = self.main_view
        if mv is None:
            return
        band = getattr(mv, "sign_band", None)
        if band is None:
            return
        cur = mv.current_file()
        doc = getattr(getattr(mv, "_doc", None), "doc", None)
        from viewer import sign_core
        mv._sign_empty = len(sign_core.empty_fields(doc)) if (cur and doc is not None) else 0
        self._sign_drafts_sync(mv)                  # 서명 자리 띠·위젯(SOT §3.10)
        if not (cur and doc is not None and sign_core.doc_is_signed(doc)):
            mv._sign_report = None
            if mv._sign_empty:
                band.show_state("empty", tr("이 문서에 빈 서명 칸이 {n}개 있습니다.").format(n=mv._sign_empty))
            else:
                band.clear()
            return
        try:
            mtime = os.stat(cur).st_mtime_ns
        except OSError:
            mtime = 0
        cached = getattr(mv, "_sign_report_key", None)
        if cached == (str(cur), mtime) and getattr(mv, "_sign_report", None) is not None:
            self._sign_show_band(mv, mv._sign_report)
            return
        band.show_state("checking", tr("서명 확인 중…"))
        from viewer import sign_store
        doc_pw = ""
        try:
            if str((doc.metadata or {}).get("encryption") or ""):
                from viewer import secure_store
                doc_pw = secure_store.recall_any(cur) or ""
        except Exception:
            pass
        # 261012-16(응답성 SOT §4.3): 워커 + `run_in_thread` — 끝나면 스스로 정리된다(keep 목록에서도 빠진다)
        from viewer.workers import SignVerifyWorker, run_in_thread
        w = SignVerifyWorker(str(cur), mtime, sign_store.trusted(), doc_pw)
        w.done.connect(lambda p, m, rep, _mv=mv: self._sign_verified(_mv, p, m, rep))
        run_in_thread(w, self._thread_keep)

    def _sign_verified(self, mv, path, mtime, rep):
        if str(mv.current_file() or "") != path:
            return                                   # 그 사이 다른 파일로 갔다
        mv._sign_report = rep
        mv._sign_report_key = (path, mtime)
        self._sign_show_band(mv, rep)

    def _sign_show_band(self, mv, rep):
        from viewer import sign_core as sc
        band = mv.sign_band
        if not rep.sigs:
            band.show_state("invalid", tr("서명을 확인하지 못했습니다({e}).").format(e=rep.error or "?"))
            return
        worst = rep.worst
        names = ", ".join(dict.fromkeys(s.signer or "?" for s in rep.sigs))
        text = {sc.OK_TRUSTED: tr("서명자 {names} · 유효 · 신뢰함"),
                sc.OK_UNKNOWN: tr("서명자 {names} · 유효 · 신원 미확인(신뢰 목록에 없음)"),
                sc.MODIFIED: tr("서명자 {names} · 서명 뒤 문서가 변경됨"),
                sc.INVALID: tr("서명자 {names} · 서명 무효 — 서명한 내용이 바뀌었거나 확인할 수 없습니다")}[worst]
        text = text.format(names=names)
        if getattr(mv, "_sign_empty", 0):
            text += tr(" · 빈 서명 칸 {n}개").format(n=mv._sign_empty)
        band.show_state(worst, text)
        band.set_editable(self._sign_editable(str(mv.current_file() or ""), rep))     # [서명 편집](SOT §3.10)

    def _on_sign_panel(self, view=None):
        mv = view or self.main_view
        if getattr(getattr(mv, "sign_band", None), "state", "") == "empty":
            try:
                self._set_active_pane(self._mv.index(mv))
            except Exception:
                pass
            self.action_sign_pdf()                   # 빈 칸만 있는 띠의 [서명] (SOT §3.7)
            return
        rep = getattr(mv, "_sign_report", None)
        if rep is None:
            return
        from viewer.widgets.sign_dialogs import SignPanelDialog
        cur = str(mv.current_file() or "")

        def _open_rev(path, _src=cur):
            try:
                self.bookmark_tree.add_or_refresh_file(path, after=_src)
            except Exception:
                pass
            self._open_saved_file(path)
        dlg = SignPanelDialog(self, rep, path=cur, open_cb=_open_rev)
        dlg.exec()
        if dlg.trust_changed:
            mv._sign_report_key = None
            self._sign_on_doc_loaded()
