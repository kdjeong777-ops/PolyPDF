# -*- coding: utf-8 -*-
"""본문 읽기 ▶ 를 누를 때 — 우리 글자층이 아니면 OCR 을 먼저 권한다 (261108-30, 영상·음성 SOT §1.11).

사용자 지시: "플레이 버튼을 눌렀는데, 글자층이 없거나, 우리 프로그램에서 한게 아니면, OCR을 우선하도록 안내하고,
OCR 실행 여부를 물어보도록 해."

쪽 판정(`page_kind`)은 텍스트 창 SOT §5.4 와 같은 기준이고 **배경에서만** 부른다(응답성 SOT §4.8·§4.9).
창·기억은 `ocr_layer_save`(텍스트 창 SOT §5.4.1)와 같은 꼴이다.
"""
from __future__ import annotations

from viewer.i18n import tr

PREF_KEY = "read_ocr_offer"     # 설정 — {파일키: "ocr" | "read"} ('이 파일은 다시 묻지 않음')
OURS_FONT = "krfix"             # 우리가 쓴 보이지 않는 층의 글꼴 자원 이름(텍스트 창 SOT §5.4.2 '기록 없는 층')

# 쪽 판정 결과 — 묻지 않는 것은 None
NONE = "none"                   # 글자층이 없다(스캔한 그림)
FOREIGN = "foreign"             # 다른 프로그램이 만든 보이지 않는 층


def _ours_page(page) -> bool:
    try:
        return any(str(f[4] or "").startswith(OURS_FONT) for f in page.get_fonts())
    except Exception:
        return False


def page_kind(doc, pno: int, *, app_ocr: bool, ours_doc: bool):
    """그 쪽을 OCR 하라고 권할지 — None(권하지 않음) · NONE · FOREIGN (SOT §1.11 표, 위에서부터 처음 맞는 줄)."""
    if app_ocr:
        return None
    from viewer.text_extract2 import has_text_layer
    if has_text_layer(doc, pno):
        return None
    try:
        page = doc.load_page(int(pno))
        words = any(ch.isalnum() for ch in (page.get_text("text") or ""))
    except Exception:
        return None
    if not words:
        return NONE
    if ours_doc or _ours_page(page):
        return None
    return FOREIGN


def judge(path, pages, *, db_path=None, cancelled=None) -> dict:
    """읽을 구간 `pages`(첫 쪽 = 시작 쪽)를 판정한다 — **배경에서** 부른다.

    시작 쪽이 권하지 않는 쪽이면 거기서 끝낸다(`start` None). 권하면 구간에서 OCR 할 쪽(`pages`)을 모두 센다."""
    out = {"start": None, "pages": []}
    pages = [int(p) for p in pages]
    if not pages:
        return out
    import fitz
    from viewer.study.study_store import StudyStore, file_key_for
    from viewer import text_apply as ta
    st = StudyStore(db_path)
    try:
        done = set(st.done_pages(file_key_for(str(path))))
    finally:
        st.close()
    try:
        doc = fitz.open(str(path))
    except Exception:
        return out
    try:
        if doc.needs_pass:
            return out                          # 암호 문서 — 판정하지 않는다(종전대로 읽는다)
        ours_doc = ta.read_text_layer_check(doc) is not None
        n = doc.page_count
        for i, p in enumerate(pages):
            if cancelled is not None and cancelled():
                break
            if not (0 <= p < n):
                continue
            k = page_kind(doc, p, app_ocr=p in done, ours_doc=ours_doc)
            if i == 0:
                if k is None:
                    return out                  # 시작 쪽은 그대로 읽는다 — 나머지는 보지 않는다
                out["start"] = k
            if k is not None:
                out["pages"].append(p)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out


def read_range(mode: str, start: int, page_count: int) -> list:
    """읽을 구간의 첫 바퀴(SOT §1.5) — 1회·연속은 지금 쪽, 전체·전체연속은 지금 쪽~끝."""
    start = max(0, min(int(start), max(1, int(page_count)) - 1))
    if mode in ("전체", "전체연속"):
        return list(range(start, max(1, int(page_count))))
    return [start]


