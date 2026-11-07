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
    """F12 — 다른 이름으로 저장(파일 탭과 같은 길, 포커스 책갈피창)."""
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
    """Alt+Shift+R — 파일 탐색기 열기(그 파일을 고른 채)."""
    ps = target_paths(mw)
    if not ps:
        _status(mw, tr("열 파일이 없습니다 — 파일을 먼저 여세요."))
        return
    mw.bookmark_tree._reveal_in_explorer(ps[0])


def new_folder(mw) -> None:
    """Ctrl+Shift+N — 새 폴더 만들기(포커스 책갈피창, 없으면 위 창 — 고른 폴더 아래, 없으면 연 폴더)."""
    kind, w = focus_kind(mw)
    bt = w if kind == "tree" else mw.bookmark_tree
    if not getattr(bt, "_root_dir", None):
        _status(mw, tr("먼저 폴더를 여세요."))
        return
    bt._ask_new_folder()


def info(mw) -> None:
    """Alt+Enter — 문서 정보(PDF) / 사진 정보(사진)."""
    if _photo_mode(mw):
        if _current_file(mw):
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
    """Ctrl+Enter — 지금 쪽 아래 흰 쪽(쪽 썸네일 '새 페이지 넣기' 와 같은 함수, 편집 모드)."""
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


def add_bookmark(mw) -> None:
    """Ctrl+B — 지금 쪽에 책갈피 추가(본문 우클릭과 같은 함수)."""
    cur, p0 = _cur_page(mw)
    if cur is None:
        _status(mw, tr("책갈피를 넣을 PDF 가 열려 있지 않습니다."))
        return
    mw._prompt_add_bookmark(cur, p0 + 1)


def hyperlink(mw) -> None:
    """Ctrl+K — 지금 쪽 하이퍼링크 등록(본문 우클릭과 같은 함수)."""
    cur, p0 = _cur_page(mw)
    if cur is None:
        _status(mw, tr("링크를 넣을 PDF 가 열려 있지 않습니다."))
        return
    mw._open_hyperlink_dialog(cur, p0)


def fav_add_file(mw) -> None:
    """Ctrl+D — 즐겨찾기에 추가(현재 파일, 즐겨찾기 탭 '현재 파일 추가' 와 같은 함수)."""
    mw._add_current_file_favorite()


def ocr_read(mw) -> None:
    """Ctrl+Alt+O — OCR 로 읽기(리본·우클릭과 같은 함수)."""
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
