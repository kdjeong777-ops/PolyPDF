"""단어장 관리 다이얼로그 — 적용할 사전 고르기 · 스타일 · 우선순위(▲▼) · 사전 더하기·지우기.

SOT: `단어장 작업 계획서.md` §11.1 (261103-2, 사용자 지시·결정).
- 왼쪽 '대기 사전'(있는 사전 가운데 지금 PDF 에 안 쓰는 것) ↔ 오른쪽 '적용할 사전'(지금 PDF 에 쓰는 것).
  [추가 →] [← 삭제] [모두 추가 →] [← 모두 삭제], 두 번 누르기. '삭제' 는 적용 목록에서 빼기 — 사전은 지우지 않는다.
- 오른쪽 차례 = 우선순위(▲▼ → priority 재배정, 모든 PDF 공통, 바로 저장).
- 스타일(settings.json `dict_styles`): 오른쪽 조합에 이름을 붙여 저장·삭제·고르기.
- '이후 PDF 에도 계속 적용' 켜짐 = 기본 선택 `enabled`, 꺼짐 = 이 PDF 의 선택(`dict_file_off`). 어느 길로 닫아도 저장.
- 사전 파일 줄: [가져오기...]·[사전 지우기]·[지운 사전 되살리기...]·[폴더 열기]·[새로고침]·[양식 CSV] — 누르면 바로 dict.db 에 쓴다.
  지운 사전은 `dict_meta.deleted_sources` 에 기억 — 동봉 용어집·폴더 CSV 도 다시 싣지 않는다.
  (261103-8: 고급 설정 '사전 목록' 묶음을 없애고 이리로 옮겼다 — 사용자 지시 '단어장 관리로 충분')
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QMessageBox, QInputDialog,
    QDialogButtonBox,
)

_KIND_LABEL = {"user": "사용자", "base": "사전/용어집", "auto": "자동(번역)",
               "online": "인터넷"}
_STYLE_NONE = "(스타일 고르기)"


def source_label(s: dict) -> str:
    """목록 한 줄 — '이름  (종류 / 구분, 항목 수)'."""
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
            "<small>[← 삭제] 는 적용 목록에서 빼기만 합니다. 사전 자체를 지우려면 아래 [사전 지우기].</small>")
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

        # ── 사전 파일 ── 더하기·지우기·되살리기·폴더(누르면 바로 저장)
        r1 = QHBoxLayout()
        self.btn_import = QPushButton("가져오기...")
        self.btn_import.setToolTip("용어집 파일(PDF·CSV)을 사전으로 불러옵니다.")
        self.btn_delete = QPushButton("사전 지우기")
        self.btn_delete.setToolTip("고른 사전과 그 항목을 지웁니다(어느 목록에서 골라도) — 사용자 단어장은 지울 수 없습니다.")
        self.btn_restore = QPushButton("지운 사전 되살리기...")
        for b, fn in ((self.btn_import, self._import), (self.btn_delete, self._delete),
                      (self.btn_restore, self._restore)):
            b.clicked.connect(fn); r1.addWidget(b)
        r1.addStretch(1)
        for txt, fn in (("폴더 열기", self._open_folder), ("새로고침", self._refresh_folder),
                        ("양식 CSV", self._write_sample)):
            b = QPushButton(txt); b.clicked.connect(fn); r1.addWidget(b)
        v.addLayout(r1)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

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
        """사전(우선순위 차례)을 다시 읽는다 — 아직 저장하지 않은 고름은 남긴다.
        새로 생긴 사전(가져오기·되살리기·새로고침)은 그 사전의 지금 상태대로(켜짐이면 오른쪽)."""
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        seen = {s["source_id"] for s in self._srcs}
        self._srcs = srcs
        ids = {s["source_id"] for s in self._srcs}
        if initial:
            self._use = {s["source_id"] for s in self._srcs if s.get("active")}
        else:
            self._use = (self._use & ids) | {s["source_id"] for s in self._srcs
                                             if s["source_id"] not in seen and s.get("active")}
        self._render()
        try:
            n_gone = len(self._store.deleted_sources())
        except Exception:
            n_gone = 0
        self.btn_restore.setEnabled(n_gone > 0)

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
            order = [s["source_id"] for s in self._store.list_sources()]
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

    # ----- 사전 파일(더하기·지우기·되살리기·폴더) — 누르면 바로 dict.db 에 쓴다 -----
    def _files_changed(self):
        self._load()
        self.changed.emit()
        if self._host is not None and hasattr(self._host, "_after_dict_list_changed"):
            try:
                self._host._after_dict_list_changed()
            except Exception:
                pass

    def _delete(self):
        from viewer.study.dict_store import USER_SOURCE_ID
        names = {s["source_id"]: (s.get("name") or s["source_id"]) for s in self._srcs}
        picked = [(sid, names.get(sid, sid)) for sid in self._ids(self.lst_wait) + self._ids(self.lst_use)
                  if sid != USER_SOURCE_ID]
        if not picked:
            self.info.setText("지울 사전을 고르세요(사용자 단어장은 지울 수 없습니다).")
            return
        lines = "\n".join(f"• {n}" for _s, n in picked[:12]) + ("\n…" if len(picked) > 12 else "")
        if QMessageBox.question(
                self, "사전 지우기",
                f"다음 사전과 그 항목을 지울까요?\n\n{lines}\n\n"
                "지운 사전은 프로그램을 다시 켜거나 [새로고침] 해도 다시 생기지 않습니다.\n"
                "되살리려면 [지운 사전 되살리기...] 를 누르세요(원본 파일은 그대로입니다).") \
                != QMessageBox.StandardButton.Yes:
            return
        for sid, _n in picked:
            try:
                self._store.delete_source(sid, remember=True)
            except Exception:
                pass
        self._files_changed()

    def _restore(self):
        gone = self._store.deleted_sources()
        if not gone:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("지운 사전 되살리기")
        lv = QVBoxLayout(dlg)
        lv.addWidget(QLabel("되살릴 사전을 고르세요. 동봉 용어집·단어장 폴더의 사전은 다시 싣고,\n"
                            "[가져오기...] 로 불러온 사전은 원본 파일을 다시 가져와야 합니다."))
        lst = QListWidget()
        for sid, name in gone.items():
            it = QListWidgetItem(str(name))
            it.setData(Qt.ItemDataRole.UserRole, sid)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            lst.addItem(it)
        lv.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lv.addWidget(bb)
        self._restore_dialog = dlg            # 검사가 잡을 수 있게
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ids = [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
               if lst.item(i).checkState() == Qt.CheckState.Checked]
        if not ids:
            return
        self._store.forget_deleted(ids)
        try:
            from viewer.study.glossary_import import load_bundled_glossaries
            load_bundled_glossaries(self._store)
        except Exception:
            pass
        try:
            from viewer.study import glossary_folder as gf
            gf.sync_folder(self._store, self._prefs)
        except Exception:
            pass
        back = {s["source_id"] for s in self._store.list_sources()}
        need = [gone[i] for i in ids if i not in back]
        self._files_changed()
        if need:
            self.info.setText("원본 파일을 다시 가져와야 하는 사전: " + ", ".join(map(str, need)))

    def _import(self):
        if self._host is not None and hasattr(self._host, "_action_import_glossary"):
            self._host._action_import_glossary()
            self._files_changed()

    def _open_folder(self):
        from viewer.study import glossary_folder as gf
        d = gf.glossaries_dir(self._prefs)
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))
        except Exception as e:
            self.info.setText(f"폴더 열기 실패: {e}")

    def _refresh_folder(self):
        from viewer.study import glossary_folder as gf
        try:
            s = gf.sync_folder(self._store, self._prefs)
            self.info.setText(f"폴더 동기화: 파일 {s['files']}개 · 갱신 {s['updated']} · "
                              f"삭제 {s['removed']}  ({s['dir']})")
        except Exception as e:
            self.info.setText(f"동기화 실패: {e}")
        self._files_changed()

    def _write_sample(self):
        from viewer.study import glossary_folder as gf
        try:
            p = gf.write_sample(prefs=self._prefs)
            self.info.setText(f"양식 저장: {p}")
            os.startfile(str(p.parent))
        except Exception as e:
            self.info.setText(f"양식 저장 실패: {e}")

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
