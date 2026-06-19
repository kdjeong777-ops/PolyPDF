"""법령·고시 검색 + 본문 뷰어 — 법제처 국가법령정보 OPEN API.

260616-1: 최초(검색→브라우저).
260616-5: '전체' 기본·정렬·이름생략·검색창 50%.
260616-6: 전체화면 검색+뷰어. 상단 검색창 / 좌측 책갈피트리(법령·행정규칙·법령해석
          1차 그룹, '이름(소관부처/종류)') / 우측 본문(QTextBrowser, 브라우저 대신 창 내 표시).
          항목 우클릭 → 즐겨찾기 추가(법령 즐겨찾기는 메인 즐겨찾기 아래 별도 구역).
"""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QPointF
from PyQt6.QtGui import (QDesktopServices, QAction, QIcon, QPixmap, QPainter,
                         QPen, QColor)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QComboBox, QTreeWidget, QTreeWidgetItem, QTextBrowser, QMenu, QWidget,
)

from viewer.study.law_api import TARGETS, CATEGORY
from viewer.widgets.toggle_splitter import ToggleSplitter
from viewer.widgets.icons import themed_icon

# 책갈피 1차 그룹 표시 순서(법령 → 행정규칙 → 법령해석)
_GROUP_ORDER = ["법령", "행정규칙", "법령해석"]


def _search_icon(color: str = "") -> QIcon:
    """돋보기 아이콘 — 화면 디자인 통일(현재 테마 단색) 아이콘 사용."""
    return themed_icon("search")


def leaf_label(row: dict) -> str:
    """'이름(소관부처/종류)' — 소관부처가 없으면 '이름(종류)'."""
    parts = [p for p in ((row.get("agency") or "").strip(),
                         (row.get("kind") or "").strip()) if p]
    suffix = f" ({'/'.join(parts)})" if parts else ""
    return (row.get("name") or "") + suffix


class _SearchWorker(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, oc, query, target, kind=1):
        super().__init__()
        self._oc, self._q, self._t, self._k = oc, query, target, kind

    def run(self):
        try:
            from viewer.study.law_api import search
            if self._t == "all":
                rows = []
                for val, _label in TARGETS:
                    try:
                        rows.extend(search(self._oc, self._q, val,
                                           search_kind=self._k))
                    except Exception:
                        pass
                self.done.emit(rows)
            else:
                self.done.emit(search(self._oc, self._q, self._t,
                                      search_kind=self._k))
        except Exception as e:
            self.failed.emit(str(e))


class _ContentWorker(QThread):
    done = pyqtSignal(str, list, list, dict)      # html, debug, articles, row

    def __init__(self, oc, row):
        super().__init__()
        self._oc, self._row = oc, row

    def run(self):
        try:
            from viewer.study.law_api import fetch_content_debug
            html, dbg, arts = fetch_content_debug(self._oc, self._row)
            self.done.emit(html, dbg, arts, self._row)
        except Exception as e:
            self.done.emit("", [f"예외: {e}"], [], self._row)


