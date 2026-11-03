"""단어장 관리 다이얼로그 — 적용할 사전 고르기 · 스타일 · 우선순위(▲▼).

SOT: `단어장 작업 계획서.md` §11.1 (261103-2, 사용자 지시·결정).
- 왼쪽 '대기 사전'(사전 목록에서 활성인 것 가운데 안 쓰는 것) ↔ 오른쪽 '적용할 사전'(지금 PDF 에 쓰는 것).
  [추가 →] [← 삭제] [모두 추가 →] [← 모두 삭제], 두 번 누르기. '삭제' 는 적용 목록에서 빼기 — 사전은 지우지 않는다.
- 오른쪽 차례 = 우선순위(▲▼ → priority 재배정, 모든 PDF 공통, 바로 저장).
- 스타일(settings.json `dict_styles`): 오른쪽 조합에 이름을 붙여 저장·삭제·고르기.
- '이후 PDF 에도 계속 적용' 켜짐 = 기본 선택 `enabled`, 꺼짐 = 이 PDF 의 선택(`dict_file_off`). 어느 길로 닫아도 저장.
- 사전 더하기·지우기·활성·폴더는 환경설정 → 고급 설정 → 사전 목록(`dict_list_group.py`).
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QMessageBox, QInputDialog,
)

_KIND_LABEL = {"user": "사용자", "base": "사전/용어집", "auto": "자동(번역)",
               "online": "인터넷"}
_STYLE_NONE = "(스타일 고르기)"


def source_label(s: dict) -> str:
    """목록 한 줄 — '이름  (종류 / 구분, 항목 수)'. 사전 목록 묶음도 같은 꼴을 쓴다."""
    kind = _KIND_LABEL.get(s.get("kind"), s.get("kind") or "")
    cat = (s.get("category") or "").strip()
    meta = kind + (f" / {cat}" if cat else "")
    return f"{s.get('name') or s.get('source_id')}  ({meta}, {s.get('n_entries', 0)})"


class DictManagerDialog(QDialog):
    changed = pyqtSignal()

    def __init__(self, store, prefs: dict = None, host=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("단어장 관리")
        self.setMinimumSize(720, 460)
        self._store = store
        self._prefs = prefs or {}
        self._host = host

        v = QVBoxLayout(self)
        intro = QLabel(
            "지금 PDF 에 쓸 사전을 <b>오른쪽(적용할 사전)</b>으로 옮깁니다. 오른쪽 차례가 <b>우선순위</b>입니다"
            "(사용자 ▶ 사전/용어집 ▶ 자동/인터넷 안에서 위부터).<br>"
            "<small>사전 더하기·지우기·활성은 환경설정 → 고급 설정 → <b>사전 목록</b>에서 합니다.</small>")
        intro.setWordWrap(True)
        v.addWidget(intro)

        # ── 스타일 ──
        st = QHBoxLayout()
        st.addWidget(QLabel("스타일"))
        self.cmb_style = QComboBox()
        self.cmb_style.setToolTip("저장해 둔 사전 조합 — 고르면 오른쪽 목록이 그 조합으로 바뀝니다.")
        self.cmb_style.activated.connect(self._on_style_chosen)
        st.addWidget(self.cmb_style, 1)
        self.btn_style_save = QPushButton("저장...")
        self.btn_style_save.setToolTip("오른쪽 목록의 조합을 스타일로 저장합니다(같은 이름이면 덮어씁니다).")
        self.btn_style_save.clicked.connect(self._style_save)
        self.btn_style_del = QPushButton("삭제")
        self.btn_style_del.setToolTip("고른 스타일을 지웁니다(사전은 그대로).")
        self.btn_style_del.clicked.connect(self._style_delete)
        st.addWidget(self.btn_style_save); st.addWidget(self.btn_style_del)
        v.addLayout(st)
        has_styles = host is not None and hasattr(host, "_dict_styles")
        for w in (self.cmb_style, self.btn_style_save, self.btn_style_del):
            w.setEnabled(has_styles)

        # ── 두 목록 ──
        body = QHBoxLayout()
        left = QVBoxLayout(); left.addWidget(QLabel("대기 사전"))
        self.lst_wait = self._make_list()
        self.lst_wait.itemDoubleClicked.connect(lambda _it: self._add())
        left.addWidget(self.lst_wait, 1)
        body.addLayout(left, 1)

        mid = QVBoxLayout(); mid.addStretch(1)
        self.btn_add = QPushButton("추가 →")
        self.btn_add.setToolTip("고른 사전을 적용할 사전에 넣습니다.")
        self.btn_remove = QPushButton("← 삭제")
        self.btn_remove.setToolTip("고른 사전을 적용할 사전에서 뺍니다(사전은 지우지 않습니다).")
        self.btn_add_all = QPushButton("모두 추가 →")
        self.btn_remove_all = QPushButton("← 모두 삭제")
        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_add_all.clicked.connect(lambda: self._move_all(True))
        self.btn_remove_all.clicked.connect(lambda: self._move_all(False))
        for b in (self.btn_add, self.btn_remove):
            mid.addWidget(b)
        mid.addSpacing(10)
        for b in (self.btn_add_all, self.btn_remove_all):
            mid.addWidget(b)
        mid.addStretch(1)
        body.addLayout(mid)

        right = QVBoxLayout(); right.addWidget(QLabel("적용할 사전"))
        self.lst_use = self._make_list()
        self.lst_use.itemDoubleClicked.connect(lambda _it: self._remove())
        right.addWidget(self.lst_use, 1)
        body.addLayout(right, 1)

        col = QVBoxLayout(); col.addStretch(1)
        self.btn_up = QPushButton("▲"); self.btn_up.setFixedWidth(40); self.btn_up.setToolTip("우선순위 올림")
        self.btn_dn = QPushButton("▼"); self.btn_dn.setFixedWidth(40); self.btn_dn.setToolTip("우선순위 내림")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_dn.clicked.connect(lambda: self._move(+1))
        col.addWidget(self.btn_up); col.addWidget(self.btn_dn); col.addStretch(1)
        body.addLayout(col)
        v.addLayout(body, 1)

        # ── 적용 범위 ── 켜면 오른쪽 목록이 기본 선택(이후 PDF 에도), 끄면 이 PDF 에만
        self.chk_default = QCheckBox("이후 PDF 에도 계속 적용(바꿀 때까지)")
        self.chk_default.setToolTip(
            "켜면 고른 단어장을 기본으로 저장해, 따로 고르지 않은 모든 PDF 에 씁니다.\n"
            "끄면 지금 PDF 에만 적용하고 다른 PDF 는 그대로 둡니다.")
        file_path = getattr(host, "_study_pdf", None) if host is not None else None
        own = bool(host is not None and hasattr(host, "_dict_file_off")
                   and host._dict_file_off() is not None)
        self.chk_default.setChecked(not own)
        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("color:#666;")
        if file_path:
            self.lbl_file.setText(f"지금 PDF: {os.path.basename(str(file_path))}"
                                  + ("  (이 PDF 만의 선택)" if own else ""))
        else:
            self.lbl_file.setText("열린 PDF 없음 — 기본 선택을 고칩니다")
            self.chk_default.setEnabled(False)
        sc = QHBoxLayout(); sc.addWidget(self.chk_default); sc.addWidget(self.lbl_file, 1)
        v.addLayout(sc)
        self._applied = False

        row2 = QHBoxLayout()
        b_user = QPushButton("사용자 뜻 편집…")          # 261019-5
        b_user.clicked.connect(self._user_terms)
        row2.addWidget(b_user)
        row2.addStretch(1)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.accept)
        row2.addWidget(self.btn_close)
        v.addLayout(row2)

        self._srcs: list[dict] = []
        self._use: set = set()
        self._load(initial=True)
        self._reload_styles()

    # ----- 목록 -----
    @staticmethod
    def _make_list() -> QListWidget:
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        return lst

    def _load(self, initial: bool = False):
        """사전 목록(활성인 것만, 우선순위 차례)을 다시 읽는다 — 아직 저장하지 않은 고름은 남긴다."""
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        self._srcs = [s for s in srcs if not s.get("inactive")]
        ids = {s["source_id"] for s in self._srcs}
        if initial:
            self._use = {s["source_id"] for s in self._srcs if s.get("active")}
        else:
            self._use &= ids
        self._render()

    def _render(self, keep_sel: set | None = None):
        for lst in (self.lst_wait, self.lst_use):
            lst.clear()
        for s in self._srcs:
            sid = s["source_id"]
            it = QListWidgetItem(source_label(s))
            it.setData(Qt.ItemDataRole.UserRole, sid)
            (self.lst_use if sid in self._use else self.lst_wait).addItem(it)
            if keep_sel and sid in keep_sel:
                it.setSelected(True)
                it.listWidget().setCurrentItem(it)

    @staticmethod
    def _ids(lst: QListWidget, selected: bool = True) -> list:
        items = lst.selectedItems() if selected else [lst.item(i) for i in range(lst.count())]
        return [it.data(Qt.ItemDataRole.UserRole) for it in items]

    def use_ids(self) -> list:
        """오른쪽 목록(적용할 사전) — 우선순위 차례."""
        return self._ids(self.lst_use, selected=False)

    def wait_ids(self) -> list:
        return self._ids(self.lst_wait, selected=False)

    def _add(self):
        moved = set(self._ids(self.lst_wait))
        self._use |= moved
        self._render(moved)

    def _remove(self):
        moved = set(self._ids(self.lst_use))
        self._use -= moved
        self._render(moved)

    def _move_all(self, to_use: bool):
        self._use = {s["source_id"] for s in self._srcs} if to_use else set()
        self._render()

    def _move(self, direction: int):
        """오른쪽 목록에서 고른 사전을 한 칸 — 우선순위(모든 PDF 공통)를 바로 고친다."""
        cur = self.lst_use.currentItem()
        if cur is None:
            return
        sid = cur.data(Qt.ItemDataRole.UserRole)
        right = self.use_ids()
        r = right.index(sid)
        nr = r + direction
        if nr < 0 or nr >= len(right):
            return
        other = right[nr]
        try:
            order = [s["source_id"] for s in self._store.list_sources()]   # 비활성까지 전체 차례
            i, j = order.index(sid), order.index(other)
            order[i], order[j] = order[j], order[i]
            for k, x in enumerate(order):
                self._store.set_source_priority(x, (k + 1) * 10)
        except Exception:
            pass
        self._load()
        self._render({sid})
        self.changed.emit()

    # ----- 스타일 -----
    def _reload_styles(self, current: str = ""):
        self.cmb_style.blockSignals(True)
        self.cmb_style.clear()
        self.cmb_style.addItem(_STYLE_NONE)
        names = [s["name"] for s in self._host._dict_styles()] if self.cmb_style.isEnabled() else []
        for n in names:
            self.cmb_style.addItem(n)
        i = self.cmb_style.findText(current) if current else -1
        self.cmb_style.setCurrentIndex(i if i > 0 else 0)
        self.cmb_style.blockSignals(False)
        self.btn_style_del.setEnabled(self.cmb_style.isEnabled() and bool(names))

    def _on_style_chosen(self, index: int):
        if index <= 0:
            return
        self._use = set(self._host._dict_style_sources(self.cmb_style.itemText(index)))
        self._render()

    def _style_save(self):
        cur = self.cmb_style.currentText() if self.cmb_style.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(self, "스타일 저장", "스타일 이름:", text=cur)
        name = (name or "").strip()
        if not ok or not name:
            return
        self._host._save_dict_style(name, self.use_ids())
        self._reload_styles(name)

    def _style_delete(self):
        if self.cmb_style.currentIndex() <= 0:
            return
        name = self.cmb_style.currentText()
        if QMessageBox.question(self, "스타일 삭제", f"'{name}' 스타일을 지울까요?\n(사전은 그대로입니다)") \
                != QMessageBox.StandardButton.Yes:
            return
        self._host._delete_dict_style(name)
        self._reload_styles()

    # ----- 저장 -----
    def _apply_enabled(self):
        """오른쪽 목록 저장 — 단어장 SOT §11.1: '이후 PDF 에도' 켜짐 = 기본 선택, 꺼짐 = 이 PDF 에만."""
        use = self.use_ids()
        if self._host is not None and hasattr(self._host, "_set_dict_selection"):
            try:
                self._host._set_dict_selection(use, as_default=self.chk_default.isChecked())
            except Exception:
                pass
            return
        for s in self._srcs:
            try:
                self._store.set_source_enabled(s["source_id"], s["source_id"] in use)
            except Exception:
                pass

    def _user_terms(self):
        if self._host is not None and hasattr(self._host, "_action_user_terms"):
            self._host._action_user_terms()
            self._load()
            self.changed.emit()

    def done(self, r):
        # 261103-2: 닫기·Esc·창 X 어느 길로 닫아도 저장한다(종전에는 [닫기] 만 저장했다)
        if not self._applied:
            self._applied = True
            self._apply_enabled()
            self.changed.emit()
        super().done(r)
