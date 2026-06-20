"""특허 검색 뷰어 — KIPRIS Plus 항목별검색(getAdvancedSearch) (260618-44).

법령·고시/건설기준 패널과 동일한 사이드 패널 방식.
- 검색 기준: 자유검색·발명의명칭·초록(내용)·출원인·등록번호·출원번호.
- 결과(서지+초록)를 트리→선택→상세 표시(추가 호출 없음, 검색결과에 내용 포함).
- 즐겨찾기: 항목을 저장(법령과 동일하게 메인 윈도가 _kipo_favorites 관리).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import (QDesktopServices, QShortcut, QKeySequence, QTextDocument,
                         QAction)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QComboBox, QTreeWidget, QTreeWidgetItem, QTextBrowser, QWidget, QMenu,
)

from viewer.study.kipo_api import SEARCH_FIELDS, item_label, format_item
from viewer.widgets.toggle_splitter import ToggleSplitter
from viewer.widgets.icons import themed_icon

_SITE = "https://www.kipris.or.kr"
_ROLE_ROW = Qt.ItemDataRole.UserRole + 1


class _SearchWorker(QThread):
    done = pyqtSignal(list, int, list)         # items, total, debug

    def __init__(self, key, field, query):
        super().__init__()
        self._key, self._field, self._q = key, field, query

    def run(self):
        try:
            from viewer.study.kipo_api import search_advanced_debug
            items, total, dbg = search_advanced_debug(self._key, self._field, self._q)
            self.done.emit(items, total, dbg)
        except Exception as e:
            self.done.emit([], 0, [f"ERR {type(e).__name__}: {e}"])


class _DetailWorker(QThread):
    done = pyqtSignal(str, list)               # html, debug

    def __init__(self, key, appno):
        super().__init__()
        self._key, self._appno = key, appno

    def run(self):
        try:
            from viewer.study.kipo_api import read_detail_debug
            html, dbg = read_detail_debug(self._key, self._appno)
            self.done.emit(html, dbg)
        except Exception as e:
            self.done.emit("", [f"ERR {type(e).__name__}: {e}"])


class _PdfWorker(QThread):
    done = pyqtSignal(str, list)               # saved_path, debug

    def __init__(self, key, appno, dest_dir, name):
        super().__init__()
        self._k, self._a, self._d, self._n = key, appno, dest_dir, name

    def run(self):
        try:
            from viewer.study.kipo_api import download_fulltext_pdf_debug
            path, dbg = download_fulltext_pdf_debug(self._k, self._a, self._d, self._n)
            self.done.emit(path, dbg)
        except Exception as e:
            self.done.emit("", [f"ERR {type(e).__name__}: {e}"])


class KipoHostWindow(QWidget):
    closed = pyqtSignal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class KipoSearchPanel(QWidget):
    """특허(KIPRIS) 검색 패널."""
    closeRequested = pyqtSignal()
    fullscreenToggled = pyqtSignal()

    def __init__(self, key: str, win=None):
        super().__init__()
        self.setWindowTitle("특허 검색 (KIPRIS)")
        self._key = key
        self._win = win
        self._workers: list = []

        self.setMinimumWidth(360)
        try:
            _f = self.font(); _f.setFamily("Malgun Gothic"); self.setFont(_f)
        except Exception:
            pass
        _esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        _esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        _esc.activated.connect(self._on_escape)

        v = QVBoxLayout(self)

        # --- 제목줄 ---
        title_row = QHBoxLayout()
        title = QLabel("특허 검색")
        tf = title.font(); tf.setBold(True); tf.setPointSize(max(11, tf.pointSize() + 2))
        title.setFont(tf)
        title_row.addWidget(title)
        self.btn_fav = QPushButton("⭐ 즐겨찾기")
        self.btn_fav.setIcon(themed_icon("star"))
        self._fav_menu = QMenu(self)
        self._fav_menu.aboutToShow.connect(self._rebuild_fav_menu)
        self.btn_fav.setMenu(self._fav_menu)
        title_row.addWidget(self.btn_fav)
        title_row.addStretch(1)
        self.btn_full = QPushButton("⛶ 전체화면")
        self.btn_full.setToolTip("전체화면(별도 창) ↔ 내부화면(메인 오른쪽)")
        self.btn_full.clicked.connect(self.fullscreenToggled.emit)
        title_row.addWidget(self.btn_full)
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(34, 28)
        self.btn_close.setToolTip("특허 검색 닫기")
        self.btn_close.setStyleSheet(
            "QPushButton{color:#d11;font-weight:bold;border:1px solid #c0c0c0;"
            "border-radius:5px;background:#f2f2f2;}"
            "QPushButton:hover{background:#e81123;color:#fff;border-color:#e81123;}")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        title_row.addWidget(self.btn_close)
        v.addLayout(title_row)

        # --- 검색줄: 기준 + 검색어 + 검색 + 지구본 ---
        top = QHBoxLayout()
        self.cmb_mode = QComboBox()
        for fld, name in SEARCH_FIELDS:
            self.cmb_mode.addItem(name, fld)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("검색어 (예: 콘크리트 포장)")
        self.ed.returnPressed.connect(self._search)
        self.btn_search = QPushButton("검색")
        self.btn_search.clicked.connect(self._search)
        self.btn_detail = QPushButton("원문")
        self.btn_detail.setToolTip("선택 특허의 원문(상세·청구범위) 보기")
        self.btn_detail.clicked.connect(self._read_detail)
        self.btn_pdf = QPushButton("명세서PDF")
        self.btn_pdf.setToolTip("선택 특허의 전자명세서 PDF 를 받아 뷰어로 열기(지정 폴더에 저장)")
        self.btn_pdf.clicked.connect(self._open_fulltext)
        self.btn_globe = QPushButton()
        self.btn_globe.setIcon(themed_icon("globe"))
        self.btn_globe.setFixedWidth(36)
        self.btn_globe.setToolTip("KIPRIS 웹사이트 열기")
        self.btn_globe.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_SITE)))
        top.addWidget(self.cmb_mode)
        top.addWidget(self.ed, 1)
        top.addWidget(self.btn_search)
        top.addWidget(self.btn_detail)
        top.addWidget(self.btn_pdf)
        top.addWidget(self.btn_globe)
        v.addLayout(top)

        self.info = QLabel("검색 기준(명칭/초록/출원인/번호…)을 고르고 검색하세요. (KIPRIS accessKey 필요)")
        self.info.setStyleSheet("color:#888;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        # --- 본문: 좌(결과) / 우(상세) ---
        self.split = ToggleSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(8)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        self.tree.currentItemChanged.connect(lambda *_: self._on_select())
        self.tree.itemClicked.connect(lambda *_: self._on_select())
        self.split.addWidget(self.tree)
        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setPlaceholderText("특허 상세가 여기에 표시됩니다.")
        self.viewer.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.split.addWidget(self.viewer)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, True)
        self.split.setSizes([320, 680])
        v.addWidget(self.split, 1)

        # --- 찾기 바 ---
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(2, 2, 2, 2)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("내용에서 찾기")
        self.find_edit.returnPressed.connect(lambda: self._find(False))
        b_prev = QPushButton(); b_prev.setIcon(themed_icon("chevron_up"))
        b_prev.setFixedWidth(30); b_prev.clicked.connect(lambda: self._find(True))
        b_next = QPushButton(); b_next.setIcon(themed_icon("chevron_down"))
        b_next.setFixedWidth(30); b_next.clicked.connect(lambda: self._find(False))
        b_fclose = QPushButton(); b_fclose.setIcon(themed_icon("close"))
        b_fclose.setFixedWidth(30); b_fclose.clicked.connect(self._hide_find)
        fb.addWidget(self.find_edit, 1); fb.addWidget(b_prev); fb.addWidget(b_next); fb.addWidget(b_fclose)
        self.find_bar.setVisible(False)
        v.addWidget(self.find_bar)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._show_find)
        QShortcut(QKeySequence("Esc"), self.find_edit, activated=self._hide_find)

        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False); b.setDefault(False)
        self.ed.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)

    # ----- 레이아웃 -----
    def set_fullscreen(self, is_full: bool):
        self.btn_full.setText("▣ 내부화면" if is_full else "⛶ 전체화면")

    def _on_escape(self):
        if self.find_bar.isVisible():
            self.find_bar.hide()
        else:
            self.closeRequested.emit()

    # ----- 검색 -----
    def _search(self):
        if not (self._key or "").strip():
            self.info.setText("설정 → '인터넷 사전'의 특허(KIPRIS) 키를 먼저 입력하세요.")
            return
        q = (self.ed.text() or "").strip()
        if not q:
            self.info.setText("검색어를 입력하세요.")
            return
        self.tree.clear(); self.viewer.clear()
        self.info.setText("검색 중…")
        w = _SearchWorker(self._key, self.cmb_mode.currentData(), q)
        self._workers.append(w)
        w.done.connect(self._on_results)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _on_results(self, items, total, dbg):
        self.tree.clear()
        if not items:
            self.info.setText("검색 결과가 없습니다. " + (dbg[-1] if dbg else ""))
            return
        for it in items:
            node = QTreeWidgetItem([item_label(it)])
            node.setData(0, _ROLE_ROW, it)
            self.tree.addTopLevelItem(node)
        self.info.setText(f"{len(items)}건" + (f" / 전체 {total}" if total else ""))

    def _current_row(self):
        it = self.tree.currentItem()
        return it.data(0, _ROLE_ROW) if it is not None else None

    def _on_select(self):
        row = self._current_row()
        if isinstance(row, dict):
            self.viewer.setHtml(format_item(row))
            t = (row.get("inventionTitle") or "").strip()
            if t:
                self.info.setText(t)

    def _read_detail(self):
        row = self._current_row()
        if not isinstance(row, dict):
            self.info.setText("먼저 목록에서 특허를 선택하세요.")
            return
        appno = (row.get("applicationNumber") or "").strip()
        if not appno:
            self.info.setText("출원번호가 없어 원문을 불러올 수 없습니다.")
            return
        self.info.setText("원문(상세) 불러오는 중…")
        w = _DetailWorker(self._key, appno)
        self._workers.append(w)
        w.done.connect(self._on_detail)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _on_detail(self, html, dbg):
        if not html:
            self.info.setText("원문을 불러오지 못했습니다. " + (dbg[-1] if dbg else ""))
            return
        self.viewer.setHtml(html)
        self.info.setText("원문(상세) 표시")

    def _open_fulltext(self):
        """전자명세서(공개전문) PDF 를 지정 폴더에 저장하고 PolyPDF 뷰어로 연다."""
        row = self._current_row()
        if not isinstance(row, dict):
            self.info.setText("먼저 목록에서 특허를 선택하세요.")
            return
        appno = (row.get("applicationNumber") or "").strip()
        if not appno:
            self.info.setText("출원번호가 없어 명세서를 받을 수 없습니다.")
            return
        win = self._win
        dest = ""
        if win is not None and hasattr(win, "_patent_save_dir"):
            dest = win._patent_save_dir()
        if not dest:
            self.info.setText("특허 저장 폴더 설정이 필요합니다.")
            return
        self.info.setText("전자명세서 PDF 내려받는 중…")
        w = _PdfWorker(self._key, appno, dest, (row.get("inventionTitle") or "").strip())
        self._workers.append(w)
        w.done.connect(self._on_pdf)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _on_pdf(self, path, dbg):
        if not path:
            msg = dbg[-1] if dbg else "PDF 를 받지 못했습니다."
            self.info.setText(msg)
            return
        self.info.setText("PDF 저장·열기 완료")
        win = self._win
        if win is not None and hasattr(win, "open_pdf"):
            from pathlib import Path
            win.open_pdf(Path(path))

    # ----- 즐겨찾기 -----
    def _on_tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None or it.data(0, _ROLE_ROW) is None:
            return
        self.tree.setCurrentItem(it)
        menu = QMenu(self)
        a = QAction("⭐ 즐겨찾기에 추가", self)
        a.triggered.connect(self._add_favorite_current)
        menu.addAction(a)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_favorite_current(self):
        row = self._current_row()
        if not row:
            return
        win = self._win
        if win is not None and hasattr(win, "_add_kipo_favorite_entry"):
            win._add_kipo_favorite_entry(row)
            self.info.setText(f"즐겨찾기에 추가: {row.get('inventionTitle','')}")

    def _rebuild_fav_menu(self):
        self._fav_menu.clear()
        favs = list(getattr(self._win, "_kipo_favorites", []) or []) if self._win else []
        if not favs:
            a = self._fav_menu.addAction("(즐겨찾기 없음)")
            a.setEnabled(False)
        else:
            for f in favs:
                act = self._fav_menu.addAction(f.get("name") or f.get("appNo") or "특허")
                act.triggered.connect(lambda _=False, ff=f: self.show_saved(ff))
        self._fav_menu.addSeparator()
        mng = self._fav_menu.addAction("즐겨찾기 관리...")
        mng.triggered.connect(self._manage_favs)

    def _manage_favs(self):
        if self._win is not None and hasattr(self._win, "_manage_kipo_favorites"):
            self._win._manage_kipo_favorites()

    def show_saved(self, fav: dict):
        """즐겨찾기 클릭 — 좌측에 모든 즐겨찾기 표시 + 클릭 항목 선택→상세(저장된 항목)."""
        favs = list(getattr(self._win, "_kipo_favorites", []) or []) if self._win else []
        rows = [dict(f) for f in (favs or [fav])]
        self.tree.clear()
        target = None
        fav_key = str(fav.get("appNo") or fav.get("regNo") or fav.get("name") or "")
        for r in rows:
            it = r.get("item") if isinstance(r.get("item"), dict) else {
                "inventionTitle": r.get("name", ""),
                "applicationNumber": r.get("appNo", ""),
                "registerNumber": r.get("regNo", ""),
            }
            node = QTreeWidgetItem([r.get("name") or item_label(it)])
            node.setData(0, _ROLE_ROW, it)
            self.tree.addTopLevelItem(node)
            if str(r.get("appNo") or r.get("regNo") or r.get("name") or "") == fav_key:
                target = node
        self.info.setText(f"즐겨찾기 {len(rows)}건")
        if target is not None:
            self.tree.setCurrentItem(target)
            self.tree.scrollToItem(target)

    # ----- 찾기 -----
    def _show_find(self):
        self.find_bar.setVisible(True)
        self.find_edit.setFocus(); self.find_edit.selectAll()

    def _hide_find(self):
        self.find_bar.hide(); self.viewer.setFocus()

    def _find(self, backward: bool):
        q = self.find_edit.text()
        if not q:
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.viewer.find(q, flags):
            cur = self.viewer.textCursor()
            cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
            self.viewer.setTextCursor(cur)
            self.viewer.find(q, flags)
