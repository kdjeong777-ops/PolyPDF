"""건설기준(KCSC) 검색·본문 뷰어 — 국가건설기준센터 OPEN API (260618-37/38/39).

법령·고시 패널(law_search_dialog)과 동일한 사이드 패널 방식.
- 카탈로그(CodeList)를 한 번 받아 캐시 → 코드체계(전체/설계기준/표준시방서/전문시방서…)
  드롭다운(데이터 기반) + 이름·코드 검색을 **클라이언트에서** 필터.
- 본문: 결과 선택 → CodeViewer → 우측 표시(절 목록은 결과 항목의 자식).
- 즐겨찾기: 법령과 동일(메인 윈도가 _kcsc_favorites 관리).
"""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import (QDesktopServices, QShortcut, QKeySequence, QTextDocument,
                         QAction)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QComboBox, QTreeWidget, QTreeWidgetItem, QTextBrowser, QWidget, QMenu,
)

from viewer.widgets.toggle_splitter import ToggleSplitter
from viewer.widgets.icons import themed_icon

_SITE = "https://www.kcsc.re.kr"
_ROLE_ROW = Qt.ItemDataRole.UserRole + 1       # 결과(row dict)
_ROLE_ANCHOR = Qt.ItemDataRole.UserRole + 2    # 절 앵커

# 260621-62: 본문 속 코드 참조(예: 'KCS 44 50 10', 'KDS 11 40 10')를 하이퍼링크로.
#   태그(<...>)는 그대로 두고, 태그 밖 텍스트의 KDS/KCS + 숫자(공백 포함)만 매칭.
#   숫자에서 공백 제거 후 6자리면 코드로 인정 → kcsc://{KDS|KCS}/{코드}
_CODE_RE = re.compile(r'(?P<tag><[^>]+>)|(?P<pfx>\b(?:KDS|KCS))[ \t]*(?P<num>(?:\d[ \t]*){4,8})')


def linkify_codes(html: str) -> str:
    def _repl(m):
        if m.group('tag'):
            return m.group('tag')
        pfx = m.group('pfx')
        digits = re.sub(r'\D', '', m.group('num') or "")
        if len(digits) != 6:
            return m.group(0)
        text = m.group(0).rstrip()
        return (f'<a href="kcsc://{pfx}/{digits}" '
                f'style="color:#1456c4;text-decoration:underline;">{text}</a>')
    try:
        return _CODE_RE.sub(_repl, html or "")
    except Exception:
        return html or ""


class _CatalogWorker(QThread):
    done = pyqtSignal(list, list)              # rows, debug

    def __init__(self, key):
        super().__init__()
        self._key = key

    def run(self):
        try:
            from viewer.study.kcsc_api import fetch_catalog_debug
            rows, dbg = fetch_catalog_debug(self._key)
            self.done.emit(rows, dbg)
        except Exception as e:
            self.done.emit([], [f"ERR {type(e).__name__}: {e}"])


class _ContentWorker(QThread):
    done = pyqtSignal(str, list, list, dict)   # html, debug, arts, meta

    def __init__(self, key, ctype, code):
        super().__init__()
        self._key, self._ctype, self._code = key, ctype, code

    def run(self):
        try:
            from viewer.study.kcsc_api import fetch_content_debug
            html, dbg, arts, meta = fetch_content_debug(self._key, self._ctype, self._code)
            self.done.emit(html, dbg, arts, meta)
        except Exception as e:
            self.done.emit("", [f"ERR {type(e).__name__}: {e}"], [], {})


