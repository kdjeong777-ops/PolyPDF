"""단어장 관리 다이얼로그 — 출처 on/off · 우선순위(▲▼) · 폴더 관리.

SOT: `단어장 작업 계획서.md`. dict.db 출처(여러 단어장)를 표로 관리.
- 사용 체크 — 지금 PDF 에 쓰는 출처(261103-2, 단어장 SOT §11.1: 전체 선택·전체 해제,
  '이후 PDF 에도 계속 적용' 켜짐 = 기본 선택 `enabled`, 꺼짐 = 이 PDF 의 선택), 우선순위 이동(▲▼ → priority 재배정), 종류/구분/항목수 표시.
- 폴더 열기 / 새로고침(폴더→dict.db 동기화) / 양식 CSV / 가져오기.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QCheckBox,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox,
)

_KIND_LABEL = {"user": "사용자", "base": "사전/용어집", "auto": "자동(번역)",
               "online": "인터넷"}


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
        v.addWidget(QLabel(
            "여러 단어장(출처)을 <b>사용 여부</b>와 <b>우선순위(▲▼)</b>로 관리합니다. "
            "조회 우선순위: 사용자 ▶ 사전/용어집 ▶ 자동/인터넷, 같은 종류 안에서는 위(우선)부터.<br>"
            "<small>단어장 폴더에 표준 CSV(+ meta)를 넣고 [새로고침]하면 출처로 등록됩니다.</small>"))

        # 261103-2(단어장 SOT §11.1): 지금 PDF 에 쓸 사전 — 전체 선택·전체 해제·칸마다 체크
        sel_row = QHBoxLayout()
        self.btn_all = QPushButton("전체 선택")
        self.btn_all.setToolTip("모든 단어장(출처)을 사용합니다.")
        self.btn_all.clicked.connect(lambda: self._check_all(True))
        self.btn_none = QPushButton("전체 해제")
        self.btn_none.setToolTip("모든 단어장(출처)을 쓰지 않습니다.")
        self.btn_none.clicked.connect(lambda: self._check_all(False))
        sel_row.addWidget(self.btn_all); sel_row.addWidget(self.btn_none)
        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("color:#666;")
        sel_row.addWidget(self.lbl_file, 1)
        v.addLayout(sel_row)

        body = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["사용", "종류", "구분", "출처명", "항목"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        body.addWidget(self.table, 1)

        col = QVBoxLayout()
        col.addStretch(1)
        b_up = QPushButton("▲"); b_up.setFixedWidth(40); b_up.setToolTip("우선순위 올림")
        b_dn = QPushButton("▼"); b_dn.setFixedWidth(40); b_dn.setToolTip("우선순위 내림")
        b_up.clicked.connect(lambda: self._move(-1))
        b_dn.clicked.connect(lambda: self._move(+1))
        b_del = QPushButton("삭제"); b_del.setFixedWidth(40)
        b_del.setToolTip("선택 단어장(출처) 삭제 — 사용자 단어장은 보호")
        b_del.clicked.connect(self._delete)
        col.addWidget(b_up); col.addWidget(b_dn); col.addSpacing(14); col.addWidget(b_del)
        col.addStretch(1)
        body.addLayout(col)
        v.addLayout(body, 1)

        # 261103-2: 켜면 체크 상태가 기본 선택(이후 PDF 에도), 끄면 이 PDF 에만
        self.chk_default = QCheckBox("이후 PDF 에도 계속 적용(바꿀 때까지)")
        self.chk_default.setToolTip(
            "켜면 고른 단어장을 기본으로 저장해, 따로 고르지 않은 모든 PDF 에 씁니다.\n"
            "끄면 지금 PDF 에만 적용하고 다른 PDF 는 그대로 둡니다.")
        file_path = getattr(host, "_study_pdf", None) if host is not None else None
        own = bool(host is not None and hasattr(host, "_dict_file_off")
                   and host._dict_file_off() is not None)
        self.chk_default.setChecked(not own)
        if file_path:
            self.lbl_file.setText(f"지금 PDF: {os.path.basename(str(file_path))}"
                                  + ("  (이 PDF 만의 선택)" if own else ""))
        else:
            self.lbl_file.setText("열린 PDF 없음 — 기본 선택을 고칩니다")
            self.chk_default.setEnabled(False)
        v.addWidget(self.chk_default)
        self._applied = False

        row2 = QHBoxLayout()
        for txt, fn in (("폴더 열기", self._open_folder), ("새로고침", self._refresh_folder),
                        ("양식 CSV", self._write_sample), ("가져오기…", self._import),
                        ("사용자 뜻 편집…", self._user_terms)):          # 261019-5
            b = QPushButton(txt); b.clicked.connect(fn); row2.addWidget(b)
        row2.addStretch(1)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self._on_close)
        row2.addWidget(self.btn_close)
        v.addLayout(row2)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        v.addWidget(self.info)

        self._reload()

    # ----- 표 -----
    def _checks(self) -> dict:
        """표의 체크 상태 {source_id: 켜짐}."""
        out = {}
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                out[it.data(Qt.ItemDataRole.UserRole)] = it.checkState() == Qt.CheckState.Checked
        return out

    def _check_all(self, on: bool):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                it.setCheckState(st)

    def _reload(self):
        # 261103-2: 아직 저장하지 않은 체크는 다시 그려도 남긴다(▲▼·새로고침·삭제 뒤)
        pending = self._checks()
        srcs = []
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        self.table.setRowCount(0)
        for s in srcs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable)
            on = pending.get(s.get("source_id"), s.get("active", s.get("enabled")))
            chk.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, s.get("source_id"))
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(_KIND_LABEL.get(s.get("kind"), s.get("kind") or "")))
            self.table.setItem(r, 2, QTableWidgetItem(s.get("category") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(s.get("name") or s.get("source_id") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(str(s.get("n_entries", 0))))
        self.info.setText(f"단어장(출처) {self.table.rowCount()}개")

    def _row_sid(self, r):
        it = self.table.item(r, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _move(self, direction: int):
        r = self.table.currentRow()
        if r < 0:
            return
        nr = r + direction
        if nr < 0 or nr >= self.table.rowCount():
            return
        # 표 순서대로 우선순위를 10단위 재배정(낮을수록 우선) 후 두 행 교환
        order = [self._row_sid(i) for i in range(self.table.rowCount())]
        order[r], order[nr] = order[nr], order[r]
        try:
            for i, sid in enumerate(order):
                if sid:
                    self._store.set_source_priority(sid, (i + 1) * 10)
        except Exception:
            pass
        self._reload()
        self.table.setCurrentCell(nr, 0)
        self.changed.emit()

    def _apply_enabled(self):
        """체크 상태 저장 — 단어장 SOT §11.1: '이후 PDF 에도' 켜짐 = 기본 선택, 꺼짐 = 이 PDF 에만."""
        checks = self._checks()
        if self._host is not None and hasattr(self._host, "_set_dict_selection"):
            try:
                self._host._set_dict_selection(
                    [sid for sid, on in checks.items() if on],
                    as_default=self.chk_default.isChecked())
            except Exception:
                pass
            return
        for sid, on in checks.items():
            try:
                self._store.set_source_enabled(sid, on)
            except Exception:
                pass

    def _delete(self):
        r = self.table.currentRow()
        sid = self._row_sid(r)
        if not sid:
            return
        name = self.table.item(r, 3).text() if self.table.item(r, 3) else sid
        if QMessageBox.question(self, "단어장 삭제",
                                f"'{name}' 출처와 항목을 삭제할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete_source(sid)
        except Exception:
            pass
        self._reload()
        self.changed.emit()

    # ----- 폴더 -----
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
        self._reload()
        self.changed.emit()

    def _write_sample(self):
        from viewer.study import glossary_folder as gf
        try:
            p = gf.write_sample(prefs=self._prefs)
            self.info.setText(f"양식 저장: {p}")
            os.startfile(str(p.parent))
        except Exception as e:
            self.info.setText(f"양식 저장 실패: {e}")

    def _import(self):
        if self._host is not None and hasattr(self._host, "_action_import_glossary"):
            self._host._action_import_glossary()
            self._reload()
            self.changed.emit()

    def _user_terms(self):
        if self._host is not None and hasattr(self._host, "_action_user_terms"):
            self._host._action_user_terms()
            self._reload()
            self.changed.emit()

    def _on_close(self):
        self.accept()

    def done(self, r):
        # 261103-2: 닫기·Esc·창 X 어느 길로 닫아도 체크를 저장한다(종전에는 [닫기] 만 저장했다)
        if not self._applied:
            self._applied = True
            self._apply_enabled()
            self.changed.emit()
        super().done(r)