class LawHostWindow(QWidget):
    """260616-19: 전체화면 팝아웃용 호스트 창. 창을 닫으면 closed 신호(→ 내부화면 복귀)."""
    closed = pyqtSignal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class LawSearchPanel(QWidget):
    """260616-19: 법령/고시 검색+본문 패널.
    메인 창에 '2단(오른쪽)'으로 임베드되거나, 전체화면 별도 창으로 팝아웃된다.
    호스트(메인 윈도)가 closeRequested/fullscreenToggled 를 처리한다."""
    _ROW = Qt.ItemDataRole.UserRole + 1
    _ANCHOR = Qt.ItemDataRole.UserRole + 2

    closeRequested = pyqtSignal()
    fullscreenToggled = pyqtSignal()

    def __init__(self, oc: str, win=None):
        super().__init__()
        self.setWindowTitle("법령·고시 검색 (법제처 국가법령정보)")
        self._oc = oc
        self._win = win              # 메인 윈도(즐겨찾기 등록용; 재부모화돼도 유지)
        self._sworker = None
        self._cworker = None
        self._cur_row = None
        self._cur_item = None        # 본문을 표시 중인 법령 트리 항목(조문 자식 부착용)
        self._workers: list = []     # 260616-14: 실행 중 스레드 보관(GC·terminate 크래시 방지)

        # 260618-8: 좁게 끌어도 제목줄 버튼(전체화면/X)이 잘리지 않도록 최소 폭 보장
        self.setMinimumWidth(360)
        # 260618-8: ESC → 찾기바가 열려 있으면 닫고, 아니면 법령/고시 패널 닫기
        from PyQt6.QtGui import QShortcut, QKeySequence
        _esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        _esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        _esc.activated.connect(self._on_escape)

        # 260616-11: 기본 글자를 한글 폰트로
        try:
            _f = self.font()
            _f.setFamily("Malgun Gothic")
            self.setFont(_f)
        except Exception:
            pass

        v = QVBoxLayout(self)

        # --- 제목줄: '법령/고시' + 전체화면 토글 + 닫기 ---
        title_row = QHBoxLayout()
        title = QLabel("법령/고시")
        tf = title.font()
        tf.setBold(True)
        tf.setPointSize(max(11, tf.pointSize() + 2))
        title.setFont(tf)
        title_row.addWidget(title)
        # 260616-20: '법령/고시' 우측 즐겨찾기 풀다운(목록 + 관리)
        self.btn_fav = QPushButton("⭐ 즐겨찾기")
        self.btn_fav.setIcon(themed_icon("star"))
        self._fav_menu = QMenu(self)
        self._fav_menu.aboutToShow.connect(self._rebuild_fav_menu)
        self.btn_fav.setMenu(self._fav_menu)
        title_row.addWidget(self.btn_fav)
        title_row.addStretch(1)
        self.btn_full = QPushButton("⛶ 전체화면")   # 전체화면/내부화면 토글
        self.btn_full.setToolTip("전체화면(별도 창) ↔ 내부화면(메인 오른쪽)")
        self.btn_full.clicked.connect(self.fullscreenToggled.emit)
        title_row.addWidget(self.btn_full)
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(34, 28)
        self.btn_close.setToolTip("법령/고시 닫기")
        self.btn_close.setStyleSheet(
            "QPushButton{color:#d11;font-weight:bold;border:1px solid #c0c0c0;"
            "border-radius:5px;background:#f2f2f2;}"
            "QPushButton:hover{background:#e81123;color:#fff;border-color:#e81123;}")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        title_row.addWidget(self.btn_close)
        v.addLayout(title_row)

        # --- 검색줄: 검색박스(둥근·돋보기·테마대응) + 대상 + 종류 + 검색 + 지구본 ---
        top = QHBoxLayout()
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("법령/고시 검색")
        self.ed.setObjectName("lawSearch")
        self._lead_act = self.ed.addAction(
            _search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.ed.returnPressed.connect(self._search)
        # 260616-20: 대상은 항상 '전체'. 검색종류(이름/내용)만 선택.
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem("이름", 1)
        self.cmb_kind.addItem("내용", 2)
        # 이전/이후 이동 버튼(종류에 따라 동작 달라짐)
        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(themed_icon("chevron_up"))
        self.btn_prev.setFixedWidth(34)
        self.btn_prev.setToolTip("이전")
        self.btn_prev.clicked.connect(lambda: self._nav(True))
        self.btn_next = QPushButton()
        self.btn_next.setIcon(themed_icon("chevron_down"))
        self.btn_next.setFixedWidth(34)
        self.btn_next.setToolTip("이후")
        self.btn_next.clicked.connect(lambda: self._nav(False))
        self.btn_globe = QPushButton()       # 브라우저 열기(지구본)
        self.btn_globe.setIcon(themed_icon("globe"))
        self.btn_globe.setFixedWidth(36)
        self.btn_globe.setToolTip("선택 항목을 브라우저에서 열기")
        self.btn_globe.clicked.connect(self._open_browser)
        top.addWidget(self.ed)
        top.addWidget(self.cmb_kind)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_next)
        top.addWidget(self.btn_globe)
        top.addStretch(1)
        v.addLayout(top)

        # 상태(간단) — 해설 문구는 제거, 검색 상태/건수만
        self.info = QLabel("")
        self.info.setStyleSheet("color:#888;")
        v.addWidget(self.info)

        # --- 본문: 좌(트리·책갈피) / 우(본문) — 손잡이 더블클릭으로 슬라이드 ---
        self.split = ToggleSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(8)             # 손잡이 넓게(더블클릭 토글)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        self.tree.currentItemChanged.connect(lambda *_: self._on_select())
        self.tree.itemClicked.connect(lambda *_: self._on_select())
        self.split.addWidget(self.tree)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setPlaceholderText("본문이 여기에 표시됩니다.")
        # 260616-7: 본문은 항상 흰 종이처럼(다크 테마에서도 가독)
        self.viewer.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.split.addWidget(self.viewer)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, True)
        self.split.setSizes([330, 770])
        self._tree_w = 330
        v.addWidget(self.split, 1)

        # --- 본문 내 찾기 바(Ctrl+F) — 기본 숨김 ---
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(2, 2, 2, 2)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("내용에서 찾기")
        self.find_edit.addAction(_search_icon("#888888"),
                                 QLineEdit.ActionPosition.LeadingPosition)
        self.find_edit.returnPressed.connect(lambda: self._find(False))
        self.find_edit.textChanged.connect(lambda *_: self._find(False, True))
        b_prev = QPushButton(); b_prev.setIcon(themed_icon("chevron_up"))
        b_prev.setFixedWidth(30); b_prev.setToolTip("이전")
        b_prev.clicked.connect(lambda: self._find(True))
        b_next = QPushButton(); b_next.setIcon(themed_icon("chevron_down"))
        b_next.setFixedWidth(30); b_next.setToolTip("다음 (Enter)")
        b_next.clicked.connect(lambda: self._find(False))
        b_fclose = QPushButton(); b_fclose.setIcon(themed_icon("close"))
        b_fclose.setFixedWidth(30); b_fclose.setToolTip("닫기 (Esc)")
        b_fclose.clicked.connect(self._hide_find)
        fb.addWidget(self.find_edit, 1)
        fb.addWidget(b_prev)
        fb.addWidget(b_next)
        fb.addWidget(b_fclose)
        self.find_bar.setVisible(False)
        v.addWidget(self.find_bar)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._show_find)
        QShortcut(QKeySequence("Esc"), self.find_edit, activated=self._hide_find)

        # 260616-15: Enter 가 '닫기/기본버튼'으로 작동해 창이 닫히던 문제 방지 —
        #   모든 버튼의 autoDefault/default 해제(Enter 는 검색창/찾기창에서만 동작).
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)
        # 검색박스 포커스 + 한글 입력 활성화
        self.ed.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)

        self._apply_theme_styles()
        self._apply_search_width()

    # ----- 레이아웃 -----
    def set_fullscreen(self, is_full: bool):
        """260616-19: 토글 버튼 라벨 갱신(전체화면/내부화면)."""
        self.btn_full.setText("▣ 내부화면" if is_full else "⛶ 전체화면")

    def _on_escape(self):
        """260618-8: ESC — 찾기바 열려 있으면 닫고, 아니면 패널 닫기."""
        fb = getattr(self, "find_bar", None)
        if fb is not None and fb.isVisible():
            fb.hide()
        else:
            self.closeRequested.emit()

    def _apply_search_width(self):
        try:
            self.ed.setFixedWidth(max(200, int(self.width() * 0.5)))
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_search_width()

    def showEvent(self, event):
        super().showEvent(event)
        self.ed.setFocus()          # 검색박스에 포커스(바로 입력 가능)

    def _apply_theme_styles(self):
        """260616-13: 검색박스를 다크/화이트 모드에 맞는 색으로(항상 블랙 방지)."""
        try:
            from viewer import theme as _theme
            dark = _theme.is_dark()
        except Exception:
            dark = False
        if dark:
            css = ("QLineEdit#lawSearch{background:#3a3a3d;color:#e8e8e8;"
                   "border:1px solid #5a5a5a;border-radius:16px;padding:6px 14px;}"
                   "QLineEdit#lawSearch:focus{border-color:#7a7a7a;}")
            ic = "#bbbbbb"
        else:
            css = ("QLineEdit#lawSearch{background:#ffffff;color:#222222;"
                   "border:1px solid #b8b8b8;border-radius:16px;padding:6px 14px;}"
                   "QLineEdit#lawSearch:focus{border-color:#7a7a7a;}")
            ic = "#777777"
        self.ed.setStyleSheet(css)
        try:
            self._lead_act.setIcon(_search_icon(ic))
        except Exception:
            pass

    # ----- 본문 내 찾기(Ctrl+F) -----
    def _show_find(self):
        self.find_bar.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _hide_find(self):
        self.find_bar.setVisible(False)
        self.viewer.setExtraSelections([])    # 하이라이트 제거
        self.viewer.setFocus()

    def _highlight_all(self, text):
        """260616-15: 본문에서 일치하는 모든 부분을 노란색으로 하이라이트."""
        from PyQt6.QtWidgets import QTextEdit
        from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor
        sels = []
        if text:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#fff176"))
            fmt.setForeground(QColor("#1a1a1a"))
            doc = self.viewer.document()
            cur = QTextCursor(doc)
            while True:
                cur = doc.find(text, cur)
                if cur.isNull():
                    break
                es = QTextEdit.ExtraSelection()
                es.format = fmt
                es.cursor = cur
                sels.append(es)
        self.viewer.setExtraSelections(sels)

    def _find(self, backward=False, from_cursor_keep=False):
        from PyQt6.QtGui import QTextDocument, QTextCursor
        text = self.find_edit.text()
        self._highlight_all(text)             # 모든 일치 하이라이트
        if not text:
            return
        flags = (QTextDocument.FindFlag.FindBackward if backward
                 else QTextDocument.FindFlag(0))
        if from_cursor_keep:
            # 입력 중: 현재 선택 시작에서 다시 찾아 깜빡임 최소화
            cur = self.viewer.textCursor()
            cur.setPosition(cur.selectionStart())
            self.viewer.setTextCursor(cur)
        if not self.viewer.find(text, flags):
            # 끝/처음으로 돌아가 재검색(순환)
            cur = self.viewer.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End if backward
                             else QTextCursor.MoveOperation.Start)
            self.viewer.setTextCursor(cur)
            self.viewer.find(text, flags)

    # ----- 이전/이후 이동(종류에 따라 동작) -----
    def _nav(self, backward: bool):
        """260616-20: 이름 모드=좌측 책갈피(법령 항목) 이동, 내용 모드=우측 본문에서
        검색어 이전/이후 이동 + 하이라이트."""
        if self.cmb_kind.currentData() == 2:    # 내용
            self._find_in_content(self.ed.text().strip(), backward)
        else:                                   # 이름
            self._select_sibling(backward)

    def _select_sibling(self, backward: bool):
        """좌측 트리에서 선택 가능한(법령/조문) 항목으로 이전/이후 이동."""
        def selectable(it):
            return it is not None and (it.data(0, self._ROW) is not None
                                       or it.data(0, self._ANCHOR) is not None)
        cur = self.tree.currentItem()
        if cur is None:
            it = self.tree.topLevelItem(0)
            while it is not None and not selectable(it):
                it = self.tree.itemBelow(it)
            if it:
                self.tree.setCurrentItem(it)
            return
        nxt = self.tree.itemAbove(cur) if backward else self.tree.itemBelow(cur)
        while nxt is not None and not selectable(nxt):
            nxt = self.tree.itemAbove(nxt) if backward else self.tree.itemBelow(nxt)
        if nxt is not None:
            self.tree.setCurrentItem(nxt)

    def _find_in_content(self, text: str, backward: bool):
        """우측 본문에서 text 의 이전/이후 일치로 이동 + 전체 하이라이트."""
        from PyQt6.QtGui import QTextDocument, QTextCursor
        self._highlight_all(text)
        if not text:
            return
        flags = (QTextDocument.FindFlag.FindBackward if backward
                 else QTextDocument.FindFlag(0))
        if not self.viewer.find(text, flags):
            cur = self.viewer.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End if backward
                             else QTextCursor.MoveOperation.Start)
            self.viewer.setTextCursor(cur)
            self.viewer.find(text, flags)

    # ----- 즐겨찾기 풀다운 -----
    def _rebuild_fav_menu(self):
        self._fav_menu.clear()
        favs = list(getattr(self._win, "_law_favorites", []) or []) if self._win else []
        if not favs:
            a = self._fav_menu.addAction("(즐겨찾기 없음)")
            a.setEnabled(False)
        else:
            for f in favs:
                label = f.get("name", "?")
                kl = f.get("kind_label") or f.get("category")
                if kl:
                    label += f"  ({kl})"
                act = self._fav_menu.addAction(label)
                act.triggered.connect(lambda _=False, ff=f: self.show_saved(ff))
        self._fav_menu.addSeparator()
        mng = self._fav_menu.addAction("즐겨찾기 관리...")
        mng.triggered.connect(self._manage_favs)

    def _manage_favs(self):
        if self._win is not None and hasattr(self._win, "_manage_law_favorites"):
            self._win._manage_law_favorites()

    # ----- 검색 -----
    def _search(self):
        q = self.ed.text().strip()
        if not q or (self._sworker and self._sworker.isRunning()):
            return
        self.tree.clear()
        self.viewer.clear()
        self.info.setText("검색 중…")
        self._sworker = _SearchWorker(self._oc, q, "all",
                                      self.cmb_kind.currentData())
        self._start_worker(self._sworker, self._on_search_done,
                           self._on_search_failed)

    def _start_worker(self, worker, on_done, on_failed=None):
        """260616-14: 스레드를 보관하고 끝나면 정리. terminate() 미사용(크래시 방지)."""
        self._workers.append(worker)
        worker.done.connect(on_done)
        if on_failed is not None and hasattr(worker, "failed"):
            worker.failed.connect(on_failed)
        worker.finished.connect(lambda w=worker: self._reap(w))
        worker.start()

    def _reap(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _on_search_done(self, rows):
        if not rows:
            self.info.setText("결과가 없습니다. (검색어/인증키 확인)")
            return
        self.info.setText(f"{len(rows)}건")
        # 카테고리별 그룹화(법령 → 행정규칙 → 법령해석)
        groups: dict = {}
        for r in rows:
            groups.setdefault(r.get("category", "기타"), []).append(r)
        order = _GROUP_ORDER + [c for c in groups if c not in _GROUP_ORDER]
        for cat in order:
            items = groups.get(cat)
            if not items:
                continue
            top = QTreeWidgetItem([f"{cat} ({len(items)})"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for r in items:
                leaf = QTreeWidgetItem([leaf_label(r)])
                leaf.setData(0, self._ROW, r)
                leaf.setToolTip(0, leaf_label(r))
                top.addChild(leaf)
            top.setExpanded(True)         # 전체 펼침
        self.tree.expandAll()

    def _on_search_failed(self, msg):
        self.info.setText(f"검색 실패(네트워크/인증키 확인): {msg}")

    # ----- 본문 표시 -----
    def _current_row(self):
        it = self.tree.currentItem()
        return it.data(0, self._ROW) if it is not None else None

    def _on_select(self):
        it = self.tree.currentItem()
        if it is None:
            return
        # 조문(앵커) 자식 클릭 → 본문에서 해당 조로 스크롤(재요청 없음)
        anchor = it.data(0, self._ANCHOR)
        if anchor:
            self.viewer.scrollToAnchor(anchor)
            return
        row = it.data(0, self._ROW)
        if not row or row is self._cur_row:
            return
        self._cur_row = row
        self._cur_item = it
        self.viewer.setHtml(
            f"<p style='color:#888'>본문을 불러오는 중… "
            f"<b>{row.get('name','')}</b></p>")
        # 260616-14: 이전 본문 스레드를 강제 종료하지 않고, 결과는 row 일치 검사로 무시
        self._cworker = _ContentWorker(self._oc, row)
        self._start_worker(self._cworker, self._on_content)

    def _populate_articles(self, item, arts):
        """260616-10: 선택한 법령 항목 아래에 조문 책갈피(앵커)를 채운다."""
        if item is None:
            return
        # 기존 조문 자식 제거(재선택 시 중복 방지)
        for i in range(item.childCount() - 1, -1, -1):
            item.removeChild(item.child(i))
        for label, anchor in arts:
            ch = QTreeWidgetItem([label])
            ch.setData(0, self._ANCHOR, anchor)
            ch.setToolTip(0, label)
            item.addChild(ch)
        if arts:
            item.setExpanded(True)

    def _on_content(self, html, dbg, arts, row):
        if row is not self._cur_row:
            return                       # 더 최근 선택이 있으면 무시
        self._populate_articles(self._cur_item, arts or [])
        if html and html.strip():
            self.viewer.setHtml(html)
        else:
            self._show_content_fallback(row, dbg)

    def _show_content_fallback(self, row, dbg=None):
        link = row.get("link") or ""
        diag = ""
        if dbg:
            rows = "".join(f"<li>{d}</li>" for d in dbg)
            diag = ("<p style='color:#999;font-size:12px'>진단(개발용):</p>"
                    f"<ul style='color:#999;font-size:12px'>{rows}</ul>")
        self.viewer.setHtml(
            "<div style='font-family:sans-serif;color:#1a1a1a;background:#fff'>"
            f"<h3>{row.get('name','')}</h3>"
            f"<p>{row.get('agency','')} · {row.get('kind','')} · {row.get('date','')}</p>"
            f"<p style='color:#888'>본문을 창 안에서 불러오지 못했습니다."
            f" 아래 링크 또는 🌐(브라우저) 버튼으로 확인하세요.</p>"
            + (f"<p><a href='{link}'>{link}</a></p>" if link else "")
            + diag + "</div>")

    def _open_browser(self):
        row = self._current_row()
        link = (row or {}).get("link")
        if link:
            QDesktopServices.openUrl(QUrl(link))

    # ----- 즐겨찾기 -----
    def _on_tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None or it.data(0, self._ROW) is None:
            return
        self.tree.setCurrentItem(it)
        menu = QMenu(self)
        a_fav = QAction("⭐ 즐겨찾기에 추가", self)
        a_fav.triggered.connect(self._add_favorite_current)
        menu.addAction(a_fav)
        a_web = QAction("브라우저에서 열기", self)
        a_web.triggered.connect(self._open_browser)
        menu.addAction(a_web)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_favorite_current(self):
        row = self._current_row()
        if not row:
            return
        win = self._win
        if win is not None and hasattr(win, "_add_law_favorite_entry"):
            win._add_law_favorite_entry(row)
            self.info.setText(f"즐겨찾기에 추가: {row.get('name','')}")

    # ----- 즐겨찾기로 직접 열기 -----
    def show_saved(self, row: dict):
        """저장된 법령 즐겨찾기 항목의 본문을 바로 표시(검색 없이)."""
        self._cur_row = row
        self._cur_item = None        # 트리 항목 없음(조문 자식 부착 생략)
        self.info.setText(f"즐겨찾기: {row.get('name','')}")
        self.viewer.setHtml(
            f"<p style='color:#888'>본문을 불러오는 중… "
            f"<b>{row.get('name','')}</b></p>")
        self._cworker = _ContentWorker(self._oc, row)
        self._start_worker(self._cworker, self._on_content)


class LawFavoritesManager(QDialog):
    """260616-20: 법령·고시 즐겨찾기 관리 — 이름변경/위로·아래로 이동/삭제."""

    def __init__(self, favs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("법령·고시 즐겨찾기 관리")
        self.resize(460, 420)
        self._favs = [dict(f) for f in (favs or [])]
        from PyQt6.QtWidgets import QListWidget
        v = QVBoxLayout(self)
        self.listw = QListWidget()
        v.addWidget(self.listw, 1)
        row = QHBoxLayout()
        b_rename = QPushButton("이름변경")
        b_rename.clicked.connect(self._rename)
        b_up = QPushButton("▲ 위로")
        b_up.clicked.connect(lambda: self._move(-1))
        b_down = QPushButton("▼ 아래로")
        b_down.clicked.connect(lambda: self._move(1))
        b_del = QPushButton("삭제")
        b_del.clicked.connect(self._delete)
        for b in (b_rename, b_up, b_down, b_del):
            row.addWidget(b)
        v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        b_ok = QPushButton("저장")
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("취소")
        b_cancel.clicked.connect(self.reject)
        row2.addWidget(b_ok)
        row2.addWidget(b_cancel)
        v.addLayout(row2)
        self._reload()

    def _reload(self, sel=0):
        self.listw.clear()
        for f in self._favs:
            label = f.get("name", "?")
            kl = f.get("kind_label") or f.get("category")
            if kl:
                label += f"  ({kl})"
            self.listw.addItem(label)
        if 0 <= sel < self.listw.count():
            self.listw.setCurrentRow(sel)

    def _rename(self):
        i = self.listw.currentRow()
        if not (0 <= i < len(self._favs)):
            return
        from PyQt6.QtWidgets import QInputDialog
        cur = self._favs[i].get("name", "")
        new, ok = QInputDialog.getText(self, "이름변경", "새 이름:", text=cur)
        if ok and new.strip():
            self._favs[i]["name"] = new.strip()
            self._reload(i)

    def _move(self, d):
        i = self.listw.currentRow()
        j = i + d
        if 0 <= i < len(self._favs) and 0 <= j < len(self._favs):
            self._favs[i], self._favs[j] = self._favs[j], self._favs[i]
            self._reload(j)

    def _delete(self):
        i = self.listw.currentRow()
        if 0 <= i < len(self._favs):
            del self._favs[i]
            self._reload(min(i, len(self._favs) - 1))

    def result_favorites(self):
        return self._favs