class KcscHostWindow(QWidget):
    """전체화면 팝아웃용 호스트 창(닫으면 closed → 내부화면 복귀)."""
    closed = pyqtSignal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class KcscSearchPanel(QWidget):
    """건설기준(KCSC) 검색+본문 패널. 메인 오른쪽 2단 임베드 / 전체화면 팝아웃."""
    closeRequested = pyqtSignal()
    fullscreenToggled = pyqtSignal()

    def __init__(self, key: str, win=None):
        super().__init__()
        self.setWindowTitle("건설기준(KCSC) 검색·본문")
        self._key = key
        self._win = win
        self._workers: list = []
        self._cur_item = None
        self._all_rows = None         # 카탈로그 캐시(전체)
        self._hist: list = []         # 260621-62: 본 기준 히스토리 [(ctype, code, item)]
        self._hist_idx = -1

        self.setMinimumWidth(360)
        try:
            _f = self.font(); _f.setFamily("Malgun Gothic"); self.setFont(_f)
        except Exception:
            pass
        _esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        _esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        _esc.activated.connect(self._on_escape)

        v = QVBoxLayout(self)

        # --- 제목줄: 건설기준(KCSC) + 즐겨찾기 + 전체화면 + 닫기 ---
        title_row = QHBoxLayout()
        title = QLabel("건설기준(KCSC)")
        tf = title.font(); tf.setBold(True); tf.setPointSize(max(11, tf.pointSize() + 2))
        title.setFont(tf)
        title_row.addWidget(title)
        # 260621-62: 뒤로/앞으로(본문 코드 링크·항목 이동 히스토리)
        self.btn_back = QPushButton("◀")
        self.btn_back.setFixedWidth(30); self.btn_back.setToolTip("뒤로 (이전 본 기준)")
        self.btn_back.clicked.connect(self._nav_back)
        self.btn_fwd = QPushButton("▶")
        self.btn_fwd.setFixedWidth(30); self.btn_fwd.setToolTip("앞으로 (다음 본 기준)")
        self.btn_fwd.clicked.connect(self._nav_fwd)
        self.btn_back.setEnabled(False); self.btn_fwd.setEnabled(False)
        title_row.addWidget(self.btn_back); title_row.addWidget(self.btn_fwd)
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
        self.btn_close.setToolTip("건설기준 닫기")
        self.btn_close.setStyleSheet(
            "QPushButton{color:#d11;font-weight:bold;border:1px solid #c0c0c0;"
            "border-radius:5px;background:#f2f2f2;}"
            "QPushButton:hover{background:#e81123;color:#fff;border-color:#e81123;}")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        title_row.addWidget(self.btn_close)
        v.addLayout(title_row)

        # --- 검색줄: 코드체계(전체+데이터기반) + 검색어 + 검색 + 지구본 ---
        top = QHBoxLayout()
        self.cmb_type = QComboBox()
        self.cmb_type.addItem("전체 (전체에서 찾기)", "")     # 제일 위 = 전체
        self.cmb_type.currentIndexChanged.connect(lambda *_: self._apply_filter())
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("이름 또는 코드 검색 (예: 콘크리트, 114010)")
        self.ed.returnPressed.connect(self._search)
        self.btn_search = QPushButton("검색")
        self.btn_search.clicked.connect(self._search)
        self.btn_globe = QPushButton()
        self.btn_globe.setIcon(themed_icon("globe"))
        self.btn_globe.setFixedWidth(36)
        self.btn_globe.setToolTip("국가건설기준센터 웹사이트 열기")
        self.btn_globe.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_SITE)))
        top.addWidget(self.cmb_type)
        top.addWidget(self.ed, 1)
        top.addWidget(self.btn_search)
        top.addWidget(self.btn_globe)
        v.addLayout(top)

        self.info = QLabel("코드체계를 고르고 이름/코드로 검색하세요. (전체=모든 체계에서 찾기)")
        self.info.setStyleSheet("color:#888;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        # --- 본문: 좌(결과·절 트리) / 우(본문) ---
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
        self.viewer.setOpenLinks(False)            # 260621-62: 코드 링크/외부 링크 직접 처리
        self.viewer.anchorClicked.connect(self._on_anchor_left)
        self.viewer.setPlaceholderText("본문이 여기에 표시됩니다.")
        self.viewer.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.split.addWidget(self.viewer)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, True)
        self.split.setSizes([320, 680])
        # 260621-63: 중앙 영역을 교체 가능한 컨테이너로(내부=단일 split / 전체화면=2단)
        self._center = QWidget()
        self._center_lay = QVBoxLayout(self._center)
        self._center_lay.setContentsMargins(0, 0, 0, 0)
        self._center_lay.addWidget(self.split)
        v.addWidget(self._center, 1)
        self._is_full = False
        self._fs_split = None
        self.tree2 = None
        self.viewer2 = None

        # --- 찾기 바(Ctrl+F) ---
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
        """260621-63: 전체화면=2단(좌측 세로 상/하 책갈피 + 본문 좌/우), 내부=단일 split."""
        is_full = bool(is_full)
        self.btn_full.setText("▣ 내부화면" if is_full else "⛶ 전체화면")
        if is_full == self._is_full:
            return
        self._is_full = is_full
        if is_full:
            self._build_fs()
            self._fs_left.insertWidget(0, self.tree)       # 상단 책갈피
            self._fs_right.insertWidget(0, self.viewer)    # 좌측 본문
            self._center_lay.removeWidget(self.split)
            self.split.setParent(None)
            self._center_lay.addWidget(self._fs_split)
            self._fs_split.show()
            self._fs_left.setSizes([400, 400])
            self._fs_right.setSizes([560, 560])
            self._fs_split.setSizes([320, 1080])
        else:
            self.split.insertWidget(0, self.tree)
            self.split.insertWidget(1, self.viewer)
            if self._fs_split is not None:
                self._center_lay.removeWidget(self._fs_split)
                self._fs_split.setParent(None)
            self._center_lay.addWidget(self.split)
            self.split.show()
            self.split.setSizes([320, 680])

    def _build_fs(self):
        """전체화면용 2단 위젯(하단 책갈피 tree2 · 우측 본문 viewer2) 1회 생성."""
        if self._fs_split is not None:
            return
        from PyQt6.QtWidgets import QSplitter
        self.tree2 = QTreeWidget()
        self.tree2.setHeaderHidden(True)
        self.tree2.currentItemChanged.connect(lambda *_: self._on_select2())
        self.tree2.itemClicked.connect(lambda *_: self._on_select2())
        self.viewer2 = QTextBrowser()
        self.viewer2.setOpenLinks(False)
        self.viewer2.anchorClicked.connect(self._on_anchor_right)
        self.viewer2.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.viewer2.setPlaceholderText("좌측 본문의 코드 링크를 누르면 여기(우측)에서 열립니다.")
        self._fs_left = QSplitter(Qt.Orientation.Vertical)    # 상단/하단 책갈피
        self._fs_left.addWidget(self.tree2)                   # 하단(상단 tree 는 진입 시 0번에 삽입)
        self._fs_right = QSplitter(Qt.Orientation.Horizontal)  # 좌측/우측 본문
        self._fs_right.addWidget(self.viewer2)                # 우측(좌측 viewer 는 진입 시 0번)
        self._fs_split = QSplitter(Qt.Orientation.Horizontal)
        self._fs_split.setHandleWidth(8)
        self._fs_split.addWidget(self._fs_left)
        self._fs_split.addWidget(self._fs_right)
        self._fs_split.setStretchFactor(0, 0)
        self._fs_split.setStretchFactor(1, 1)

    def _on_select2(self):
        """하단 책갈피 선택 → 우측 본문의 해당 절로 스크롤(또는 코드면 우측에 로드)."""
        if self.tree2 is None:
            return
        it = self.tree2.currentItem()
        if it is None:
            return
        anchor = it.data(0, _ROLE_ANCHOR)
        if anchor and self.viewer2 is not None:
            self.viewer2.scrollToAnchor(anchor)
            return
        row = it.data(0, _ROLE_ROW)
        if isinstance(row, dict) and row.get("code"):
            self._load_content(row.get("ctype") or "", row["code"], None,
                               push=False, target="right")

    def _on_escape(self):
        if self.find_bar.isVisible():
            self.find_bar.hide()
        else:
            self.closeRequested.emit()

    # ----- 카탈로그 로드 + 필터 -----
    def _search(self):
        if not (self._key or "").strip():
            self.info.setText("설정 → '인터넷 사전'의 KCSC 키를 먼저 입력하세요.")
            return
        if self._all_rows is None:
            self.info.setText("목록 불러오는 중…")
            w = _CatalogWorker(self._key)
            self._workers.append(w)
            w.done.connect(self._on_catalog)
            w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
            w.start()
        else:
            self._apply_filter()

    def _on_catalog(self, rows, dbg):
        if not rows:
            self.info.setText("목록을 불러오지 못했습니다. " + (dbg[-1] if dbg else ""))
            return
        self._all_rows = rows
        # 드롭다운: '전체' + 데이터에 나온 카테고리(최초 등장 순서)
        seen = []
        for r in rows:
            c = r.get("category") or ""
            if c and c not in seen:
                seen.append(c)
        self.cmb_type.blockSignals(True)
        cur = self.cmb_type.currentData()
        self.cmb_type.clear()
        self.cmb_type.addItem("전체 (전체에서 찾기)", "")
        for c in seen:
            self.cmb_type.addItem(c, c)
        # 이전 선택 유지
        idx = self.cmb_type.findData(cur) if cur else 0
        self.cmb_type.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_type.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self):
        if self._all_rows is None:
            return
        cat = self.cmb_type.currentData() or ""
        q = (self.ed.text() or "").strip().lower()
        rows = self._all_rows
        if cat:
            rows = [r for r in rows if (r.get("category") or "") == cat]
        if q:
            rows = [r for r in rows if q in r["name"].lower()
                    or q in r["code"].lower() or q in (r.get("fullCode") or "").lower()]
        self.tree.clear(); self._cur_item = None
        if not rows:
            self.info.setText("검색 결과가 없습니다.")
            return
        # 카테고리 선택 시 평면, 전체 시 카테고리 그룹
        big = len(rows) > 1500
        if cat:
            for r in rows:
                self.tree.addTopLevelItem(self._leaf(r))
        else:
            groups: dict = {}
            order: list = []
            for r in rows:
                c = r.get("category") or "기타"
                if c not in groups:
                    groups[c] = []; order.append(c)
                groups[c].append(r)
            for c in order:
                g = QTreeWidgetItem([f"{c}  ({len(groups[c])})"])
                self.tree.addTopLevelItem(g)
                for r in groups[c]:
                    g.addChild(self._leaf(r))
                g.setExpanded(not big)        # 너무 많으면 접어둠
        self.info.setText(f"{len(rows)}건" + ("  · 검색어를 입력하면 좁혀집니다." if big else ""))

    @staticmethod
    def _leaf(r: dict) -> QTreeWidgetItem:
        label = f"{r['name']} ({r['code']})" if r.get("code") else r["name"]
        it = QTreeWidgetItem([label])
        it.setData(0, _ROLE_ROW, r)
        return it

    # ----- 선택 → 본문 / 절 이동 -----
    def _on_select(self):
        it = self.tree.currentItem()
        if it is None:
            return
        anchor = it.data(0, _ROLE_ANCHOR)
        if anchor:
            self.viewer.scrollToAnchor(anchor)
            return
        row = it.data(0, _ROLE_ROW)
        if isinstance(row, dict) and row.get("code"):
            self._load_content(row.get("ctype") or "", row["code"], it)

    def _current_row(self):
        it = self.tree.currentItem()
        return it.data(0, _ROLE_ROW) if it is not None else None

    def _load_content(self, ctype, code, item, push: bool = True, target: str = "left"):
        if target == "left":
            self._cur_item = item
        if push:
            cur = self._hist[self._hist_idx][:2] if (0 <= self._hist_idx < len(self._hist)) else None
            if cur != (ctype, code):
                self._hist = self._hist[:self._hist_idx + 1]
                self._hist.append((ctype, code, item))
                self._hist_idx = len(self._hist) - 1
        self._update_nav()
        self.info.setText("불러오는 중…")
        w = _ContentWorker(self._key, ctype, code)
        self._workers.append(w)
        w.done.connect(lambda h, d, a, m, t=target: self._on_content(h, d, a, m, t))
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        w.start()

    # ----- 코드 링크 · 뒤로/앞으로 -----
    def _on_anchor_left(self, url: QUrl):
        # 전체화면이면 좌측 본문의 코드 링크는 우측에서 연다; 내부화면은 같은 창.
        self._anchor(url, self.viewer, "right" if self._is_full else "left")

    def _on_anchor_right(self, url: QUrl):
        self._anchor(url, self.viewer2, "right")

    def _anchor(self, url: QUrl, src_viewer, code_target: str):
        s = url.toString()
        if s.startswith("kcsc://"):
            rest = s[len("kcsc://"):]
            ctype, _, code = rest.partition("/")
            ctype = (ctype or "").strip().upper()
            code = re.sub(r"\D", "", code or "")
            if ctype in ("KDS", "KCS") and len(code) == 6:
                self._open_code(ctype, code, target=code_target)
            return
        if url.scheme().lower() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return
        frag = url.fragment() or (s[1:] if s.startswith("#") else "")
        if frag and src_viewer is not None:
            src_viewer.scrollToAnchor(frag)

    def _open_code(self, ctype: str, code: str, target: str = "left"):
        """260621-62/63: 코드 링크 열기. target='left'=같은 본문창(내부),
        'right'=전체화면 우측 본문(+하단 책갈피)."""
        self._load_content(ctype, code, None, push=(target == "left"), target=target)

    def _nav_back(self):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            ct, cd, it = self._hist[self._hist_idx]
            self._load_content(ct, cd, it, push=False)

    def _nav_fwd(self):
        if self._hist_idx < len(self._hist) - 1:
            self._hist_idx += 1
            ct, cd, it = self._hist[self._hist_idx]
            self._load_content(ct, cd, it, push=False)

    def _update_nav(self):
        self.btn_back.setEnabled(self._hist_idx > 0)
        self.btn_fwd.setEnabled(self._hist_idx < len(self._hist) - 1)

    def _on_content(self, html, dbg, arts, meta, target: str = "left"):
        if not html:
            self.info.setText("표시할 본문이 없습니다. " + (dbg[-1] if dbg else ""))
            return
        linked = linkify_codes(html)
        name = meta.get("name") or ""
        ver = meta.get("version") or ""
        if target == "right" and self.viewer2 is not None:
            # 우측 본문 + 하단 책갈피(절)
            self.viewer2.setHtml(linked)
            self.tree2.clear()
            for label, anchor in (arts or []):
                ch = QTreeWidgetItem([label])
                ch.setData(0, _ROLE_ANCHOR, anchor)
                self.tree2.addTopLevelItem(ch)
            self.info.setText((f"우측: {name}" + (f" (v{ver})" if ver else "")) if name
                              else (dbg[-1] if dbg else ""))
            return
        self.viewer.setHtml(linked)
        self.info.setText((f"{name}" + (f"  (v{ver})" if ver else "")) if name
                          else (dbg[-1] if dbg else ""))
        it = self._cur_item
        if it is not None:
            it.takeChildren()
            for label, anchor in (arts or []):
                ch = QTreeWidgetItem([label])
                ch.setData(0, _ROLE_ANCHOR, anchor)
                it.addChild(ch)
            it.setExpanded(True)

    # ----- 즐겨찾기 -----
    def _on_tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None or it.data(0, _ROLE_ROW) is None:
            return
        self.tree.setCurrentItem(it)
        menu = QMenu(self)
        a_fav = QAction("⭐ 즐겨찾기에 추가", self)
        a_fav.triggered.connect(self._add_favorite_current)
        menu.addAction(a_fav)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_favorite_current(self):
        row = self._current_row()
        if not row:
            return
        win = self._win
        if win is not None and hasattr(win, "_add_kcsc_favorite_entry"):
            win._add_kcsc_favorite_entry(row)
            self.info.setText(f"즐겨찾기에 추가: {row.get('name','')}")

    def _rebuild_fav_menu(self):
        self._fav_menu.clear()
        favs = list(getattr(self._win, "_kcsc_favorites", []) or []) if self._win else []
        if not favs:
            a = self._fav_menu.addAction("(즐겨찾기 없음)")
            a.setEnabled(False)
        else:
            for f in favs:
                label = f.get("name", "?")
                cat = f.get("category")
                if cat:
                    label += f"  ({cat})"
                act = self._fav_menu.addAction(label)
                act.triggered.connect(lambda _=False, ff=f: self.show_saved(ff))
        self._fav_menu.addSeparator()
        mng = self._fav_menu.addAction("즐겨찾기 관리...")
        mng.triggered.connect(self._manage_favs)

    def _manage_favs(self):
        if self._win is not None and hasattr(self._win, "_manage_kcsc_favorites"):
            self._win._manage_kcsc_favorites()

    def show_saved(self, fav: dict):
        """260618-40: 즐겨찾기 클릭 — 좌측 트리에 **모든 건설기준 즐겨찾기**를 책갈피로
        표시하고, 클릭한 항목을 선택(→우측 본문 표시·좌측 강조)."""
        favs = list(getattr(self._win, "_kcsc_favorites", []) or []) if self._win else []
        rows = [dict(f) for f in (favs or [fav])]
        self.tree.clear(); self._cur_item = None
        groups: dict = {}
        order: list = []
        for r in rows:
            c = r.get("category") or "기타"
            if c not in groups:
                groups[c] = []; order.append(c)
            groups[c].append(r)
        multi = len(order) > 1
        for c in order:
            if multi:
                g = QTreeWidgetItem([f"{c}  ({len(groups[c])})"])
                self.tree.addTopLevelItem(g); g.setExpanded(True)
                for r in groups[c]:
                    g.addChild(self._leaf(r))
            else:
                for r in groups[c]:
                    self.tree.addTopLevelItem(self._leaf(r))
        self.info.setText(f"즐겨찾기 {len(rows)}건")
        self._select_fav(fav)

    def _select_fav(self, fav: dict):
        key = (str(fav.get("code") or ""), fav.get("ctype") or "")
        root = self.tree.invisibleRootItem()

        def walk(node):
            for i in range(node.childCount()):
                ch = node.child(i)
                r = ch.data(0, _ROLE_ROW)
                if r and (str(r.get("code") or ""), r.get("ctype") or "") == key:
                    return ch
                found = walk(ch)
                if found:
                    return found
            return None
        it = walk(root)
        if it is not None:
            self.tree.setCurrentItem(it)
            self.tree.scrollToItem(it)

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
