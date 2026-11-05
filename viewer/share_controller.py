# -*- coding: utf-8 -*-
"""'전달' — PDF + PolyPDF 자료 묶음(.polypdf.zip) 만들기·받기 (261105-9, 마스터 §4.7.23).

- 만들기: 책갈피창 우클릭 '전달...' → 넣을 자료 고르기 → 저장 자리 → 배경 일감(`_run_merge_job`) → 묶음 파일을 클립보드에(골랐으면).
  꾸밈·링크·태그는 **메인에서 미리 떼어** 넘긴다(앱 저장소를 배경에서 읽지 않는다). 파일 일·DB 는 배경(`share_bundle`).
- 받기: 묶음을 끌어 놓거나 [PDF 열기] 에서 고르면 → 풀 자리 → 배경에서 풀고 자료를 그 경로 키로 → 목록에 더한다.
방식은 §11.11 표준 믹스인(`class MainWindow(…, ShareMixin, …)`).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMessageBox,
                             QVBoxLayout)

from viewer.i18n import tr


class _Pre:
    """메인에서 떼어 둔 기록을 배경의 `collect` 에 건넨다(`export_entry`·`get_manual`·`get_keywords` 꼴)."""

    def __init__(self, d: dict):
        self.d = d

    def export_entry(self, p):
        return self.d.get(str(p))

    def get_manual(self, p):
        return (self.d.get(str(p)) or {}).get("manual") or []

    def get_keywords(self, p):
        return (self.d.get(str(p)) or {}).get("keywords") or []


class ShareDialog(QDialog):
    """넣을 자료 고르기 — OCR·단어장 / 고친 글·하이라이트 / 꾸밈·링크(켬), 태그(끔 — 내 분류라서), 클립보드(켬)."""

    def __init__(self, parent, n: int, last: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("전달"))
        last = dict(last or {})
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("PDF {n}개를 묶음 파일(.polypdf.zip)로 만듭니다.\n받는 사람이 PolyPDF 로 열면 아래 자료까지 함께 봅니다 — 원본 PDF 는 바뀌지 않습니다.").format(n=n)))
        self.cb = {}
        for key, label, on in (("ocr", tr("OCR 결과·단어장(고른 낱말 포함)"), True),
                               ("fix", tr("텍스트 창 고친 글·하이라이트"), True),
                               ("deco", tr("꾸밈(선·도형·글·사진)·하이퍼링크 — 저장하지 않은 것 포함"), True),
                               ("tags", tr("해시태그·키워드"), False)):
            c = QCheckBox(label)
            c.setChecked(bool(last.get(key, on)))
            lay.addWidget(c)
            self.cb[key] = c
        self.cb_clip = QCheckBox(tr("만든 파일을 클립보드에 복사(메신저·메일 창에 붙여넣기)"))
        self.cb_clip.setChecked(bool(last.get("clip", True)))
        lay.addWidget(self.cb_clip)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("만들기..."))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("취소"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        v = {k: c.isChecked() for k, c in self.cb.items()}
        v["clip"] = self.cb_clip.isChecked()
        return v


class ShareMixin:
    # ── 만들기 ──
    def action_share_files(self, files) -> str:
        """고른 PDF 들의 전달 묶음을 만든다. 만든 묶음 경로(못 만들면 "")."""
        from viewer import share_bundle
        files = [str(Path(f)) for f in (files or []) if f and str(f).lower().endswith(".pdf") and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("전달"), tr("전달할 PDF 가 없습니다."))
            return ""
        dlg = ShareDialog(self, len(files), getattr(self, "_share_opts", None))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        opts = dlg.values()
        self._share_opts = opts
        parts = [k for k in share_bundle.PARTS if opts.get(k)]
        start = str(Path(files[0]).parent / share_bundle.default_name(files))
        out, _ = QFileDialog.getSaveFileName(self, tr("전달 묶음 저장"), start,
                                             tr("PolyPDF 전달 묶음") + " (*" + share_bundle.SUFFIX + ")")
        if not out:
            return ""
        if not out.lower().endswith(share_bundle.SUFFIX):
            out = str(Path(out).with_suffix("")) + share_bundle.SUFFIX if out.lower().endswith(".zip") else out + share_bundle.SUFFIX
        pm_map, hl_map, tag_map = self._share_pre(files, parts)

        def stores_for(_folder):
            return _Pre(pm_map), _Pre(hl_map)

        def job(progress):
            def tick(i, n, name):
                progress(i, max(1, n), name)
            share_bundle.build(files, out, parts, stores_for=stores_for,
                               tags=_Pre(tag_map) if "tags" in parts else None, progress=tick)
        res = self._run_merge_job(job, tr("전달 묶음 만들기"))
        if res.get("cancelled") or not Path(out).exists():
            if res.get("err"):
                QMessageBox.warning(self, tr("전달"), tr('묶음을 만들지 못했습니다: {e}').format(e=res["err"]))
            return ""
        if opts.get("clip"):
            self._share_to_clipboard(out)
        self.status.showMessage((tr('전달 묶음을 만들고 클립보드에 복사했습니다: {name}') if opts.get("clip")
                                 else tr('전달 묶음을 만들었습니다: {name}')).format(name=Path(out).name), 8000)
        return out

    def _share_pre(self, files, parts):
        """꾸밈·링크·태그를 메인에서 떼어 둔다 — 연 폴더의 것은 지금 메모리(저장 안 한 꾸밈 포함), 다른 폴더는 그 폴더 사이드카."""
        from viewer.page_meta import PageMetaStore
        from viewer.hyperlinks import HyperlinkStore
        pm_map, hl_map, tag_map = {}, {}, {}
        root = str(self._folder) if getattr(self, "_folder", None) else ""
        others = {}
        for f in files:
            if "deco" in parts:
                folder = str(Path(f).parent)
                if root and self._share_inside(root, f):
                    pm, hl = self._ensure_page_meta_store(), self._ensure_hyperlink_store()
                else:
                    if folder not in others:
                        others[folder] = (PageMetaStore(Path(folder)), HyperlinkStore(Path(folder)))
                    pm, hl = others[folder]
                for st, m in ((pm, pm_map), (hl, hl_map)):
                    try:
                        e = st.export_entry(f) if st is not None else None
                        if e:
                            m[str(f)] = e
                    except Exception:
                        pass
            if "tags" in parts and getattr(self, "_tags", None) is not None:
                try:
                    tag_map[str(f)] = {"manual": list(self._tags.get_manual(str(f)) or []),
                                       "keywords": list(self._tags.get_keywords(str(f)) or [])}
                except Exception:
                    pass
        return pm_map, hl_map, tag_map

    @staticmethod
    def _share_inside(root: str, p: str) -> bool:
        import os
        from viewer.pathutil import norm_key
        try:
            return norm_key(os.path.commonpath([root, str(p)])) == norm_key(root)
        except ValueError:
            return False

    def _share_to_clipboard(self, path):
        """묶음 **파일**을 클립보드에 — 탐색기·메신저·메일 창에 붙여넣으면 첨부된다."""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtWidgets import QApplication
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(path))])
        QApplication.clipboard().setMimeData(md)

    # ── 받기 ──
    def open_share_bundle(self, zip_path) -> list:
        """받은 묶음을 풀고 자료를 넣은 뒤 목록에 더한다. 푼 PDF 경로 목록."""
        from viewer import share_bundle
        zp = Path(zip_path)
        man = {}

        def _read():
            man.update(share_bundle.read_manifest(zp))
        e = self._file_op_bg(_read, tr("묶음 읽는 중…"))
        if e is not None:
            QMessageBox.warning(self, tr("전달 묶음 열기"), str(e))
            return []
        files = man.get("files") or []
        if not files:
            QMessageBox.information(self, tr("전달 묶음 열기"), tr("묶음에 PDF 가 없습니다."))
            return []
        dest = self._share_ask_dest(zp, len(files))
        if dest is None:
            return []
        got = []

        def job(progress):
            got.extend(share_bundle.extract(zp, dest, progress=lambda i, n, name: progress(i, max(1, n), name)))
        res = self._run_merge_job(job, tr("전달 묶음 풀기"))
        if res.get("err") and not got:
            QMessageBox.warning(self, tr("전달 묶음 열기"), tr('묶음을 풀지 못했습니다: {e}').format(e=res["err"]))
            return []
        bad = [p.name for p, _r, ok in got if not ok]
        good = [(p, r) for p, r, ok in got if ok]

        def _apply():
            for p, r in good:
                share_bundle.apply_records(p, r)
        e = self._file_op_bg(_apply, tr("받은 자료 넣는 중…"))
        self._share_apply_qt(dest, good)
        paths = [str(p) for p, _r, _ok in got]
        if paths:
            self.add_pdfs(paths)
            try:
                self._pending_refresh()
            except Exception:
                pass
        msg = tr('PDF {n}개를 풀었습니다: {dest}').format(n=len(paths), dest=dest)
        if bad:
            msg += "\n\n" + tr('내용이 목록과 달라(손상·바뀜) 자료를 넣지 않은 파일: {names}').format(names=", ".join(bad))
        if e is not None:
            msg += "\n\n" + tr('자료를 넣다가 실패: {e}').format(e=e)
        QMessageBox.information(self, tr("전달 묶음 열기"), msg)
        return paths

    def _share_ask_dest(self, zp: Path, n: int):
        here = zp.parent / zp.name[: -len(".polypdf.zip")] if zp.name.lower().endswith(".polypdf.zip") else zp.parent / zp.stem
        box = QMessageBox(self)
        box.setWindowTitle(tr("전달 묶음 열기"))
        box.setText(tr("PolyPDF 전달 묶음 — PDF {n}개\n\n풀 폴더: {here}").format(n=n, here=here))
        b_here = box.addButton(tr("여기에 풀기"), QMessageBox.ButtonRole.AcceptRole)
        b_pick = box.addButton(tr("다른 폴더..."), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_here:
            return here
        if c is b_pick:
            d = QFileDialog.getExistingDirectory(self, tr("풀 폴더"), str(zp.parent))
            return Path(d) if d else None
        return None

    def _share_apply_qt(self, dest, good):
        """꾸밈·링크는 그 폴더 사이드카에, 태그는 태그 저장소에(메인 — 작은 JSON)."""
        from viewer.page_meta import PageMetaStore
        from viewer.hyperlinks import HyperlinkStore
        root = str(self._folder) if getattr(self, "_folder", None) else ""
        dirty = bool(getattr(self, "_edit_dirty", False))
        for key, cls, getter in (("page_meta", PageMetaStore, self._ensure_page_meta_store),
                                 ("hyperlinks", HyperlinkStore, self._ensure_hyperlink_store)):
            items = [(p, r[key]) for p, r in good if r.get(key)]
            if not items:
                continue
            same = bool(root) and self._share_inside(root, str(dest))
            st = getter() if same else cls(Path(dest))
            if st is None:
                continue
            for p, ent in items:
                try:
                    st.import_entry(str(p), ent)
                except Exception:
                    pass
            if not (same and dirty):
                try:
                    st.save()
                except Exception:
                    pass
        tg = getattr(self, "_tags", None)
        if tg is not None:
            for p, r in good:
                t = r.get("tags") or {}
                try:
                    if t.get("manual"):
                        tg.set(str(p), list(t["manual"]))
                    if t.get("keywords"):
                        tg.set_keywords(str(p), list(t["keywords"]), src="share")
                except Exception:
                    pass