def ask(parent, kind: str, n_pages: int):
    """창을 띄우고 ("ocr" | "read" | "cancel", 다시 묻지 않음) 을 돌려준다."""
    from PyQt6.QtWidgets import QMessageBox, QCheckBox
    box = QMessageBox(parent)
    box.setWindowTitle(tr("본문 읽기"))
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(tr("이 쪽에는 글자층이 없습니다(스캔한 그림).") if kind == NONE
                else tr("이 쪽의 글자층은 다른 프로그램이 만든 것입니다."))
    info = tr("OCR 을 먼저 하면 더 정확히 읽습니다 — OCR 할 쪽 {n}쪽(지금 쪽부터).").format(n=n_pages)
    if n_pages > 1:
        info += "\n" + tr("지금 쪽 OCR 이 끝나면 읽기 시작하고, 나머지 쪽은 읽는 동안 이어서 OCR 합니다.")
    box.setInformativeText(info)
    b_ocr = box.addButton(tr("OCR 하고 읽기"), QMessageBox.ButtonRole.AcceptRole)
    b_read = box.addButton(tr("그대로 읽기"), QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(b_ocr)
    cb = QCheckBox(tr("이 파일은 다시 묻지 않음"))
    box.setCheckBox(cb)
    box.exec()
    c = box.clickedButton()
    choice = "ocr" if c is b_ocr else ("read" if c is b_read else "cancel")
    return choice, bool(cb.isChecked()) and choice != "cancel"


def offer(mw, view, *, db_path=None) -> bool:
    """▶ 를 누를 때(메인). True = 여기서 맡았다(읽기를 지금 시작하지 않는다 — 취소했거나 OCR 뒤에 시작), False = 곧바로 읽는다."""
    from viewer.pathutil import norm_key
    f = view.current_file() if view is not None else None
    if not f or not str(f).lower().endswith(".pdf"):
        return False
    try:
        n = int(getattr(view._doc, "page_count", 0) or 0)
    except Exception:
        n = 0
    if n <= 0:
        return False
    start = view.current_page()
    pages = read_range(mw.read_aloud.mode, start, n)
    got = {}
    err = mw._file_op_bg(lambda: got.update(judge(f, pages, db_path=db_path)),
                         tr("읽을 쪽의 글자층 살피는 중…"), tr("본문 읽기"))
    if err is not None or not got.get("start"):
        return False
    todo = list(got.get("pages") or [start])
    key = norm_key(str(f))
    prefs = mw._prefs
    memo = (prefs.get(PREF_KEY) or {}).get(key)
    if memo in ("ocr", "read"):
        choice = memo
    else:
        choice, remember = ask(mw, got["start"], len(todo))
        if choice == "cancel":
            return True
        if remember:
            prefs.setdefault(PREF_KEY, {})[key] = choice
            try:
                mw._save_settings_now()
            except Exception:
                pass
    if choice == "read":
        return False
    return start_ocr_then_read(mw, view, f, todo, start)


def start_ocr_then_read(mw, view, path, pages, start) -> bool:
    """텍스트 창의 OCR 길(`_start_text_ocr`)로 읽고, **시작 쪽이 끝나면** 그 자리부터 읽는다."""
    opts = getattr(mw, "_ocr_opts", None) or {}
    lang = opts.get("lang") or mw._ocr_lang_for(path)
    mw._start_text_ocr(path, list(pages), lang, bool(opts.get("watermark", False)), True)
    w = getattr(mw, "_text_ocr_worker", None)
    if w is None:
        return True                             # 언어 자료 창에서 그만뒀다 — 읽지 않는다
    state = {"started": False, "stopped": False}
    order = [int(p) for p in pages]               # OCR 일꾼이 하는 차례
    ready = set()                                  # 결과가 온 쪽(건너뛴 쪽 포함)

    def _go():
        if state["started"] or state["stopped"]:
            return
        state["started"] = True
        ra = mw.read_aloud
        if ra.is_active():
            return
        if getattr(ra, "_view", None) is not view or view.current_file() is None:
            return
        try:
            if str(view.current_file()) != str(path):
                return                          # 그 사이 다른 파일을 열었다
        except Exception:
            return
        ra.start()
        # 261109-6(영상·음성 SOT §1.11 '아직 OCR 이 안 된 쪽'): 결과가 아직 없는 쪽에 닿으면 건너뛰지 않고 기다린다
        if ra.is_active() and not state["stopped"]:
            ra.wait_for_ocr([p for p in order if p not in ready and p != int(start)])

    def _reading():
        ra = mw.read_aloud
        return state["started"] and ra.is_active() and getattr(ra, "_view", None) is view

    def _on_done(page, words, dpi, token):
        p = int(page)
        # 일꾼은 차례로 한다 — 이 쪽 앞에서 결과 없이 지나간 쪽(글자층이 멀쩡해 건너뜀)도 이제 끝났다
        i = order.index(p) if p in order else -1
        for q in (order[:i + 1] if i >= 0 else [p]):
            if q not in ready:
                ready.add(q)
                if _reading():
                    mw.read_aloud.ocr_page_ready(q)
        if p == int(start):
            _go()

    def _on_cancel(*_a):
        if _reading():
            mw.read_aloud.ocr_wait_end()           # 남은 쪽은 있는 글로 — 기다려 매달리지 않는다
        state["stopped"] = True

    def _on_finished():
        if _reading():
            mw.read_aloud.ocr_wait_end()

    w.done.connect(_on_done)
    w.error.connect(_on_cancel)
    try:
        w.finished.connect(_on_finished)
    except Exception:
        pass
    try:
        prog = getattr(mw, "_ocr_progress", None)
        if prog is not None and len(pages) > 1:
            prog.canceled.connect(_on_cancel)
    except Exception:
        pass
    mw.status.showMessage(tr("OCR 이 끝나면 지금 쪽부터 읽습니다."), 6000)
    return True
