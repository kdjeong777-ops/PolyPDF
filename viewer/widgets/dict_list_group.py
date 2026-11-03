"""환경설정 → 고급 설정 → '사전 목록' 묶음 (261103-2, 단어장 SOT §11.1, 디자인 SOT §2.14).

프로그램이 쓸 수 있는 사전(출처)을 정한다 — 활성 체크(끄면 어느 사전 조회 길에서도 빠지고 단어장 관리 창 왼쪽 목록에서도 사라진다),
[가져오기...]·[삭제]·[지운 사전 되살리기...]·[폴더 열기]·[새로고침]·[양식 CSV].
- 활성 체크는 고급 설정 [확인] 때 `apply()` 로 저장(dict.db `dict_meta.inactive_sources`).
- 가져오기·삭제·되살리기·새로고침은 누르면 바로 dict.db 에 쓴다(확인 창이 있는 파일 작업).
- 지운 사전은 `dict_meta.deleted_sources` 에 기억 — 동봉 용어집·폴더 CSV 도 다시 싣지 않는다.
한국 전용(다국어 SOT §7) — 감싸지 않는다(`test_i18n_coverage` KOREA_ONLY).
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QMessageBox, QDialog, QListWidget, QListWidgetItem,
    QDialogButtonBox,
)

from viewer.widgets.dict_manager_dialog import _KIND_LABEL


class DictListGroup(QGroupBox):
    def __init__(self, host, parent=None):
        super().__init__("사전 목록", parent)
        self._host = host
        self._store = host._study_get_dict()
        self._prefs = getattr(host, "_prefs", {}) or {}

        v = QVBoxLayout(self)
        tip = QLabel("<small>켠(활성) 사전만 단어장 관리 창의 <b>대기 사전</b>에 나옵니다. 끄면 어디서도 쓰지 않습니다. "
                     "지운 사전은 다시 생기지 않습니다([지운 사전 되살리기...]).</small>")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["활성", "종류", "구분", "출처명", "항목"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(180)
        v.addWidget(self.table)

        r1 = QHBoxLayout()
        self.btn_import = QPushButton("가져오기...")
        self.btn_import.setToolTip("용어집 파일(PDF·CSV)을 사전으로 불러옵니다.")
        self.btn_delete = QPushButton("삭제")
        self.btn_delete.setToolTip("고른 사전과 그 항목을 지웁니다 — 사용자 단어장은 지울 수 없습니다.")
        self.btn_restore = QPushButton("지운 사전 되살리기...")
        for b, fn in ((self.btn_import, self._import), (self.btn_delete, self._delete),
                      (self.btn_restore, self._restore)):
            b.clicked.connect(fn); r1.addWidget(b)
        r1.addStretch(1)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        for txt, fn in (("폴더 열기", self._open_folder), ("새로고침", self._refresh_folder),
                        ("양식 CSV", self._write_sample)):
            b = QPushButton(txt); b.clicked.connect(fn); r2.addWidget(b)
        r2.addStretch(1)
        v.addLayout(r2)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self._reload()

    # ----- 표 -----
    def _checks(self) -> dict:
        out = {}
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                out[it.data(Qt.ItemDataRole.UserRole)] = it.checkState() == Qt.CheckState.Checked
        return out

    def _reload(self):
        pending = self._checks()          # 저장 전 체크는 다시 그려도 남긴다
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        self.table.setRowCount(0)
        for s in srcs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            sid = s.get("source_id")
            chk = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if s.get("kind") != "user":           # 사용자 단어장은 늘 활성
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            chk.setFlags(flags)
            on = pending.get(sid, not s.get("inactive"))
            chk.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, sid)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(_KIND_LABEL.get(s.get("kind"), s.get("kind") or "")))
            self.table.setItem(r, 2, QTableWidgetItem(s.get("category") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(s.get("name") or sid or ""))
            self.table.setItem(r, 4, QTableWidgetItem(str(s.get("n_entries", 0))))
        n_gone = len(self._store.deleted_sources())
        self.btn_restore.setEnabled(n_gone > 0)
        self.info.setText(f"사전 {self.table.rowCount()}개" + (f" · 지운 사전 {n_gone}개" if n_gone else ""))

    def _selected_ids(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole), self.table.item(r, 3).text())
                for r in rows]

    def _changed(self):
        if hasattr(self._host, "_after_dict_list_changed"):
            try:
                self._host._after_dict_list_changed()
            except Exception:
                pass

    def apply(self):
        """고급 설정 [확인] — 활성 체크를 저장한다."""
        off = [sid for sid, on in self._checks().items() if not on]
        try:
            self._store.set_inactive(off)
        except Exception:
            pass
        self._changed()

    # ----- 삭제·되살리기 -----
    def _delete(self):
        from viewer.study.dict_store import USER_SOURCE_ID
        picked = [(sid, name) for sid, name in self._selected_ids() if sid != USER_SOURCE_ID]
        if not picked:
            self.info.setText("지울 사전을 고르세요(사용자 단어장은 지울 수 없습니다).")
            return
        names = "\n".join(f"• {n}" for _s, n in picked[:12]) + ("\n…" if len(picked) > 12 else "")
        if QMessageBox.question(
                self, "사전 삭제",
                f"다음 사전과 그 항목을 지울까요?\n\n{names}\n\n"
                "지운 사전은 프로그램을 다시 켜거나 [새로고침] 해도 다시 생기지 않습니다.\n"
                "되살리려면 [지운 사전 되살리기...] 를 누르세요(원본 파일은 그대로입니다).") \
                != QMessageBox.StandardButton.Yes:
            return
        for sid, _n in picked:
            try:
                self._store.delete_source(sid, remember=True)
            except Exception:
                pass
        self._reload()
        self._changed()

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
        self._reload()
        if need:
            self.info.setText("원본 파일을 다시 가져와야 하는 사전: " + ", ".join(map(str, need)))
        self._changed()

    # ----- 가져오기·폴더 -----
    def _import(self):
        if hasattr(self._host, "_action_import_glossary"):
            self._host._action_import_glossary()
            self._reload()
            self._changed()

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
            self._reload()
            self.info.setText(f"폴더 동기화: 파일 {s['files']}개 · 갱신 {s['updated']} · "
                              f"삭제 {s['removed']}  ({s['dir']})")
        except Exception as e:
            self.info.setText(f"동기화 실패: {e}")
            self._reload()
        self._changed()

    def _write_sample(self):
        from viewer.study import glossary_folder as gf
        try:
            p = gf.write_sample(prefs=self._prefs)
            self.info.setText(f"양식 저장: {p}")
            os.startfile(str(p.parent))
        except Exception as e:
            self.info.setText(f"양식 저장 실패: {e}")
