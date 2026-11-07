# -*- coding: utf-8 -*-
"""261107-4(입력 SOT §3.2.3, 사용자 지시·결정): 흔한 프로그램 관례 키의 대상 — **포커스가 있는 곳**.

책갈피창(위·아래)에 포커스면 그 창의 고른 줄, 사진 썸네일 줄이면 고른 사진, 그 밖은 지금 본문의 파일·쪽·사진.
메뉴 항목과 **같은 함수**를 부른다 — 여기서 새 일을 만들지 않는다. 할 수 없으면 상태 줄로 까닭을 알리고 아무것도 바꾸지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

from viewer.i18n import tr


def _status(mw, msg: str, ms: int = 4000) -> None:
    try:
        mw.status.showMessage(msg, ms)
    except Exception:
        pass


def focus_kind(mw):
    """('tree', 책갈피창) · ('strip', 사진 썸네일 줄) · ('thumbs', 쪽 썸네일) · ('main', None)."""
    fw = QApplication.focusWidget()
    for bt in (getattr(mw, "bookmark_tree_right", None), getattr(mw, "bookmark_tree", None)):
        tw = getattr(bt, "tree", None)
        if tw is not None and fw is not None and bt.isVisible() and (fw is tw or tw.isAncestorOf(fw)):
            return "tree", bt
    strip = mw.__dict__.get("_photo_strip")
    if strip is not None and fw is not None and (fw is strip or strip.isAncestorOf(fw)):
        return "strip", strip
    pt = getattr(mw, "page_thumbs", None)
    if pt is not None and fw is not None and (fw is pt or pt.isAncestorOf(fw)):
        return "thumbs", pt
    return "main", None


def _photo_mode(mw) -> bool:
    return bool(getattr(mw, "_photo_mode", False))


def _tree_paths(bt) -> list:
    """책갈피창의 고른 줄 → 파일·폴더 경로(겹침 없이, 차례대로). 고른 것이 없으면 지금 줄."""
    tw = bt.tree
    items = list(tw.selectedItems()) or ([tw.currentItem()] if tw.currentItem() is not None else [])
    out = []
    for it in items:
        if bt._is_folder_node(it):
            p = it.toolTip(0)
        else:
            p = bt._file_path_of(it)
        if p and p not in out:
            out.append(p)
    return out


def _current_file(mw) -> str:
    mv = getattr(mw, "main_view", None)
    cur = mv.current_file() if mv is not None else None
    return str(cur) if cur else ""


def target_paths(mw) -> list:
    """키가 다룰 파일 경로 — 포커스 책갈피창의 고른 줄 · 사진 썸네일 줄의 고른 사진 · 지금 본문 파일."""
    kind, w = focus_kind(mw)
    if kind == "tree":
        ps = _tree_paths(w)
        if ps:
            return ps
    if kind == "strip":
        ps = [str(p) for p in (w.selected_paths() or [])]
        if ps:
            return ps
    cur = _current_file(mw)
    return [cur] if cur else []


# ── 키 하나에 함수 하나 ─────────────────────────────────────────────────────

def save_as(mw) -> None:
    """F12 — 다른 이름으로 저장(파일 탭과 같은 길). 261107-20: 우클릭 '저장 ▸ 다른 이름으로 저장' 과 같은 대상 —
    책갈피창에 포커스면 **그 창의 지금 줄 PDF**(우클릭한 줄이 지금 줄), 그 밖은 **지금 본문 PDF**. 그런 PDF 가 없으면 종전 길(선택 기준)."""
    kind, w = focus_kind(mw)
    if kind == "tree":
        it = w.tree.currentItem()
        f = w._file_path_of(it) if it is not None and not w._is_folder_node(it) else ""
        if f and str(f).lower().endswith(".pdf"):
            mw._action_save_as(bt=w, file_path=str(f))
            return
    elif not _photo_mode(mw):
        cur = _current_file(mw)
        if cur.lower().endswith(".pdf"):
            mw._action_save_as(bt=mw.bookmark_tree, file_path=cur)
            return
    mw._action_save_as()


def copy_path(mw) -> None:
    """Ctrl+Shift+C — 경로 복사(탐색기 '경로로 복사' 와 같게 — 여러 개면 줄마다 하나)."""
    ps = target_paths(mw)
    if not ps:
        _status(mw, tr("복사할 경로가 없습니다 — 파일을 먼저 여세요."))
        return
    if _photo_mode(mw):
        mw._photo_action("copy_path", ps)
        return
    QApplication.clipboard().setText("\n".join(ps))
    _status(mw, tr("경로를 복사했습니다."), 2500)


def reveal(mw) -> None:
    """Alt+Shift+R — 파일 탐색기 열기(그 파일을 고른 채). 책갈피창 폴더 줄이면 그 폴더를 연다(우클릭과 같다, 261107-26)."""
    kind, w = focus_kind(mw)
    if kind == "tree":
        it = w.tree.currentItem()
        if it is not None and w._is_folder_node(it) and it.toolTip(0):
            w._open_folder_in_explorer(Path(it.toolTip(0)))
            return
    ps = target_paths(mw)
    if not ps:
        _status(mw, tr("열 파일이 없습니다 — 파일을 먼저 여세요."))
        return
    mw.bookmark_tree._reveal_in_explorer(ps[0])


def new_folder(mw) -> None:
    """Ctrl+Shift+N — 새 폴더 만들기. 포커스 책갈피창이면 우클릭 '새 폴더 만들기' 와 같은 자리(261107-26 — 폴더 줄 = 그 안,
    파일·책갈피 줄 = 그 파일이 든 폴더), 아니면 위 창의 고른 폴더 아래(없으면 연 폴더)."""
    kind, w = focus_kind(mw)
    bt = w if kind == "tree" else mw.bookmark_tree
    if not getattr(bt, "_root_dir", None):
        _status(mw, tr("먼저 폴더를 여세요."))
        return
    if kind == "tree":
        base = bt.new_folder_base(bt.tree.currentItem())
        if base is not None:
            bt._new_folder_notice(base)
            return
    bt._ask_new_folder()


# ── 261107-26(입력 SOT §3.2.3 '창 키도 포커스 따라', 사용자 지시): 창 키를 그 창 우클릭 줄과 같은 대상에 ──────────
def _tree_row(w):
    """책갈피창 지금 줄 → (항목, 파일 경로, 사진 모드 줄인가). 폴더 줄·빈 곳이면 경로 ''."""
    it = w.tree.currentItem()
    if it is None or w._is_folder_node(it):
        return it, "", False
    return it, str(w._file_path_of(it) or ""), bool(w._photo_on())


def _photo_sel(mw, kind, w) -> list:
    """사진 모드에서 책갈피창·사진 썸네일 줄 포커스면 고른 사진들(없으면 [])."""
    if not _photo_mode(mw) or kind not in ("tree", "strip"):
        return []
    return [p for p in target_paths(mw) if mw._is_photo_path(p)]


def print_(mw) -> None:
    """Ctrl+P — 책갈피창 = 우클릭 맨 위 '인쇄'(고른 파일·책갈피 쪽 범위·폴더 아래 PDF), 사진 = 고른 사진,
    쪽 썸네일 = '인쇄 (N쪽)', 그 밖은 파일 탭 '인쇄'(종전 그대로)."""
    kind, w = focus_kind(mw)
    if kind == "tree":
        it = w.tree.currentItem()
        files, rng = w.print_targets(it, w._photo_on()) if it is not None else ([], None)
        if files:
            w.printFilesRequested.emit(files, rng)
            return
    elif kind == "strip":
        ps = _photo_sel(mw, kind, w)
        if ps:
            mw._photo_print(paths=ps)
            return
    elif kind == "thumbs" and not _photo_mode(mw):
        pages = w.selected_pages()
        if pages:
            mw._on_thumb_print_pages(pages)
            return
    a = getattr(mw, "_sc_act_print", None)
    if a is not None and a.isEnabled():
        a.trigger()


def present(mw) -> None:
    """F5 — 발표보기. 책갈피창 PDF 줄이면 그 파일을, 사진 줄·사진 썸네일 줄이면 그 사진을 연 뒤(우클릭과 같다)."""
    kind, w = focus_kind(mw)
    ps = _photo_sel(mw, kind, w)
    if ps:
        mw._photo_open_then(ps[0], mw._open_presentation)
        return
    if kind == "tree":
        _it, f, pm = _tree_row(w)
        if f and not pm and f.lower().endswith(".pdf"):
            w._file_action("present", [f])
            return
    mw._open_presentation()


def rotate(mw, delta: int) -> None:
    """Ctrl+[ · Ctrl+] — 쪽 썸네일 포커스(편집 모드)면 고른 쪽, 사진 줄이면 고른 사진, 그 밖은 지금 쪽·사진(종전)."""
    kind, w = focus_kind(mw)
    ps = _photo_sel(mw, kind, w)
    if ps:
        for p in ps:
            mw._photo_rotate(delta, path=p)
        return
    if kind == "thumbs" and not _photo_mode(mw) and getattr(w, "_edit_mode", False):
        pages = w.selected_pages()
        if pages:
            w.rotatePages.emit(pages, int(delta))
            return
    mw._rotate_current(delta)


def _thumb_own_page(w):
    """쪽 썸네일의 지금(고른) 썸네일 → 이 문서 쪽 번호(붙여넣은 쪽·없으면 None)."""
    from PyQt6.QtCore import Qt
    it = w.list.currentItem()
    if it is None or not it.isSelected():
        sel = w.list.selectedItems()
        it = sel[-1] if sel else it
    v = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
    return v if isinstance(v, int) else None


def info(mw) -> None:
    """Alt+Enter — 문서 정보(PDF) / 사진 정보(사진 — 책갈피창·사진 썸네일 줄이면 고른 사진, 261107-26)."""
    if _photo_mode(mw):
        kind, w = focus_kind(mw)
        ps = _photo_sel(mw, kind, w)
        if ps:
            mw._photo_info_for(ps[0])
        elif _current_file(mw):
            mw._photo_info_dialog()
        return
    fn = getattr(mw, "show_doc_info", None)
    if fn is None or not _current_file(mw):
        _status(mw, tr("정보를 볼 파일이 없습니다 — 파일을 먼저 여세요."))
        return
    fn()


def crop(mw) -> None:
    """Ctrl+Shift+X — 크롭 창(사진은 사진 크롭, PDF 는 쪽 썸네일에 포커스면 고른 쪽, 아니면 지금 쪽)."""
    if _photo_mode(mw):
        ps = [p for p in target_paths(mw) if mw._is_photo_path(p)]
        if ps:
            mw._photo_action("crop", ps[:1])
        return
    kind, w = focus_kind(mw)
    if kind == "thumbs":
        pages = sorted(set(w.selected_pages()))           # 이 문서 쪽 번호(붙여넣은 쪽은 빠진다 — 쪽 메뉴 '크롭' 과 같게)
        if pages:
            mw._open_crop_dialog(pages=pages)
            return
    mw._open_crop_dialog(view=mw.main_view)


def _cur_page(mw):
    """(지금 파일, 0부터 쪽) — PDF 가 없으면 (None, None)."""
    if _photo_mode(mw):
        return None, None
    cur = _current_file(mw)
    mv = getattr(mw, "main_view", None)
    if not cur or mv is None or not cur.lower().endswith(".pdf"):
        return None, None
    try:
        return cur, int(mv.current_page())
    except Exception:
        return cur, 0


def new_page(mw) -> None:
    """Ctrl+Enter — 지금 쪽 아래 흰 쪽(쪽 썸네일 '새 페이지 넣기' 와 같은 함수, 편집 모드).
    쪽 썸네일 포커스면 그 메뉴 줄과 같은 자리 — 누른(고른) 썸네일 뒤(`_img_ref_row`, 261107-26)."""
    kind, w = focus_kind(mw)
    if kind == "thumbs" and not _photo_mode(mw) and getattr(w, "_doc", None) is not None:
        w.addBlankPageRequested.emit(w._img_ref_row(None))
        return
    cur, p0 = _cur_page(mw)
    if cur is None:
        _status(mw, tr("쪽을 넣을 PDF 가 열려 있지 않습니다."))
        return
    row = p0
    pt = getattr(mw, "page_thumbs", None)              # 썸네일 줄 번호(붙여넣은 쪽이 끼면 쪽 번호와 다르다)
    lst = getattr(pt, "list", None)
    if lst is not None:
        from PyQt6.QtCore import Qt
        for i in range(lst.count()):
            if lst.item(i).data(Qt.ItemDataRole.UserRole) == p0:
                row = i
                break
    mw._on_add_blank_page(row)


def _thumbs_page_signal(mw, signal_name) -> bool:
    """쪽 썸네일 포커스면 고른 썸네일의 쪽으로 그 메뉴 줄과 같은 신호(261107-26). 처리했으면 True(붙여넣은 쪽은 아무것도 안 함)."""
    kind, w = focus_kind(mw)
    if kind != "thumbs" or _photo_mode(mw) or getattr(w, "_doc", None) is None:
        return False
    if not getattr(w, "_edit_mode", False):
        return False                                   # 그 메뉴 줄은 편집 모드에서만 — 그 밖은 종전(지금 쪽)
    pg = _thumb_own_page(w)
    if pg is not None:
        getattr(w, signal_name).emit(int(pg))
    else:
        _status(mw, tr("붙여넣은 쪽은 아직 파일에 없습니다.\n💾 '저장' 한 뒤에 다시 해 주세요.").replace("\n", " "))   # 썸네일 알림과 같은 글
    return True


def add_bookmark(mw) -> None:
    """Ctrl+B — 지금 쪽에 책갈피 추가(본문 우클릭과 같은 함수). 쪽 썸네일 포커스면 고른 썸네일의 쪽(261107-26)."""
    if _thumbs_page_signal(mw, "addBookmarkAtPage"):
        return
    cur, p0 = _cur_page(mw)
    if cur is None:
        _status(mw, tr("책갈피를 넣을 PDF 가 열려 있지 않습니다."))
        return
    mw._prompt_add_bookmark(cur, p0 + 1)


def hyperlink(mw) -> None:
    """Ctrl+K — 지금 쪽 하이퍼링크 등록(본문 우클릭과 같은 함수). 쪽 썸네일 포커스면 고른 썸네일의 쪽(261107-26)."""
    if _thumbs_page_signal(mw, "registerHyperlinkAtPage"):
        return
    cur, p0 = _cur_page(mw)
    if cur is None:
        _status(mw, tr("링크를 넣을 PDF 가 열려 있지 않습니다."))
        return
    mw._open_hyperlink_dialog(cur, p0)


def fav_add_file(mw) -> None:
    """Ctrl+D — 즐겨찾기에 추가(현재 파일, 즐겨찾기 탭 '현재 파일 추가' 와 같은 함수).
    책갈피창 파일 줄이면 그 파일, 사진 썸네일 줄이면 고른 사진(우클릭 '현재 파일을 즐겨찾기에 추가' 와 같다, 261107-26)."""
    kind, w = focus_kind(mw)
    if kind == "tree":
        it = w.tree.currentItem()
        if it is not None and w._is_file_node(it) and w._file_path_of(it):
            w.addFileFavoriteRequested.emit(str(w._file_path_of(it)))
            return
    ps = _photo_sel(mw, kind, w) if kind == "strip" else []
    if len(ps) == 1:
        mw._add_file_favorite(ps[0])
        return
    mw._add_current_file_favorite()


def ocr_read(mw) -> None:
    """Ctrl+Alt+O — OCR 로 읽기(리본·우클릭과 같은 함수). 261107-26: 책갈피창·썸네일 포커스면 그 우클릭 줄과 같은 범위 —
    PDF 파일 줄 = 그 파일 전체, 책갈피 줄 = 그 쪽 범위, 사진 = 고른 사진(여러 장이면 차례로), 쪽 썸네일 = 고른 쪽 범위."""
    kind, w = focus_kind(mw)
    ps = _photo_sel(mw, kind, w)
    if len(ps) > 1:
        mw._photo_ocr_many(ps)
        return
    if ps:
        mw._photo_open_then(ps[0], mw._photo_ocr_start)
        return
    if kind == "tree" and not w._photo_on():
        it, f, _pm = _tree_row(w)
        if f and f.lower().endswith(".pdf"):
            rng = None
            if not w._is_file_node(it) and it.data(0, w.DATA_PAGE) is not None:
                rng = w._bookmark_page_range(it)
            w._file_action("ocr_read", [f], rng)
            return
    if kind == "thumbs" and not _photo_mode(mw):
        pages = w.selected_pages()
        if pages:
            w.ocrPagesRequested.emit(list(pages))
            return
    mw._action_ocr_read()


def rename(mw) -> bool:
    """F2 — 책갈피창에 더해 사진 썸네일 줄·사진 본문에서도(지금 사진의 책갈피창 줄 이름 변경). 처리했으면 True."""
    if not _photo_mode(mw):
        return False
    kind, w = focus_kind(mw)
    if kind not in ("strip", "main"):
        return False
    ps = target_paths(mw)
    if not ps:
        return False
    bt = mw.bookmark_tree
    node = bt._file_node_for_path(str(Path(ps[0])))
    if node is None:
        return False
    bt._edit_item(node)
    return True
