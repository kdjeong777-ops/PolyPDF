"""사전 고르기 판 — 대기 사전 ↔ 적용할 사전 · 스타일 · 우선순위(▲▼) · 바로 실행 묶음.

SOT: `단어장 작업 계획서.md` §11.1 (261103-2, 261107-13·-17, 사용자 지시·결정).
같은 판(`DictManagerPanel`)을 두 곳에서 쓴다:
- 환경설정 `고급 › 사전`(mode="default") — **기본 선택**·우선순위·스타일. 저장은 환경설정 [적용]·[확인] 때
  (`result_default()` → 결과 키 `dict_default`·`dict_styles`, `MainWindow._settings_apply`). [취소] 면 버린다.
  아래 '바로 실행' 묶음 — 가져오기·내보내기·백업·복원·고급 ▾·지우기·되살리기·폴더·양식 CSV·사용자 뜻 편집 — 은 누르면 바로 dict.db 에 쓴다.
- 단어장 창 `이 PDF 사전` 단추 → `DictFileDialog`(mode="file") — **이 PDF 의 선택**. 창을 닫을 때 저장(`dict_file_off`).
스타일 줄([저장]·[수정]·[삭제])은 두 판 모두 — 기본 판은 [적용] 때, 이 PDF 판은 누르면 바로 `dict_styles` 에(261107-25).
'삭제' 는 적용 목록에서 빼기 — 사전은 지우지 않는다. 지운 사전은 `dict_meta.deleted_sources` 에 기억 — 동봉 용어집·폴더 CSV 도 다시 싣지 않는다.
(261107-17: 종전 '사전 관리' 창·도구 탭 단추는 없앴다 — 사용자 결정 '환경설정의 외부 연결 아래에')
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QGroupBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QMessageBox, QInputDialog,
    QDialogButtonBox, QMenu,
)

_KIND_LABEL = {"user": "사용자", "base": "사전/용어집", "auto": "자동(번역)",
               "online": "인터넷"}
_STYLE_NONE = "(스타일 고르기)"
RUN_NOW_TITLE = "바로 실행 — 누르면 바로 실행되며 [취소]로 되돌리지 않습니다"


def source_label(s: dict) -> str:
    """목록 한 줄 — '이름  (종류 / 구분, 항목 수)'."""
    kind = _KIND_LABEL.get(s.get("kind"), s.get("kind") or "")
    cat = (s.get("category") or "").strip()
    meta = kind + (f" / {cat}" if cat else "")
    return f"{s.get('name') or s.get('source_id')}  ({meta}, {s.get('n_entries', 0)})"


class DictManagerPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, store, prefs: dict = None, host=None, mode: str = "default", parent=None):
        super().__init__(parent)
        self._store = store
        self._prefs = prefs or {}
        self._host = host
        self.mode = mode
        is_def = (mode == "default")
        # 스타일 — 기본 판은 [적용] 때 저장하려고 사본을 들고 있다(디자인 SOT §2.14 [취소] 규칙)
        self._styles = [dict(s) for s in (host._dict_styles() if host is not None and hasattr(host, "_dict_styles") else [])]

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        grp = QGroupBox("기본 사전 (모든 PDF)" if is_def else "이 PDF 에 쓸 사전")
        gv = QVBoxLayout(grp)
        intro = QLabel(
            ("따로 고르지 않은 <b>모든 PDF</b> 에 쓸 사전을 오른쪽으로 옮깁니다. 오른쪽 차례가 <b>우선순위</b>입니다"
             "(사용자 ▶ 사전/용어집 ▶ 자동/인터넷 안에서 위부터).<br>"
             "<small>한 PDF 에만 따로 고르려면 단어장 창의 [이 PDF 사전]. [← 삭제] 는 적용 목록에서 빼기만 합니다.</small>")
            if is_def else
            ("지금 PDF 에만 쓸 사전을 오른쪽으로 옮깁니다 — 다른 PDF·기본 선택은 그대로입니다.<br>"
             "<small>우선순위는 환경설정 › 고급 › 사전. 스타일은 여기서 바꾸면 바로 저장됩니다.</small>"))
        intro.setWordWrap(True)
        gv.addWidget(intro)

        # ── 스타일 ──
        st = QHBoxLayout()
        st.addWidget(QLabel("스타일"))
        self.cmb_style = QComboBox()
        self.cmb_style.setToolTip("저장해 둔 사전 조합 — 고르면 오른쪽 목록이 그 조합으로 바뀝니다.")
        self.cmb_style.activated.connect(self._on_style_chosen)
        st.addWidget(self.cmb_style, 1)
        self.btn_style_save = QPushButton("저장")
        self.btn_style_save.setToolTip("오른쪽 목록의 조합을 새 스타일로 저장합니다.")
        self.btn_style_save.clicked.connect(self._style_save)
        self.btn_style_edit = QPushButton("수정")            # 261107-25
        self.btn_style_edit.setToolTip("고른 스타일을 지금 오른쪽 목록으로 바꿉니다(이름도 고칠 수 있습니다).")
        self.btn_style_edit.clicked.connect(self._style_edit)
        self.btn_style_del = QPushButton("삭제")
        self.btn_style_del.setToolTip("고른 스타일을 지웁니다(사전은 그대로).")
        self.btn_style_del.clicked.connect(self._style_delete)
        for b in (self.btn_style_save, self.btn_style_edit, self.btn_style_del):
            st.addWidget(b)
        self.cmb_style.currentIndexChanged.connect(lambda _i: self._style_buttons())
        gv.addLayout(st)

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
        self.btn_up.setVisible(is_def); self.btn_dn.setVisible(is_def)
        for lst in (self.lst_wait, self.lst_use):
            lst.setMinimumHeight(160)
        gv.addLayout(body, 1)
        v.addWidget(grp, 1)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        self.info.setWordWrap(True)
        self.grp_run = None
        if is_def:
            self._build_run_now(v)
        else:
            v.addWidget(self.info)

        self._srcs: list[dict] = []
        self._use: set = set()
        self._load(initial=True)
        self._reload_styles()

    # ── 바로 실행 묶음(기본 판만) ──
    def _build_run_now(self, v):
        grp = QGroupBox(RUN_NOW_TITLE)
        self.grp_run = grp
        gv = QVBoxLayout(grp)
        r0 = QHBoxLayout()
        self.btn_import = QPushButton("가져오기")
        self.btn_import.setToolTip("용어집 파일 하나(PDF·CSV)를 새 사전으로 더합니다.")
        self.btn_export = QPushButton("내보내기")
        self.btn_export.setToolTip("사전 하나 또는 전체를 다른 프로그램용 파일(TBX·CSV)로 저장합니다.")
        self.btn_backup = QPushButton("백업")
        self.btn_backup.setToolTip("사전 전체(용어·사용자 뜻·그림·인터넷 캐시)를 zip 한 파일로 저장합니다 — 다른 PC 로 옮길 때.")
        self.btn_restore_all = QPushButton("복원")
        self.btn_restore_all.setToolTip("[백업] 한 zip 으로 지금 사전 전체를 바꿉니다(옛 것은 .bak 으로 둡니다).")
        for b, fn in ((self.btn_import, self._import), (self.btn_export, self._export),
                      (self.btn_backup, self._backup), (self.btn_restore_all, self._restore_all)):
            b.clicked.connect(fn); r0.addWidget(b)
        self.btn_adv = QPushButton("고급 ▾")
        self.btn_adv.setToolTip("고치거나 다시 받을 때만 쓰는 일")
        adv = QMenu(self.btn_adv)
        self.act_sanitize = adv.addAction("사전 정리 (HTML 마크업 제거)")
        self.act_sanitize.triggered.connect(lambda _c=False: self._host_call("_action_sanitize_dict"))
        self.act_reclassify = adv.addAction("온용어 다시 분류")
        self.act_reclassify.setToolTip("인터넷 온용어 캐시를 비우고 다시 받아 용어집별로 나눕니다(인터넷 사용)")
        self.act_reclassify.triggered.connect(lambda _c=False: self._host_call("_action_reclassify_onterm"))
        self.btn_adv.setMenu(adv)
        r0.addWidget(self.btn_adv)
        r0.addStretch(1)
        gv.addLayout(r0)
        r1 = QHBoxLayout()
        self.btn_delete = QPushButton("사전 지우기")
        self.btn_delete.setToolTip("고른 사전과 그 항목을 지웁니다(어느 목록에서 골라도) — 사용자 단어장은 지울 수 없습니다.")
        self.btn_restore = QPushButton("지운 사전 되살리기")
        for b, fn in ((self.btn_delete, self._delete), (self.btn_restore, self._restore)):
            b.clicked.connect(fn); r1.addWidget(b)
        r1.addStretch(1)
        for txt, fn, tip in (("폴더 열기", self._open_folder, "단어장 폴더 — 여기 둔 CSV 는 [새로고침] 때 사전이 됩니다"),
                             ("새로고침", self._refresh_folder, "단어장 폴더의 CSV 를 다시 읽습니다"),
                             ("양식 CSV", self._write_sample, "양식 예제 CSV 를 단어장 폴더에 만들고 폴더를 엽니다")):
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn); r1.addWidget(b)
        self.btn_user = QPushButton("사용자 뜻 편집")          # 261019-5
        self.btn_user.setToolTip("내가 고치거나 더한 뜻만 불러 고칩니다")
        self.btn_user.clicked.connect(self._user_terms)
        r1.addWidget(self.btn_user)
        gv.addLayout(r1)
        gv.addWidget(self.info)
        v.addWidget(grp)
        has_host = self._host is not None
        for w in (self.btn_import, self.btn_export, self.btn_backup, self.btn_restore_all, self.btn_adv, self.btn_user):
            w.setEnabled(has_host)

    # ----- 목록 -----
    @staticmethod
    def _make_list() -> QListWidget:
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        return lst

    def _load(self, initial: bool = False):
        """사전을 다시 읽는다 — 아직 저장하지 않은 고름·차례는 남긴다.
        새로 생긴 사전(가져오기·되살리기·새로고침)은 그 사전의 지금 상태대로(켜짐이면 오른쪽), 차례는 끝에.
        기본 판은 기본 선택(`enabled`), 이 PDF 판은 지금 PDF 에 쓰는 것(`active`)."""
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        flag = "enabled" if self.mode == "default" else "active"
        on = lambda s: bool(s.get(flag, s.get("enabled", 1)))
        if initial:
            self._srcs = srcs
            self._use = {s["source_id"] for s in srcs if on(s)}
        else:
            seen = [s["source_id"] for s in self._srcs]
            by = {s["source_id"]: s for s in srcs}
            self._srcs = [by[i] for i in seen if i in by] + [s for s in srcs if s["source_id"] not in seen]
            self._use = (self._use & set(by)) | {i for i, s in by.items() if i not in seen and on(s)}
        self._render()
        if hasattr(self, "btn_restore"):
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

    def order_ids(self) -> list:
        """모든 사전의 우선순위 차례(▲▼ 를 반영한 판 안의 차례)."""
        return [s["source_id"] for s in self._srcs]

    def result_default(self) -> dict:
        """환경설정 결과 — `MainWindow._settings_apply` → `StudyMixin._apply_dict_default`."""
        return {"use": self.use_ids(), "order": self.order_ids()}

    def styles(self) -> list:
        return [dict(s) for s in self._styles]

    def _changed(self):
        self.changed.emit()

    def _add(self):
        moved = set(self._ids(self.lst_wait))
        self._use |= moved
        self._render(moved)
        self._changed()

    def _remove(self):
        moved = set(self._ids(self.lst_use))
        self._use -= moved
        self._render(moved)
        self._changed()

    def _move_all(self, to_use: bool):
        self._use = {s["source_id"] for s in self._srcs} if to_use else set()
        self._render()
        self._changed()

    def _move(self, direction: int):
        """오른쪽 목록에서 고른 사전을 한 칸 — 판 안의 우선순위 차례만 바꾼다([적용] 때 저장)."""
        cur = self.lst_use.currentItem()
        if cur is None:
            return
        sid = cur.data(Qt.ItemDataRole.UserRole)
        right = self.use_ids()
        r = right.index(sid)
        nr = r + direction
        if nr < 0 or nr >= len(right):
            return
        order = self.order_ids()
        i, j = order.index(sid), order.index(right[nr])
        self._srcs[i], self._srcs[j] = self._srcs[j], self._srcs[i]
        self._render({sid})
        self._changed()

    # ----- 스타일 -----
    def _reload_styles(self, current: str = ""):
        self.cmb_style.blockSignals(True)
        self.cmb_style.clear()
        self.cmb_style.addItem(_STYLE_NONE)
        for s in self._styles:
            self.cmb_style.addItem(s["name"])
        i = self.cmb_style.findText(current) if current else -1
        self.cmb_style.setCurrentIndex(i if i > 0 else 0)
        self.cmb_style.blockSignals(False)
        self._style_buttons()

    def _style_buttons(self):
        """[수정]·[삭제] 는 스타일을 고른 동안만."""
        on = self.cmb_style.currentIndex() > 0
        self.btn_style_edit.setEnabled(on)
        self.btn_style_del.setEnabled(on)

    def _style_names(self) -> list:
        return [s["name"] for s in self._styles]

    def _ask_overwrite(self, name: str) -> bool:
        return QMessageBox.question(self, "스타일 저장", f"'{name}' 스타일이 이미 있습니다. 덮어쓸까요?")             == QMessageBox.StandardButton.Yes

    def _put_style(self, name: str, old: str = ""):
        """이름 `name` 으로 오른쪽 목록을 넣는다 — `old` 가 있으면 그 자리에서 바꾼다(수정)."""
        item = {"name": name, "sources": self.use_ids()}
        out, placed = [], False
        for s in self._styles:
            if s["name"] == (old or name):
                out.append(item); placed = True
            elif s["name"] != name:
                out.append(s)
        if not placed:
            out.append(item)
        self._styles = out
        self._commit_styles(name)

    def _commit_styles(self, current: str = ""):
        """기본 판: [적용] 때 저장(판 안의 사본만). 이 PDF 판: 바로 settings `dict_styles` 에(단어장 SOT §11.1)."""
        self._reload_styles(current)
        if self.mode != "default" and self._host is not None and hasattr(self._host, "_set_dict_styles"):
            self._host._set_dict_styles(self.styles())
        else:
            self._changed()

    def _on_style_chosen(self, index: int):
        if index <= 0:
            return
        name = self.cmb_style.itemText(index)
        st = next((s for s in self._styles if s["name"] == name), None)
        live = {s["source_id"] for s in self._srcs}
        self._use = {sid for sid in (st or {}).get("sources") or [] if sid in live}   # 지운 사전은 건너뛴다
        self._render()
        self._changed()

    def _style_save(self):
        cur = self.cmb_style.currentText() if self.cmb_style.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(self, "스타일 저장", "새 스타일 이름:", text=cur)
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self._style_names() and not self._ask_overwrite(name):
            return
        self._put_style(name)

    def _style_edit(self):
        """고른 스타일을 지금 오른쪽 목록으로 — 이름 칸을 고치면 이름도 바뀐다(261107-25)."""
        if self.cmb_style.currentIndex() <= 0:
            return
        old = self.cmb_style.currentText()
        name, ok = QInputDialog.getText(self, "스타일 수정",
                                        "스타일 이름(지금 오른쪽 목록으로 바꿉니다):", text=old)
        name = (name or "").strip()
        if not ok or not name:
            return
        if name != old and name in self._style_names() and not self._ask_overwrite(name):
            return
        self._put_style(name, old=old)

    def _style_delete(self):
        if self.cmb_style.currentIndex() <= 0:
            return
        name = self.cmb_style.currentText()
        if QMessageBox.question(self, "스타일 삭제", f"'{name}' 스타일을 지울까요?\n(사전은 그대로입니다)") \
                != QMessageBox.StandardButton.Yes:
            return
        self._styles = [s for s in self._styles if s["name"] != name]
        self._commit_styles()

    # ----- 바로 실행 — 누르면 바로 dict.db 에 쓴다 -----
    def _files_changed(self, reset: bool = False):
        self._load(initial=reset)
        self._changed()
        if self._host is not None and hasattr(self._host, "_after_dict_list_changed"):
            try:
                self._host._after_dict_list_changed()
            except Exception:
                pass

    def _host_call(self, name: str, reopen: bool = False, reset: bool = False):
        """앱의 사전 동작을 부르고 목록을 고친다. reopen — 백업·복원은 화면 스레드 사전 연결을 닫으므로 다시 연다.
        reset — 복원은 사전 전체가 바뀌므로 판의 고름도 복원한 사전 그대로로."""
        fn = getattr(self._host, name, None) if self._host is not None else None
        if fn is None:
            return
        fn()
        if reopen and hasattr(self._host, "_study_get_dict"):
            try:
                self._store = self._host._study_get_dict()
            except Exception:
                pass
        self._files_changed(reset=reset)

    def _import(self):
        self._host_call("_action_import_glossary")

    def _export(self):
        self._host_call("_action_export_dict")

    def _backup(self):
        self._host_call("_action_backup_dict", reopen=True)

    def _restore_all(self):
        self._host_call("_action_restore_dict", reopen=True, reset=True)

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
                "되살리려면 [지운 사전 되살리기] 를 누르세요(원본 파일은 그대로입니다).") \
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
                            "[가져오기] 로 불러온 사전은 원본 파일을 다시 가져와야 합니다."))
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
            # 261107-13(단어장 SOT §11.1): 양식은 이 한 길
            self.info.setText(f"양식 저장: {p}\n열: term_ko(한글 표제어)·term_en(영문 표제어)·def_ko·def_en(뜻)·"
                              "examples(예시)·reference(참고문헌)·level(난이도)·hanja(한자) — 고쳐 넣고 [새로고침]")
            os.startfile(str(p.parent))
        except Exception as e:
            self.info.setText(f"양식 저장 실패: {e}")

    def _user_terms(self):
        if self._host is not None and hasattr(self._host, "_action_user_terms"):
            self._host._action_user_terms()
            self._load()
            self._changed()


def attach_settings(dlg, layout) -> DictManagerPanel | None:
    """환경설정 `고급 › 사전` 쪽에 기본 판을 붙인다(디자인 SOT §2.14 — `add_result_fn`·`mark_changed`)."""
    host = getattr(dlg, "_host", None)
    if host is None or not hasattr(host, "_study_get_dict"):
        dlg.dict_panel = None
        layout.addWidget(QLabel("사전 정보가 없습니다."))
        return None
    panel = DictManagerPanel(host._study_get_dict(), getattr(host, "_prefs", {}) or {}, host=host, mode="default")
    layout.addWidget(panel, 1)
    panel.changed.connect(dlg.mark_changed)
    dlg.dict_panel = panel
    fn = lambda: {"dict_default": panel.result_default(), "dict_styles": panel.styles()}
    if hasattr(dlg, "_applied"):
        dlg.add_result_fn(fn)
    else:                                   # 쪽을 만드는 중 — 뒤 쪽이 아직 없어 목록에만 건다(창이 끝에 한 번 잰다)
        dlg._extra_results.append(fn)
    return panel


class DictFileDialog(QDialog):
    """단어장 창 `이 PDF 사전` — 지금 PDF 에만 쓸 사전(단어장 SOT §11.1). 어느 길로 닫아도 저장한다.
    [기본 선택 따르기] = 이 PDF 의 선택을 지우고 닫는다."""

    def __init__(self, store, prefs: dict = None, host=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이 PDF 의 사전")
        self.setMinimumSize(640, 400)
        self._host = host
        v = QVBoxLayout(self)
        path = getattr(host, "_study_pdf", None) if host is not None else None
        own = bool(host is not None and hasattr(host, "_dict_file_off") and host._dict_file_off() is not None)
        self.lbl_file = QLabel(("지금 PDF: " + os.path.basename(str(path)) if path else "열린 PDF 없음")
                               + ("  (이 PDF 만의 선택)" if own else "  (지금은 기본 선택을 따름)"))
        self.lbl_file.setStyleSheet("color:#666;")
        v.addWidget(self.lbl_file)
        self.panel = DictManagerPanel(store, prefs, host=host, mode="file", parent=self)
        v.addWidget(self.panel, 1)
        row = QHBoxLayout()
        self.btn_follow = QPushButton("기본 선택 따르기")
        self.btn_follow.setToolTip("이 PDF 만의 선택을 지웁니다 — 환경설정 › 고급 › 사전의 기본 선택을 씁니다.")
        self.btn_follow.clicked.connect(self._follow_default)
        row.addWidget(self.btn_follow)
        row.addStretch(1)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_close)
        v.addLayout(row)
        self._saved = False

    def _follow_default(self):
        self._saved = True
        if self._host is not None and hasattr(self._host, "_clear_dict_file_sel"):
            self._host._clear_dict_file_sel()
        self.accept()

    def done(self, r):
        # 닫기·Esc·창 X 어느 길로 닫아도 저장한다(261103-2)
        if not self._saved:
            self._saved = True
            key = self._host._dict_file_key() if self._host is not None and hasattr(self._host, "_dict_file_key") else None
            if key and hasattr(self._host, "_set_dict_selection"):      # 열린 PDF 가 없으면 저장하지 않는다(기본 선택을 건드리지 않게)
                try:
                    self._host._set_dict_selection(self.panel.use_ids(), as_default=False)
                except Exception:
                    pass
        super().done(r)

    def __getattr__(self, name):            # 검사·호출 편의 — 판의 목록·단추를 그대로
        panel = self.__dict__.get("panel")
        if panel is not None and not name.startswith("__"):
            return getattr(panel, name)
        raise AttributeError(name)
