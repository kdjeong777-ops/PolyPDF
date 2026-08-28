"""이미지 파일 → PDF 변환 다이얼로그 (260825-13).

좌측: 파일 목록(다중선택/드래그앤드롭 추가·순서변경·삭제), 우측: 선택 파일 미리보기.
다단(N-up) 저장은 인쇄·PDF병합과 동일한 twoup 엔진을 재사용.
"""
from __future__ import annotations

import os
import re

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel,
    QPushButton, QDialogButtonBox, QCheckBox, QComboBox, QWidget, QFileDialog,
    QAbstractItemView,
)

from viewer.widgets.nup_preset import NupPresetMixin   # 260628: 다단 프리셋 공통(SOT §11.10)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
_PATH_ROLE = Qt.ItemDataRole.UserRole


def _natural_key(path: str):
    """파일명 자연정렬 키(img2 < img10). 경로는 basename 기준."""
    name = os.path.basename(str(path)).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


class _DropList(QListWidget):
    """외부 파일 드래그앤드롭 추가 + 내부 순서변경(InternalMove) 겸용 목록."""

    def __init__(self, on_files, parent=None):
        super().__init__(parent)
        self._on_files = on_files
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(56, 56))
        self.setUniformItemSizes(False)

    def _urls(self, e):
        md = e.mimeData()
        if md is not None and md.hasUrls():
            return [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        return []

    def dragEnterEvent(self, e):
        if self._urls(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._urls(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        paths = self._urls(e)
        if paths:
            self._on_files(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)          # 내부 순서변경


class ImageToPdfDialog(NupPresetMixin, QDialog):
    def __init__(self, parent=None, initial_paths=None, preset_api=None, sample=None):
        super().__init__(parent)
        self.setWindowTitle("이미지 → PDF 변환")
        self.resize(860, 580)
        self._preset_api = preset_api
        self._sample = sample
        self._nup_settings = {"make_cover": False, "make_toc": False}

        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ── 좌측: 목록 + 조작 버튼 ──
        left = QVBoxLayout()
        left.addWidget(QLabel("이미지 목록 (위→아래 = 페이지 순서, 드래그로 순서 변경)"))
        self.lst = _DropList(self._add_files, self)
        self.lst.currentItemChanged.connect(lambda *_: self._update_preview())
        left.addWidget(self.lst, 1)
        lb = QHBoxLayout()
        for txt, fn, tip in (
            ("파일 추가", self._pick_files, "이미지 파일 선택(여러 개 가능)"),
            ("삭제", self._remove_sel, "선택 항목 삭제"),
            ("전체삭제", self._clear_all, "목록 비우기"),
            ("▲", lambda: self._move(-1), "위로 이동"),
            ("▼", lambda: self._move(1), "아래로 이동"),
        ):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            lb.addWidget(b)
        left.addLayout(lb)
        lw = QWidget()
        lw.setLayout(left)
        body.addWidget(lw, 3)

        # ── 우측: 미리보기 ──
        right = QVBoxLayout()
        right.addWidget(QLabel("미리보기"))
        self.preview = QLabel("파일을 선택하면 미리보기가 표시됩니다.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(340)
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            "background:#f4f4f4;border:1px solid #cccccc;color:#888888;")
        right.addWidget(self.preview, 1)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#555555;")
        right.addWidget(self.info)
        rw = QWidget()
        rw.setLayout(right)
        body.addWidget(rw, 2)

        # ── 다단 옵션 ──
        nrow = QHBoxLayout()
        self.chk_nup = QCheckBox("다단 저장")
        self.chk_nup.toggled.connect(lambda on: self.btn_nup.setEnabled(on))
        self.cmb_preset = QComboBox()
        self.cmb_preset.setMinimumWidth(150)
        self._reload_presets()
        self.cmb_preset.activated.connect(self._on_preset_pick)
        self.btn_nup = QPushButton("설정")
        self.btn_nup.setEnabled(False)
        self.btn_nup.clicked.connect(self._open_nup)
        nrow.addWidget(self.chk_nup)
        nrow.addWidget(QLabel("스타일:"))
        nrow.addWidget(self.cmb_preset, 1)
        nrow.addWidget(self.btn_nup)
        root.addLayout(nrow)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = bb.addButton("PDF로 저장", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.clicked.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        if initial_paths:
            self._add_files(initial_paths)

    # ----- 목록 조작 -----
    def _existing(self) -> set:
        return {self.lst.item(i).data(_PATH_ROLE) for i in range(self.lst.count())}

    def _add_files(self, paths):
        exist = self._existing()
        news = []
        for p in (paths or []):
            p = str(p)
            if (p and p.lower().endswith(IMAGE_EXTS) and os.path.isfile(p)
                    and p not in exist):
                news.append(p)
                exist.add(p)
        news.sort(key=_natural_key)          # 여러 개 한 번에 추가 시 파일명 순
        for p in news:
            it = QListWidgetItem(os.path.basename(p))
            it.setData(_PATH_ROLE, p)
            it.setToolTip(p)
            pm = QPixmap(p)
            if not pm.isNull():
                it.setIcon(QIcon(pm.scaled(
                    56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)))
            self.lst.addItem(it)
        if news and self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "이미지 파일 선택", "",
            "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
        if paths:
            self._add_files(paths)

    def _remove_sel(self):
        for it in self.lst.selectedItems():
            self.lst.takeItem(self.lst.row(it))
        self._update_preview()

    def _clear_all(self):
        self.lst.clear()
        self._update_preview()

    def _move(self, delta):
        row = self.lst.currentRow()
        if row < 0:
            return
        new = row + delta
        if new < 0 or new >= self.lst.count():
            return
        it = self.lst.takeItem(row)
        self.lst.insertItem(new, it)
        self.lst.setCurrentRow(new)

    def _update_preview(self):
        it = self.lst.currentItem()
        if it is None:
            self.preview.setText("파일을 선택하면 미리보기가 표시됩니다.")
            self.preview.setPixmap(QPixmap())
            self.info.setText("")
            return
        path = it.data(_PATH_ROLE)
        pm = QPixmap(path)
        if pm.isNull():
            self.preview.setText("미리보기를 불러올 수 없습니다.")
            self.info.setText(os.path.basename(path))
            return
        area = self.preview.size()
        w = max(200, area.width() - 8)
        h = max(200, area.height() - 8)
        self.preview.setPixmap(pm.scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        try:
            kb = os.path.getsize(path) // 1024
        except Exception:
            kb = 0
        self.info.setText(f"{os.path.basename(path)}  ·  {pm.width()}×{pm.height()}px  ·  {kb:,} KB")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_preview()

    # ----- 결과/다단 -----
    def result_paths(self) -> list:
        return [self.lst.item(i).data(_PATH_ROLE) for i in range(self.lst.count())]

    # nup_enabled() 는 NupPresetMixin 제공(260628).

    def nup_settings(self) -> dict:
        from viewer.twoup import merge_twoup_settings
        s = merge_twoup_settings(self._nup_settings)
        s["enabled"] = True
        return s

    # 260628: _reload_presets/_on_preset_pick/_open_nup 은 NupPresetMixin 공통(SOT §11.10).
