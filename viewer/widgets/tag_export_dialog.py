# -*- coding: utf-8 -*-
"""해시태그 폴더로 사본 저장 (태그 SOT §8.8, 261111-8).

고른 태그마다 `<폴더>\\<태그>\\` 를 만들고 그 태그를 가진 목록의 파일을 사본으로 넣는다(같은 이름은 '이름 (2)').
창은 고르기만 — 파일 작업은 부른 쪽(`MainWindow._tag_export_run`)이 배경에서.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout)

from viewer.i18n import tr

_BAD = re.compile(r'[\\/:*?"<>|]')


def folder_name(tag: str) -> str:
    """태그 → 폴더 이름(쓸 수 없는 글자는 `_`, 끝의 점·빈칸은 뺀다)."""
    s = _BAD.sub("_", str(tag or "").strip()).rstrip(". ")
    return s or "_"


def plan(store, paths, tags) -> list:
    """[(원본, 태그 폴더 안 대상 이름)] — 태그 여럿을 가진 파일은 고른 태그마다 하나씩."""
    out = []
    for t in tags:
        tl = t.lower()
        for p in paths:
            if tl in {x.lower() for x in store.get(p)}:
                out.append((str(p), folder_name(t)))
    return out


def copy_job(items, dst_root, progress=None, done=None) -> list:
    """배경에서 — 사본을 만들고 [(원본, 사본)] 을 `done` 에 쌓아 돌려준다. 이름이 겹치면 '이름 (2)'(덮어쓰지 않는다).
    `progress(했음, 전체, 글)` 가 False 를 돌려주면(취소) 거기서 멈춘다 — 만든 사본은 남는다."""
    from viewer.pathutil import unique_path
    done = [] if done is None else done
    n = len(items)
    for i, (src, sub) in enumerate(items):
        d = Path(dst_root) / sub
        d.mkdir(parents=True, exist_ok=True)
        tgt = unique_path(d / Path(src).name, first=2)
        tmp = tgt.with_name(tgt.name + ".polypdf-tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, tgt)
        done.append((src, str(tgt)))
        if progress is not None and progress(i + 1, n, Path(src).name) is False:
            break
    return done


class TagExportDialog(QDialog):
    def __init__(self, store, paths, parent=None, start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("해시태그 폴더로 사본 저장"))
        self.resize(460, 520)
        self._store, self._paths = store, [str(p) for p in paths]
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr("저장할 해시태그를 고르세요. 고른 태그마다 폴더를 만들고 그 태그를 가진 파일의 사본을 넣습니다.")))
        self.lst = QListWidget()
        counts = {}
        for p in self._paths:
            for t in store.get(p):
                counts[t] = counts.get(t, 0) + 1
        for t in sorted(counts, key=lambda t: (-counts[t], t.lower())):
            it = QListWidgetItem(tr("#{tag}  ({n}개)").format(tag=t, n=counts[t]))
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.lst.addItem(it)
        v.addWidget(self.lst, 1)
        v.addWidget(QLabel(tr("저장할 폴더")))
        h = QHBoxLayout()
        self.ed_dir = QLineEdit(start_dir)
        b = QPushButton(tr("찾아보기…"))
        b.clicked.connect(self._pick)
        h.addWidget(self.ed_dir, 1)
        h.addWidget(b)
        v.addLayout(h)
        v.addWidget(QLabel("<small>%s</small>" % tr("같은 이름이 있으면 '이름 (2)' 로 저장합니다. 사본에도 해시태그·OCR 결과가 따라갑니다.")))
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        v.addWidget(self.bb)
        self.lst.itemChanged.connect(self._sync)
        self.ed_dir.textChanged.connect(self._sync)
        self._sync()

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, tr("저장할 폴더"), self.ed_dir.text() or "")
        if d:
            self.ed_dir.setText(d)

    def tags(self) -> list:
        return [self.lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).checkState() == Qt.CheckState.Checked]

    def dest(self) -> str:
        return self.ed_dir.text().strip()

    def _sync(self, *_a):
        self.bb.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(self.tags()) and os.path.isdir(self.dest()))
