# -*- coding: utf-8 -*-
"""형식 변환 진입 (형식 변환 SOT §2, 261014-11) — 메뉴 넷이 모두 `action_convert` 하나로 들어온다.

- 파일·도구 탭 '변환...'(261025-5, 종전 '변환해서 내보내기') · 책갈피창 우클릭 '변환...'(하위 메뉴 없음, 여러 파일이면 일괄) · 썸네일 우클릭 '선택한 쪽 변환 ▸'.
- 실행은 `_run_merge_job`(배경 스레드 + 진행창 + 취소, 응답성 SOT §4). 문서·DB 는 그 스레드에서 `PageSource` 가 연다.

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(ConvertMixin, ...)`).
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import QMenu, QMessageBox

from viewer.i18n import tr


class ConvertMixin:
    def convert_format_menu(self, parent, title: str, on_pick) -> QMenu:
        """형식 하위 메뉴 — 다 만든 형식만(SOT §1). `on_pick(형식 키)`."""
        from viewer import convert
        m = QMenu(title, parent)
        for f in convert.ready_formats():
            a = m.addAction(tr(f.label))
            a.triggered.connect(lambda _=False, k=f.key: on_pick(k))
        return m

    def action_convert(self, files=None, fmt: str | None = None, pages=None) -> bool:
        """변환 창을 띄우고 고른 대로 변환한다. 변환했으면 True."""
        from viewer import convert
        from viewer.widgets.convert_dialog import ConvertDialog
        mv = self.main_view
        if not files:
            cur = mv.current_file() if mv else None
            files = [cur] if cur else []
        files = [str(f) for f in files if f and str(f).lower().endswith(".pdf") and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("변환"), tr("변환할 PDF 를 먼저 여세요."))
            return False
        self._lite_heavy_notice(tr("변환"))                 # 261021-1(응답성 SOT §4.7)
        if pages is not None:
            # 썸네일에서 — 저장 전 쪽 편집이 있으면 파일의 쪽 번호와 다르다(SOT §2.2)
            pt = self.page_thumbs
            doc = getattr(pt, "_doc", None)
            if doc is not None and str(doc.path) == files[0] and pt.is_page_dirty():
                QMessageBox.information(self, tr("변환"),
                                        tr("썸네일에서 바꾼 쪽 순서·삭제·끼운 쪽을 먼저 저장한 뒤 변환하세요."))
                return False
        n = 0
        try:
            import fitz
            from viewer import secure_store
            d = fitz.open(files[0])
            if d.needs_pass:
                d.authenticate(secure_store.recall_any(files[0]) or "")
            n = d.page_count
            d.close()
        except Exception:
            n = 0
        dlg = ConvertDialog(self, files=files, page_count=n, preset=fmt, picked_pages=pages)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return False
        key = dlg.format_key()
        sel = dlg.pages() if len(files) == 1 else None
        return self._run_convert(files, key, sel)

    def _run_convert(self, files, key, pages) -> bool:
        from viewer import convert
        from viewer.text_word import snapshot_fixes
        from viewer.twoup import MergeCancelled
        fixes = snapshot_fixes()
        forced_all = getattr(self, "_text_force_ocr", None) or set()
        results = []                                    # (원본, 결과|None, 알림|None)

        def _job(progress):
            for i, src in enumerate(files):
                name = Path(src).name
                forced = {int(p) for (f, p) in forced_all if str(f) == str(src)}

                def prog(done, total, label, _i=i, _name=name):
                    # 여러 파일이면 파일 단위로 나눈 칸 안에서 나아간다
                    total = max(1, int(total))
                    return progress(_i * 1000 + int(1000 * done / total), len(files) * 1000,
                                    f"{_name}  {label}".strip())
                try:
                    out = convert.run(src, key, pages, fixes=fixes, forced_pages=forced, progress=prog)
                    results.append((src, out, None))
                except convert.Cancelled:
                    raise MergeCancelled()
                except convert.NothingToWrite:
                    results.append((src, None, tr("표가 없습니다")))
                except Exception as e:                 # noqa: BLE001 — 한 파일 실패가 일괄을 멈추지 않게
                    results.append((src, None, str(e)))
        res = self._run_merge_job(_job, tr("변환"))
        if res.get("cancelled"):
            self.status.showMessage(tr("변환을 취소했습니다 — 만들던 파일은 지웠습니다."), 5000)
            return False
        ok = [r for r in results if r[1] is not None]
        bad = [r for r in results if r[1] is None]
        if not results and res.get("err"):
            QMessageBox.warning(self, tr("변환"), res.get("err"))
            return False
        if ok:
            self.status.showMessage(tr('변환: {path}').format(path=ok[0][1]), 8000)
        if len(files) == 1 and bad:
            QMessageBox.information(self, tr("변환"), tr('{name}: {why}').format(name=Path(bad[0][0]).name, why=bad[0][2]))
            return False
        msg = (tr('변환했습니다: {name}').format(name=Path(ok[0][1]).name) if len(files) == 1
               else tr('변환 {ok}개 · 실패 {bad}개').format(ok=len(ok), bad=len(bad))
               + ("".join("\n· %s — %s" % (Path(s).name, w) for s, _o, w in bad[:10])))
        if ok and QMessageBox.question(self, tr("변환"), msg + "\n\n" + tr("폴더를 열까요?")) == QMessageBox.StandardButton.Yes:
            self._reveal_converted(ok[0][1])
        elif not ok:
            QMessageBox.information(self, tr("변환"), msg)
        return bool(ok)

    def _reveal_converted(self, path) -> None:
        """탐색기로 결과를 짚어 연다 — 책갈피창 '파일 탐색기 열기' 와 같은 함수."""
        try:
            self.bookmark_tree._reveal_in_explorer(str(path))
        except Exception:
            try:
                os.startfile(str(Path(path).parent))      # noqa: S606 — 사용자가 고른 결과 폴더
            except Exception:
                pass
