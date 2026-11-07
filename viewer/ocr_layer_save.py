# -*- coding: utf-8 -*-
"""261107-30: [저장] 할 때 앱 OCR 을 PDF 글자층에 넣을지 묻는다 (텍스트 창 SOT §5.4.1).

사용자 지시: OCR 했는데 글자층으로 들어가지 않았으면 [저장] 때 넣을지 묻고, PDF 의 OCR 층과 앱 OCR 이 다르면 그것도.
흐름 — 배경에서 세기(`count_pages`) → 창(`OcrLayerSaveDialog`, 파일별 기억) → 배경에서 임시 파일(`text_apply.layer_tmp_for`)
→ 부르는 쪽(책갈피창 [저장])이 그 임시 파일을 바탕으로 저장(`_finalize_save` 한 번) → `LayerPlan.done(final)` 이 서명을 남긴다.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from viewer.i18n import tr

LAYER_DIFF_SIM = 0.9        # 기존 글자층과 앱 OCR 의 낱말 닮음도가 이 아래면 '다르다'(SOT §5.4.1 실측: 스캐너 층 ≤ 0.86, 우리 층 ≥ 0.97)
PREF_KEY = "ocr_layer_save"  # 설정 — {파일키: {"put": bool, "replace": bool}} ('이 파일은 다시 묻지 않음')
_TOK = re.compile(r"[0-9a-z]+|[가-힣]+")


def layer_similarity(a: str, b: str) -> float:
    """두 글의 낱말 닮음도(0~1) — 소문자 영숫자·한글 낱말의 다중집합 Dice. 한쪽이 비면 0."""
    A, B = Counter(_TOK.findall((a or "").lower())), Counter(_TOK.findall((b or "").lower()))
    if not A or not B:
        return 0.0
    return 2.0 * sum((A & B).values()) / (sum(A.values()) + sum(B.values()))


def ocr_sig(text: str) -> str:
    """그 쪽 OCR 글의 서명 — 우리가 쓴 층이 지금 OCR 과 같은 것에서 나왔는지 본다."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _writable(page) -> bool:
    """§5.4 안전 조건 중 세기 단계에서 볼 수 있는 것 — 돌리지 않았고 보이는 글자가 없다."""
    try:
        if int(page.rotation or 0) != 0:
            return False
        for span in page.get_texttrace():
            if span.get("type") != 3 and span.get("chars"):
                return False
    except Exception:
        return False
    return True


def count_pages(path, *, db_path=None, fix_store=None, cancelled=None) -> dict:
    """그 파일에서 글자층에 넣을 쪽(`missing`)·앱 OCR 과 다른 층의 쪽(`differs`)을 센다 — **배경에서** 부른다.

    앱 OCR 쪽(보류·저장본) 중 쓸 만한 글자층이 없고(`has_text_layer` 거짓)·돌리지 않았고·보이는 글자가 없는 쪽만 본다.
    층이 비었으면 missing, 있으면 우리가 쓴 서명이 지금 OCR 과 같으면 건너뛰고, 아니면 닮음도가 `LAYER_DIFF_SIM` 아래일 때 differs."""
    import fitz
    from viewer import text_extract2 as tx
    from viewer.study.study_store import StudyStore, file_key_for
    out = {"missing": [], "differs": [], "sigs": {}}
    st = StudyStore(db_path)
    try:
        texts = {int(p): t for p, t in st.iter_all_text(file_key_for(str(path))) if (t or "").strip()}
    finally:
        st.close()
    if not texts:
        return out
    try:
        doc = fitz.open(str(path))
    except Exception:
        return out
    try:
        if doc.needs_pass:
            return out
        for p in sorted(texts):
            if cancelled is not None and cancelled():
                break
            if not (0 <= p < doc.page_count) or tx.has_text_layer(doc, p):
                continue
            page = doc.load_page(p)
            if not _writable(page):
                continue
            sig = ocr_sig(texts[p])
            out["sigs"][p] = sig
            layer = page.get_text("text") or ""
            if not _TOK.search(layer.lower()):
                out["missing"].append(p)
            elif fix_store is not None and fix_store.layer_sig(str(path), p) == sig:
                continue
            elif layer_similarity(layer, texts[p]) < LAYER_DIFF_SIM:
                out["differs"].append(p)
    finally:
        doc.close()
    return out


