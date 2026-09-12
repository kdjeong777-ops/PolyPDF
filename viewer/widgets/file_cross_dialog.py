# -*- coding: utf-8 -*-
"""260912-5: 파일 경계를 넘기 전에 묻는 창 (입력 장치 SOT §2.4).

사용자 지시: "PDF 마지막 페이지에서 다음 PDF 로 넘어갈 때, 발표 화면과 유사하게
다음 PDF 의 파일명(확장자 제외)을 보여 주고 다음 PDF 를 볼 건지 물어보는 창을 띄워."

쪽이 넘어가는 것과 **파일이 바뀌는 것**은 무게가 다르다 — 파일이 바뀌면 보던 자리·
확대율·선택이 모두 새 문서의 것으로 갈린다. 그래서 한 번 묻는다.

이 창은 **묻기만** 한다. 언제 묻고 언제 묻지 않는지는 SOT §2.4 가 정한다.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QDialogButtonBox,
                             QFrame)

PREVIEW_W = 220         # 미리보기 최대 가로(px) — 창이 본문을 가리지 않을 만큼만
PREVIEW_H = 300
PREVIEW_DPI = 72        # 이 크기에 넉넉하다. 더 올려도 눈에 띄지 않고 느려진다


def _preview(path, last_page: bool):
    """그 파일의 첫(또는 마지막) 쪽을 작은 그림으로. 실패하면 None.

    **실패해도 물음은 뜬다** — 그림 때문에 물음이 사라지면 안 된다(SOT §2.4).
    """
    doc = None
    try:
        from viewer.pdf_doc import PdfDocument
        doc = PdfDocument(str(path))
        n = int(doc.page_count)
        if n <= 0:
            return None
        rp = doc.render_thumbnail((n - 1) if last_page else 0, dpi=PREVIEW_DPI)
        img = QImage(rp.samples, rp.width, rp.height,
                     rp.width * 3, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img.copy())      # copy: 원본 버퍼가 사라져도 살아 있게
        if pm.width() > PREVIEW_W or pm.height() > PREVIEW_H:
            pm = pm.scaled(PREVIEW_W, PREVIEW_H,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        return pm
    except Exception:
        return None
    finally:
        try:
            if doc is not None:
                doc.close()                     # 붙들고 있지 않는다
        except Exception:
            pass


class FileCrossDialog(QDialog):
    """다음/이전 PDF 로 넘어갈지 묻는다. `exec()` 가 참이면 넘어간다."""

    def __init__(self, parent=None, *, path, forward: bool):
        super().__init__(parent)
        self._forward = bool(forward)
        stem = Path(str(path)).stem             # 확장자를 뺀 이름(사용자 지시)
        self.setWindowTitle("다음 PDF 로" if self._forward else "이전 PDF 로")

        v = QVBoxLayout(self)
        v.setSpacing(10)

        head = QLabel("다음 PDF 를 볼까요?" if self._forward
                      else "이전 PDF 를 볼까요?")
        f = head.font()
        f.setBold(True)
        f.setPointSize(max(10, f.pointSize() + 1))
        head.setFont(f)
        v.addWidget(head)

        name = QLabel(stem)
        name.setObjectName("crossFileName")
        name.setWordWrap(True)
        nf = name.font()
        nf.setPointSize(max(10, nf.pointSize() + 2))
        name.setFont(nf)
        v.addWidget(name)

        pm = _preview(path, last_page=not self._forward)
        if pm is not None:
            shot = QLabel()
            shot.setPixmap(pm)
            shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shot.setFrameShape(QFrame.Shape.Box)
            v.addWidget(shot, 0, Qt.AlignmentFlag.AlignCenter)
            cap = QLabel("첫 쪽" if self._forward else "마지막 쪽")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet("color:#888;")
            v.addWidget(cap)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes
                               | QDialogButtonBox.StandardButton.No)
        self.btn_yes = box.button(QDialogButtonBox.StandardButton.Yes)
        self.btn_no = box.button(QDialogButtonBox.StandardButton.No)
        self.btn_yes.setText("예")
        self.btn_no.setText("아니오")
        self.btn_yes.setDefault(True)           # 누르던 흐름을 잇는 쪽이 기본
        self.btn_yes.setAutoDefault(True)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)       # Esc = 아니오
        v.addWidget(box)
