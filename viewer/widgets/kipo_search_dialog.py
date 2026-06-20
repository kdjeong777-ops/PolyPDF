"""특허청(KIPO) 특허 등록정보 뷰어 — patent.go.kr 웹서비스 (260618-43).

법령·고시/건설기준 패널과 동일한 사이드 패널 방식.
- 검색 기준: 등록번호(rgstNo) | 출원인코드(apAgtCd).
  · 등록번호 → 등록 기본정보 바로 표시.
  · 출원인코드 → 등록번호 목록 → 선택 → 기본정보.
- 즐겨찾기: 법령과 동일(메인 윈도가 _kipo_favorites 관리).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import (QDesktopServices, QShortcut, QKeySequence, QTextDocument,
                         QAction)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QComboBox, QTreeWidget, QTreeWidgetItem, QTextBrowser, QWidget, QMenu,
)

from viewer.widgets.toggle_splitter import ToggleSplitter
from viewer.widgets.icons import themed_icon

_SITE = "https://www.patent.go.kr"
_ROLE_ROW = Qt.ItemDataRole.UserRole + 1


class _ListWorker(QThread):
    done = pyqtSignal(list, list)              # rows, debug

    def __init__(self, key, apagtcd):
        super().__init__()
        self._key, self._ap = key, apagtcd

    def run(self):
        try:
            from viewer.study.kipo_api import list_reg_numbers_debug
            rows, dbg = list_reg_numbers_debug(self._key, self._ap)
            self.done.emit(rows, dbg)
        except Exception as e:
            self.done.emit([], [f"ERR {type(e).__name__}: {e}"])


class _BasicWorker(QThread):
    done = pyqtSignal(str, list, dict)         # html, debug, meta

    def __init__(self, key, rgstno):
        super().__init__()
        self._key, self._rgst = key, rgstno

    def run(self):
        try:
            from viewer.study.kipo_api import read_basic_info_debug
            html, dbg, meta = read_basic_info_debug(self._key, self._rgst)
            self.done.emit(html, dbg, meta)
        except Exception as e:
            self.done.emit("", [f"ERR {type(e).__name__}: {e}"], {})


class KipoHostWindow(QWidget):
    """전체화면 팝아웃용 호스트 창(닫으면 closed → 내부화면 복귀)."""
    closed = pyqtSignal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class KipoSearchPanel(QWidget):
    """특허(KIPO) 등록정보 패널. 메인 오른쪽 2단 임베드 / 전체화면 팝아웃."""
    closeRequested = pyqtSignal()
    fullscreenToggled = pyqtSignal()

    def __init__(self, key: str, win=None):
        super().__init__()
        self.setWindowTitle("특허 등록정보 (KIPO)")
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
        title = QLabel("특허 등록정보")
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
        self.btn_close.setToolTip("특허 등록정보 닫기")
        self.btn_close.setStyleSheet(
            "QPushButton{color:#d11;font-weight:bold;border:1px solid #c0c0c0;"
            "border-radius:5px;background:#f2f2f2;}"
            "QPushButton:hover{background:#e81123;color:#fff;border-color:#e81123;}")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        title_row.addWidget(self.btn_close)
        v.addLayout(title_row)

        # --- 검색줄: 기준(등록번호/출원인코드) + 값 + 검색 + 지구본 ---
        top = QHBoxLayout()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("등록번호", "rgst")
        self.cmb_mode.addItem("출원인코드", "apagt")
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("등록번호 (예: 10-1234567)")
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        self.ed.returnPressed.connect(self._search)
        self.btn_search = QPushButton("검색")
        self.btn_search.clicked.connect(self._search)
        self.btn_globe = QPushButton()
        self.btn_globe.setIcon(themed_icon("globe"))
        self.btn_globe.setFixedWidth(36)
        self.btn_globe.setToolTip("특허로(patent.go.kr) 열기")
        self.btn_globe.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_SITE)))
        top.addWidget(self.cmb_mode)
        top.addWidget(self.ed, 1)
        top.addWidget(self.btn_search)
        top.addWidget(self.btn_globe)
        v.addLayout(top)

        self.info = QLabel("등록번호 또는 출원인코드로 검색하세요. (KIPO signKey 필요)")
        self.info.setStyleSheet("color:#888;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        # --- 본문: 좌(결과 트리) / 우(기본정보) ---
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
        self.viewer.setPlaceholderText("등록 기본정보가 여기에 표시됩니다.")
        self.viewer.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.split.addWidget(self.viewer)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, True)
        self.split.setSizes([300, 700])
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

    def _on_mode(self):
        self.ed.setPlaceholderText("등록번호 (예: 10-1234567)" if self.cmb_mode.currentData() == "rgst"
                                   else "출원인코드 (예: 120190012345)")

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
            self.info.setText("설정 → '인터넷 사전'의 KIPO signKey 를 먼저 입력하세요.")
            return
        val = (self.ed.text() or "").strip()
        if not val:
            self.info.setText("검색어를 입력하세요.")
            return
        self.tree.clear(); self.viewer.clear()
        if self.cmb_mode.currentData() == "rgst":
            self.info.setText("등록정보 불러오는 중…")
            it = QTreeWidgetItem([f"등록 {val}"])
            it.setData(0, _ROLE_ROW, {"rgstNo": val, "name": ""})
            self.tree.addTopLevelItem(it)
            self.tree.setCurrentItem(it)        # → _on_select → 기본정보 로드
        else:
            self.info.setText("등록번호 목록 불러오는 중…")
            w = _ListWorker(self._key, val)
            self._workers.append(w)
            w.done.connect(self._on_list)
            w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
            w.start()

    def _on_list(self, rows, dbg):
        self.tree.clear()
        if not rows:
            self.info.setText("결과가 없습니다. " + (dbg[-1] if dbg else ""))
            return
        for r in rows:
            label = (f"{r['name']} ({r['rgstNo']})" if r.get("name")
                     else f"등록 {r['rgstNo']}")
            it = QTreeWidgetItem([label])
            it.setData(0, _ROLE_ROW, r)
            self.tree.addTopLevelItem(it)
        self.info.setText(f"{len(rows)}건")

    def _current_row(self):
        it = self.tree.currentItem()
        return it.data(0, _ROLE_ROW) if it is not None else None

    def _on_select(self):
        row = self._current_row()
        if isinstance(row, dict) and row.get("rgstNo"):
            self.info.setText("등록정보 불러오는 중…")
            w = _BasicWorker(self._key, row["rgstNo"])
            self._workers.append(w)
            w.done.connect(self._on_basic)
            w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
            w.start()

    def _on_basic(self, html, dbg, meta):
        if not html:
            self.info.setText("표시할 정보가 없습니다. " + (dbg[-1] if dbg else ""))
            return
        self.viewer.setHtml(html)
        name = meta.get("name") or ""
        self.info.setText(name if name else (dbg[-1] if dbg else ""))
        # 결과 항목 라벨에 명칭 반영
        it = self.tree.currentItem()
        if it is not None and name and meta.get("rgstNo"):
            it.setText(0, f"{name} ({meta['rgstNo']})")
            row = it.data(0, _ROLE_ROW) or {}
            row["name"] = name
            it.setData(0, _ROLE_ROW, row)

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
            self.info.setText(f"즐겨찾기에 추가: {row.get('name') or row.get('rgstNo')}")

    def _rebuild_fav_menu(self):
        self._fav_menu.clear()
        favs = list(getattr(self._win, "_kipo_favorites", []) or []) if self._win else []
        if not favs:
            a = self._fav_menu.addAction("(즐겨찾기 없음)")
            a.setEnabled(False)
        else:
            for f in favs:
                label = f.get("name") or f"등록 {f.get('rgstNo','?')}"
                act = self._fav_menu.addAction(label)
                act.triggered.connect(lambda _=False, ff=f: self.show_saved(ff))
        self._fav_menu.addSeparator()
        mng = self._fav_menu.addAction("즐겨찾기 관리...")
        mng.triggered.connect(self._manage_favs)

    def _manage_favs(self):
        if self._win is not None and hasattr(self._win, "_manage_kipo_favorites"):
            self._win._manage_kipo_favorites()

    def show_saved(self, fav: dict):
        """즐겨찾기 클릭 — 좌측 트리에 모든 즐겨찾기 표시 + 클릭 항목 선택→기본정보."""
        favs = list(getattr(self._win, "_kipo_favorites", []) or []) if self._win else []
        rows = [dict(f) for f in (favs or [fav])]
        self.tree.clear()
        for r in rows:
            label = r.get("name") or f"등록 {r.get('rgstNo','?')}"
            it = QTreeWidgetItem([label])
            it.setData(0, _ROLE_ROW, {"rgstNo": r.get("rgstNo", ""), "name": r.get("name", "")})
            self.tree.addTopLevelItem(it)
        self.info.setText(f"즐겨찾기 {len(rows)}건")
        key = str(fav.get("rgstNo") or "")
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            r = it.data(0, _ROLE_ROW) or {}
            if str(r.get("rgstNo")) == key:
                self.tree.setCurrentItem(it)
                self.tree.scrollToItem(it)
                break

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