class LayerPlan:
    """창에서 넣기로 한 결과 — `tmp` 는 글자층을 넣은 임시 PDF. 저장이 끝나면 `done(최종 경로)`, 아니면 `discard()`."""

    def __init__(self, path, tmp, pages, sigs, fix_store=None):
        self.path, self.tmp, self.pages, self.sigs, self._fs = str(path), str(tmp), list(pages), dict(sigs), fix_store

    def done(self, final) -> None:
        if self._fs is not None and self.pages:
            try:
                self._fs.set_layer_sigs(str(final), {p: self.sigs.get(p, "") for p in self.pages})
                self._fs.mark_applied(str(final), self.pages)
            except Exception:
                pass
        self.discard()

    def discard(self) -> None:
        try:
            Path(self.tmp).unlink()
        except Exception:
            pass


def _dialog_cls():
    from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox, QPushButton)

    class OcrLayerSaveDialog(QDialog):
        """'OCR N쪽을 PDF 글자층에 넣을까요?' — [넣고 저장]/[넣지 않고 저장]/[취소] + 다른 쪽 바꾸기 + 다시 묻지 않음."""

        def __init__(self, parent, name: str, n_missing: int, n_differs: int, replace: bool = True):
            super().__init__(parent)
            self.setWindowTitle(tr("저장 — OCR 글자층"))
            self.choice = "cancel"
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(name))
            if n_missing:
                lay.addWidget(QLabel(tr("OCR {n}쪽을 PDF 글자층에 넣을까요?").format(n=n_missing)))
            else:
                lay.addWidget(QLabel(tr("PDF 글자층에 넣을 OCR 쪽은 없습니다.")))
            self.cb_replace = QCheckBox(tr("앱 OCR 과 다른 글자층 {m}쪽도 바꾸기").format(m=n_differs))
            self.cb_replace.setChecked(bool(replace))
            self.cb_replace.setVisible(n_differs > 0)
            lay.addWidget(self.cb_replace)
            self.cb_remember = QCheckBox(tr("이 파일은 다시 묻지 않음"))
            lay.addWidget(self.cb_remember)
            bb = QDialogButtonBox()
            self.btn_put = QPushButton(tr("넣고 저장"))
            self.btn_skip = QPushButton(tr("넣지 않고 저장"))
            self.btn_cancel = QPushButton(tr("취소"))
            bb.addButton(self.btn_put, QDialogButtonBox.ButtonRole.AcceptRole)
            bb.addButton(self.btn_skip, QDialogButtonBox.ButtonRole.DestructiveRole)
            bb.addButton(self.btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
            self.btn_put.clicked.connect(lambda: self._pick("put"))
            self.btn_skip.clicked.connect(lambda: self._pick("skip"))
            self.btn_cancel.clicked.connect(lambda: self._pick("cancel"))
            self.btn_put.setDefault(True)
            lay.addWidget(bb)

        def _pick(self, c):
            self.choice = c
            (self.accept if c != "cancel" else self.reject)()

    return OcrLayerSaveDialog


def ask_for_save(parent, path, *, prefs: dict, save_prefs=None, run_bg, fix_store=None, db_path=None):
    """[저장] 진입에서 부른다(메인). 돌려주는 것: `"cancel"` · `None`(넣지 않음 — 종전 저장) · `LayerPlan`.

    `run_bg(fn, 안내)` 는 앱의 배경 파일 작업(`_file_op_bg` — 진행창, 실패면 예외를 돌려준다)."""
    from viewer.pathutil import norm_key
    got = {}
    err = run_bg(lambda: got.update(count_pages(path, db_path=db_path, fix_store=fix_store)),
                 tr("OCR 쪽 세는 중…"))
    if err is not None or not (got.get("missing") or got.get("differs")):
        return None
    missing, differs = got["missing"], got["differs"]
    key = norm_key(str(path))
    memo = (prefs.get(PREF_KEY) or {}).get(key)
    if isinstance(memo, dict):
        put, replace = bool(memo.get("put")), bool(memo.get("replace", True))
    else:
        dlg = _dialog_cls()(parent, Path(str(path)).name, len(missing), len(differs))
        dlg.exec()
        if dlg.choice == "cancel":
            return "cancel"
        put, replace = dlg.choice == "put", dlg.cb_replace.isChecked()
        if dlg.cb_remember.isChecked():
            prefs.setdefault(PREF_KEY, {})[key] = {"put": put, "replace": replace}
            if save_prefs is not None:
                try:
                    save_prefs()
                except Exception:
                    pass
    pages = sorted(set(missing) | (set(differs) if replace else set()))
    if not put or not pages:
        return None
    from viewer import text_apply as ta
    res = {}
    err = run_bg(lambda: res.update(zip(("tmp", "stats"), ta.layer_tmp_for(path, pages, db_path=db_path))),
                 tr("OCR 글자층 쓰는 중…"))
    if err is not None:
        raise err
    if not res.get("tmp"):
        return None
    st = res.get("stats") or {}
    return LayerPlan(path, res["tmp"], st.get("rewritten") or [], got.get("sigs") or {}, fix_store)
