# -*- coding: utf-8 -*-
"""전자서명 흐름 — `MainWindow` 믹스인 (보안 SOT §3·§4·§5·§6, 마스터 §11.11 믹스인 표준).

  도구 '서명' → 사전 점검(§3.5) → 디지털 ID·서명 그림 확인 → 본문에서 자리 끌기(§3.3)
  → 서명 창 → 비밀번호(1순위 Windows Hello · 2순위 직접 입력/붙여넣기, §6)
  → 배경에서 증분 서명 → `_finalize_save` 로 현재 파일에(§3.4) → 다시 열면 검증 띠(§5).

서명된 PDF 를 PolyPDF 가 다시 쓰면(전체 저장) 서명이 깨진다 — `_sign_guard` 를 `_finalize_save` 가
진입에서 부른다(§4, 가드는 한 곳).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr

SIGN_DEFAULT_WIDTH_PT = 50 / 25.4 * 72      # 클릭만 했을 때 서명 상자 폭 50mm (SOT §3.3)
SIGN_MIN_SIDE_PT = 12                       # 이보다 작게 끌면 클릭으로 본다


class _SignVerifyThread(QThread):
    """서명 검증 — 배경(SOT §10). 결과는 (경로, mtime, 보고서)."""
    done = pyqtSignal(str, object, object)

    def __init__(self, path, mtime, trusted, doc_pw, parent=None):
        super().__init__(parent)
        self._a = (path, mtime, trusted, doc_pw)

    def run(self):
        path, mtime, trusted, doc_pw = self._a
        try:
            from viewer import sign_core
            rep = sign_core.verify_pdf(path, trusted, doc_pw)
        except Exception as e:                   # noqa: BLE001
            from viewer.sign_core import VerifyReport
            rep = VerifyReport(error=type(e).__name__)
        self.done.emit(path, mtime, rep)


class SignMixin:
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
        from viewer.widgets.sign_dialogs import DigitalIdDialog
        DigitalIdDialog(self, runner=self._sign_bg, hello_ok=self._sign_hello_ready()).exec()

    def action_sign_image(self) -> str:
        from viewer.widgets.sign_dialogs import SignImageDialog
        dlg = SignImageDialog(self)
        dlg.exec()
        return dlg.saved_name

    def action_sign_pdf(self, at_scene=None):
        """도구 '서명' — 사전 점검 뒤 본문에서 자리를 끌게 한다(SOT §3).
        `at_scene`(scene 점, 본문 우클릭 '여기에 서명…')이면 끌지 않고 그 자리에 기본 크기로 바로 서명 창(S6)."""
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if not (cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None):
            QMessageBox.information(self, tr("서명"), tr("서명할 PDF를 먼저 여세요."))
            return
        if not self._sign_preflight(str(cur)):
            return
        from viewer import sign_store
        d = sign_store.load()
        if not d["ids"]:
            if QMessageBox.question(self, tr("서명"), tr("디지털 ID 가 없습니다. 지금 만들까요?")) != QMessageBox.StandardButton.Yes:
                return
            self.action_digital_ids()
            if not sign_store.load()["ids"]:
                return
        if not sign_store.load()["images"]:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("서명"))
            box.setText(tr("서명 그림이 없습니다. 종이에 한 서명을 찍은 사진으로 만들까요?"))
            b_make = box.addButton(tr("서명 그림 만들기…"), QMessageBox.ButtonRole.AcceptRole)
            b_skip = box.addButton(tr("그림 없이"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            c = box.clickedButton()
            if c is b_make:
                self.action_sign_image()
            elif c is not b_skip:
                return
        # 3단계(SOT §3.7): 빈 서명 칸이 있으면 먼저 묻는다 — 끌기·우클릭은 _on_sign_region 이 칸 안인지 본다
        from viewer import sign_core as _sc
        empties = _sc.empty_fields(mv._doc.doc)
        if at_scene is None and empties:
            choice = self._sign_choose_field(empties, _sc.doc_certify_level(mv._doc.doc))
            if choice is None:
                return
            if choice != "new":
                self._sign_fill_field(str(cur), choice, mv)
                return
        self._sign_pending = str(cur)
        self._sign_pending_mode = "sign"
        if at_scene is not None:
            from PyQt6.QtCore import QRectF
            self._on_sign_region(QRectF(at_scene, at_scene), view=mv)     # 크기 0 = 클릭 → 기본 크기(_sign_box_fit)
            return
        mv.view.arm_block_select(True, purpose="sign")
        self.status.showMessage(tr("서명할 자리를 본문에서 끌어 정하세요(클릭만 하면 기본 크기)."), 8000)

    def _sign_preflight(self, cur: str) -> bool:
        """SOT §3.5 — 저장 안 한 편집 · PolyPDF 꾸밈 · 권한 · 보기 상태."""
        dirty = False
        try:
            dirty = bool(self._page_edits_dirty() or getattr(self, "_edit_dirty", False)
                         or getattr(self.bookmark_tree, "_dirty", False))
        except Exception:
            pass
        if dirty:
            QMessageBox.information(self, tr("서명"), tr("저장하지 않은 편집(쪽·크롭·책갈피·꾸밈)이 있습니다. 먼저 저장해야 서명할 수 있습니다 — 서명은 디스크에 있는 판에 합니다."))
            return False
        # PolyPDF 가 따로 든 꾸밈·사진·하이퍼링크 — 서명에 들어가지 않는다
        side = False
        try:
            side = bool(self._decorations_norm_for(cur))
            st_hl = self._ensure_hyperlink_store()
            side = side or bool(st_hl and st_hl.pages_with_links(cur))
            st_im = self._ensure_page_meta_store()
            side = side or bool(st_im and st_im.pages_with_images(cur))
        except Exception:
            pass
        if side:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("서명"))
            box.setText(tr("이 파일에는 PolyPDF 가 따로 든 꾸밈·사진·하이퍼링크가 있습니다. 이것들은 서명에 들어가지 않고 다른 뷰어에서 보이지 않습니다."))
            box.setInformativeText(tr("서명에 넣으려면 먼저 '저장(일반뷰어용)' 으로 현재 파일에 구운 뒤 다시 서명하세요."))
            b_bake = box.addButton(tr("일반뷰어용으로 먼저 저장…"), QMessageBox.ButtonRole.AcceptRole)
            b_go = box.addButton(tr("그대로 서명"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_bake)
            box.exec()
            c = box.clickedButton()
            if c is b_bake:
                self._action_save_decorated_pdf(file_path=cur)
                return False
            if c is not b_go:
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
        if mv._rotations.get(pidx, 0):
            QMessageBox.information(self, tr("서명"), tr("보기 회전을 한 쪽에는 그대로 서명할 수 없습니다. 회전을 되돌리거나, '저장(일반뷰어용)' 으로 회전을 넣어 쪽을 바로 세운 뒤 서명하세요."))
            return
        page = mv._doc.doc[pidx]
        if page.rotation:
            # SOT §3.3 — 회전된 쪽은 겉모양이 누워 들어간다. 일반뷰어용 저장이 바로 세운다(마스터 §4.7.13)
            QMessageBox.information(self, tr("서명"), tr("이 쪽은 PDF 안에서 회전되어 있어 그대로 서명할 수 없습니다(서명이 누워 들어갑니다). '저장(일반뷰어용)' 으로 쪽을 바로 세운 뒤 서명하세요."))
            return
        z = mv._zoom or 1.0
        r = fitz.Rect(scene_rect.left() / z, scene_rect.top() / z, scene_rect.right() / z, scene_rect.bottom() / z)
        from viewer import sign_core as _sc
        if mode == "sigfield":
            self._sigfield_make(cur, pidx, self._sign_box_fit(page, r), mv)
            return
        # 끌기·우클릭의 가운데가 빈 서명 칸 안이면 그 칸을 채운다(SOT §3.7)
        hit = _sc.field_at(_sc.empty_fields(mv._doc.doc), pidx, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if hit is not None:
            self._sign_fill_field(cur, hit, mv)
            return
        r = self._sign_box_fit(page, r)
        self._sign_open_dialog(cur, pidx, r, mv)

    def _sign_open_dialog(self, cur, pidx, r, mv, field=None):
        from viewer.widgets.sign_dialogs import SignDialog
        from viewer import sign_core as _sc
        hello_ok = self._sign_hello_ready()
        dlg = SignDialog(self, hello_ok=hello_ok, file_name=Path(cur).name, box_size=(r.width, r.height),
                         page_count=mv._doc.doc.page_count, current_page=pidx,
                         can_certify=not _sc.doc_is_signed(mv._doc.doc),
                         field_name=field.name if field is not None else "")
        try:
            self._sign_dialog_loop(cur, pidx, r, dlg, mv)
        finally:
            dlg.stop_preview()

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
        """빈 칸 하나를 채운다 — 그 쪽으로 가서 칸 크기 그대로 서명 창(SOT §3.7)."""
        import fitz
        if mv.is_two_page_mode():
            QMessageBox.information(self, tr("서명"), tr("2쪽 보기에서는 자리를 정할 수 없습니다. 1쪽 보기로 바꾼 뒤 다시 서명하세요."))
            return
        page = mv._doc.doc[field.page]
        if page.rotation or mv._rotations.get(field.page, 0):
            QMessageBox.information(self, tr("서명"), tr("이 쪽은 PDF 안에서 회전되어 있어 그대로 서명할 수 없습니다(서명이 누워 들어갑니다). '저장(일반뷰어용)' 으로 쪽을 바로 세운 뒤 서명하세요."))
            return
        if int(mv.current_page()) != field.page:
            try:
                mv.go_to_page(field.page)
            except Exception:
                pass
        self._sign_open_dialog(cur, field.page, fitz.Rect(*field.rect), mv, field=field)

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
        self._sign_pending = str(cur)
        self._sign_pending_mode = "sigfield"
        mv.view.arm_block_select(True, purpose="sign")
        self.status.showMessage(tr("빈 서명 칸 자리를 본문에서 끌어 정하세요(클릭만 하면 기본 크기)."), 8000)

    def _sigfield_make(self, cur: str, pidx: int, r, mv):
        from PyQt6.QtWidgets import QInputDialog
        from viewer import sign_core
        doc = mv._doc.doc
        used = {f.name for f in sign_core.empty_fields(doc)}
        k = 1
        while f"Signature{k}" in used:
            k += 1
        name, ok = QInputDialog.getText(self, tr("빈 서명 칸"), tr("칸 이름 — 서명할 사람이 알아보게(예: 검토자, 승인자)"),
                                        text=f"Signature{k}")
        if not ok:
            return
        box = sign_core.page_box_to_pdf(doc[pidx], r)
        doc_pw, remembered = self._sign_doc_password(cur, doc)
        fd, tmp = tempfile.mkstemp(suffix=".polypdf-sign", prefix="~", dir=str(Path(cur).parent))
        os.close(fd)
        try:
            got = self._sign_bg(lambda: sign_core.add_empty_field(cur, tmp, page_index=pidx, box_pdf=box,
                                                                  name=name, doc_password=doc_pw),
                                tr("빈 서명 칸 만드는 중"))
        except sign_core.SignError as e:
            self._sign_unlink(tmp)
            msg = {"field_exists": tr("같은 이름의 서명 칸이 이미 있습니다: {name}").format(name=e.detail),
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
        final = self._sign_place(cur, tmp, False)
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

    def _sign_dialog_loop(self, cur, pidx, r, dlg, mv):
        while True:
            dlg.save_as = dlg.use_hello = False
            dlg.ed_pw.clear()                    # 틀린 비밀번호를 다시 보이지 않는다
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            pw = self._sign_password(dlg)
            if pw is None:
                continue
            ok = self._sign_do(cur, pidx, r, dlg, pw, mv)
            if ok != "retry":
                return

    def _sign_box_fit(self, page, r):
        """클릭(작은 상자)이면 기본 크기 — 서명 그림 비율, 쪽 안으로 맞춘다."""
        import fitz
        pr = page.rect
        if r.width < SIGN_MIN_SIDE_PT or r.height < SIGN_MIN_SIDE_PT:
            w = SIGN_DEFAULT_WIDTH_PT
            h = w / 2.5
            try:
                from viewer import sign_store
                ip = sign_store.image_path(sign_store.load().get("default_image", ""))
                if ip:
                    from PIL import Image
                    with Image.open(ip) as im:
                        h = w * im.height / max(1, im.width)
            except Exception:
                pass
            cx, cy = r.x0, r.y0
            r = fitz.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        dx = max(0, pr.x0 - r.x0) - max(0, r.x1 - pr.x1)
        dy = max(0, pr.y0 - r.y0) - max(0, r.y1 - pr.y1)
        r = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy) & pr
        return r

    def _sign_password(self, dlg):
        """1순위 Windows Hello, 안 되면 칸에 넣은 비밀번호(SOT §6). None = 다시 서명 창으로."""
        fp = dlg.fp()
        from viewer import sign_store
        if (sign_store.get_id(fp) or {}).get("kind") == "win":
            return ""                            # Windows 저장소 — 비밀번호 대신 Windows 가 PIN 을 묻는다(SOT §3.9)
        if dlg.use_hello:
            from viewer import sign_hello
            try:
                return self._sign_bg(lambda: sign_hello.recall(fp), tr("Windows Hello 확인"))
            except sign_hello.HelloCancelled:
                self.status.showMessage(tr("Windows Hello 를 취소했습니다 — 비밀번호를 넣어 서명할 수 있습니다."), 6000)
                return None
            except Exception:
                QMessageBox.information(self, tr("서명"), tr("Windows Hello 로 보관한 비밀번호를 꺼내지 못했습니다. 비밀번호를 넣어 서명하세요 — 서명한 뒤 다시 보관할지 묻습니다."))
                self._sign_rehello = fp
                return None
        return dlg.password() or None

    def _sign_do(self, cur: str, pidx: int, rect, dlg, pw: str, mv=None) -> str:
        """배경에서 서명 → 저장 → 다시 열기. 반환 'ok' | 'retry' | 'fail'."""
        from viewer import sign_core, sign_store
        fp = dlg.fp()
        entry = sign_store.get_id(fp) or {}
        pfx, signer = b"", None
        if entry.get("kind") == "win":
            # Windows 인증서 저장소(SOT §3.9) — 키는 Windows 안에, PIN 은 Windows 가 묻는다
            from viewer import sign_winstore
            try:
                signer = sign_winstore.make_signer(entry.get("thumb", ""), hwnd=int(self.winId()))
            except sign_winstore.StoreError as e:
                QMessageBox.warning(self, tr("서명"), self._sign_store_msg(e))
                return "fail"
        else:
            try:
                pfx = sign_store.read_pfx(fp)
            except Exception:
                QMessageBox.warning(self, tr("서명"), tr("디지털 ID 파일을 찾지 못했습니다. 디지털 ID 창에서 다시 가져오세요."))
                return "fail"
        doc = (mv or self.main_view)._doc.doc     # 자리를 끈 그 창(2단이면 오른쪽일 수 있다)
        field = getattr(dlg, "field_name", "") or ""
        # 2단계(SOT §3.6): 여러 쪽 — 같은 자리(쪽 좌표)에, 쪽 밖이면 쪽 안으로. 회전 쪽은 막는다.
        # 3단계(SOT §3.7): 빈 칸 채우기는 그 칸 하나(쪽 고르기 끔)
        pages = [pidx] if field else dlg.pages()
        if not pages:
            QMessageBox.information(self, tr("서명"), tr("쪽 범위를 읽지 못했습니다. 예: 1-3, 5"))
            return "retry"
        certify = dlg.certify()
        if certify == 1 and len(pages) > 1:
            QMessageBox.information(self, tr("서명"), tr("'인증 — 변경 금지' 는 한 쪽에만 할 수 있습니다(뒤따르는 서명도 변경이 됩니다)."))
            return "retry"
        rotated = [p + 1 for p in pages
                   if doc[p].rotation or (mv or self.main_view)._rotations.get(p, 0)]
        if rotated:
            QMessageBox.information(self, tr("서명"), tr("회전된 쪽이 있어 서명할 수 없습니다: p.{pages}\n'저장(일반뷰어용)' 으로 쪽을 바로 세운 뒤 서명하세요.").format(
                pages=", ".join(str(x) for x in rotated[:20])))
            return "retry"
        if len(pages) > 30 and QMessageBox.question(
                self, tr("서명"), tr("{n}쪽에 서명합니다 — 쪽마다 서명이 하나씩 들어가 시간이 걸리고 파일이 커집니다. 계속할까요?").format(n=len(pages))
        ) != QMessageBox.StandardButton.Yes:
            return "retry"
        targets = []
        if not field:
            for p in pages:
                targets.append((p, sign_core.page_box_to_pdf(doc[p], self._sign_box_fit(doc[p], rect))))
        app = dlg.appearance()
        tsa = dlg.tsa_url()
        doc_pw, remembered = self._sign_doc_password(cur, doc)
        # 같은 폴더(바꿔치기가 원자적이게), `.pdf` 로 끝나지 않게(목록·색인에 안 뜬다 — 마스터 §4.7.5 백업과 같은 규칙)
        fd, tmp = tempfile.mkstemp(suffix=".polypdf-sign", prefix="~", dir=str(Path(cur).parent))
        os.close(fd)
        reason, loc = dlg.ed_reason.text(), dlg.ed_loc.text()
        try:
            self._sign_bg(lambda: sign_core.sign_pdf(cur, tmp, pfx, pw, targets=targets or None, appearance=app,
                                                     reason=reason, location=loc, doc_password=doc_pw,
                                                     certify=certify, tsa=tsa or None, field=field,
                                                     signer=signer),
                          tr("서명 중") if len(targets) <= 1 else tr("서명 중 ({n}쪽)").format(n=len(targets)))
        except sign_core.WrongPassword:
            self._sign_unlink(tmp)
            QMessageBox.warning(self, tr("서명"), tr("비밀번호가 맞지 않습니다."))
            return "retry"
        except sign_core.SignError as e:
            self._sign_unlink(tmp)
            msg = {"certified": tr("작성자가 서명 뒤 변경을 금지한 문서입니다 — 서명을 더할 수 없습니다."),
                   "certified_new_field": tr("작성자가 인증한 문서입니다 — 새 서명 칸을 더하면 인증이 허용하지 않은 변경이 됩니다. 문서에 빈 서명 칸이 있으면 그 칸에만 서명할 수 있습니다."),
                   "no_field": tr("빈 서명 칸을 찾지 못했습니다(이미 서명됐거나 지워졌습니다): {name}").format(name=e.detail),
                   "certify_not_first": tr("이미 서명이 있는 문서에는 인증 서명을 할 수 없습니다(인증은 첫 서명만)."),
                   "certify_one_page": tr("'인증 — 변경 금지' 는 한 쪽에만 할 수 있습니다(뒤따르는 서명도 변경이 됩니다)."),
                   "tsa_failed": tr("타임스탬프 기관에서 시각을 받지 못해 서명하지 않았습니다. 주소·인터넷을 확인하거나 타임스탬프를 끄고 서명하세요.\n({d})").format(d=e.detail[:120]),
                   "need_doc_password": tr("암호 문서의 암호를 모릅니다. 권한 암호로 연 뒤 서명하세요."),
                   "unreadable": tr("이 PDF 는 그대로 서명할 수 없습니다(파일 구조 손상). 먼저 PolyPDF 로 저장(다른 이름으로 저장)해 정리한 뒤 그 파일에 서명하세요."),
                   "no_font": tr("겉모양 글자에 쓸 한글 글꼴이 없습니다. 서명 그림을 고르거나 겉모양 글자를 끄세요.")
                   }.get(e.reason, tr("서명하지 못했습니다: {e}").format(e=e.detail or e.reason))
            QMessageBox.warning(self, tr("서명"), msg)
            return "fail"
        except Exception as e:                   # noqa: BLE001
            self._sign_unlink(tmp)
            from viewer import sign_winstore
            if isinstance(e, sign_winstore.StoreCancelled):
                self.status.showMessage(tr("Windows 가 물은 PIN·확인을 취소했습니다."), 6000)
                return "retry"
            if isinstance(e, sign_winstore.StoreError):
                QMessageBox.warning(self, tr("서명"), self._sign_store_msg(e))
                return "fail"
            QMessageBox.warning(self, tr("서명"), tr("서명하지 못했습니다: {e}").format(e=type(e).__name__))
            return "fail"
        # Hello 보관을 다시 하자고 했으면(꺼내기 실패) 지금 맞은 비밀번호로
        if getattr(self, "_sign_rehello", None) == fp:
            self._sign_rehello = None
            if QMessageBox.question(self, tr("Windows Hello"), tr("이 비밀번호를 Windows Hello 로 다시 보관할까요?")) == QMessageBox.StandardButton.Yes:
                from viewer import sign_hello
                try:
                    self._sign_bg(lambda: sign_hello.store(fp, pw), tr("Windows Hello 확인"))
                    sign_store.set_id_flag(fp, hello=True)
                except Exception:
                    pass
        final = self._sign_place(cur, tmp, dlg.save_as)
        if not final:
            return "fail"
        if doc_pw:
            self._sign_carry_password(final, doc_pw, remembered)
        try:
            self.bookmark_tree.add_or_refresh_file(final, after=str(cur))
            self._open_saved_file(final, pidx)
        except Exception:
            pass
        self.status.showMessage(tr("서명했습니다: {name}").format(name=Path(final).name), 6000)
        return "ok"

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
    def _sign_unlink(p):
        try:
            os.remove(p)
        except Exception:
            pass

    def _sign_place(self, cur: str, tmp: str, save_as: bool) -> str:
        """현재 파일(기본, `_finalize_save`) 또는 다른 이름(SOT §3.4)."""
        if save_as:
            from PyQt6.QtWidgets import QFileDialog
            default = str(Path(cur).with_name(tr("{stem}_서명.pdf").format(stem=Path(cur).stem)))
            out, _ = QFileDialog.getSaveFileName(self, tr("다른 이름으로 서명"), default, tr("PDF 파일 (*.pdf)"))
            if not out:
                self._sign_unlink(tmp)
                return ""
            if not out.lower().endswith(".pdf"):
                out += ".pdf"
            if os.path.normcase(os.path.abspath(out)) != os.path.normcase(os.path.abspath(cur)):
                err = self._file_op_bg(lambda: os.replace(tmp, out), tr("저장 중: {name}").format(name=Path(out).name))
                if err is not None:
                    self._sign_unlink(tmp)
                    QMessageBox.warning(self, tr("서명"), tr("저장하지 못했습니다: {e}").format(e=err))
                    return ""
                return out
        self._sign_saving = True
        try:
            return str(self._finalize_save(cur, tmp, shift=False))
        except Exception as e:                   # noqa: BLE001
            self._sign_unlink(tmp)
            from viewer.file_overwrite import SaveCancelled
            if isinstance(e, SaveCancelled):
                self.status.showMessage(str(e), 5000)
            else:
                QMessageBox.warning(self, tr("서명"), tr("저장하지 못했습니다: {e}").format(e=e))
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
        th = _SignVerifyThread(str(cur), mtime, sign_store.trusted(), doc_pw, self)
        th.done.connect(lambda p, m, rep, _mv=mv: self._sign_verified(_mv, p, m, rep))
        # 끝난 스레드는 목록에서 빼고 지운다 — deleteLater 만 걸고 목록에 남기면 다음 판정 때 지워진 객체를 만진다(실측)
        threads = getattr(self, "_sign_threads", None)
        if threads is None:
            threads = self._sign_threads = []
        threads.append(th)

        def _gone(t=th, lst=threads):
            try:
                lst.remove(t)
            except ValueError:
                pass
            t.deleteLater()
        th.finished.connect(_gone)
        th.start()

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
