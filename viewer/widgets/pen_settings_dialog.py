"""260609-16 (F3): 발표 펜(사용자선 1~3) 설정 — 명칭·색·굵기·단축키."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QColorDialog, QGroupBox, QSpinBox, QKeySequenceEdit,
)


class _ColorBtn(QPushButton):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 24)
        self._color = QColor(color)
        self._apply()
        self.clicked.connect(self._pick)

    def _apply(self):
        self.setStyleSheet(
            f"background:{self._color.name()};border:1px solid #888;border-radius:4px;")

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "선 색 선택")
        if c.isValid():
            self._color = c
            self._apply()

    def color_name(self):
        return self._color.name()


class PenSettingsDialog(QDialog):
    def __init__(self, pens, pen_keys, parent=None, eraser_widths=None):
        super().__init__(parent)
        self.setWindowTitle("발표 선(펜) 설정")
        self.resize(470, 360)
        self._rows = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("발표 중 마우스 왼쪽 드래그로 선을 긋습니다. 색·굵기·단축키 설정:"))
        keys = list(pen_keys or [])
        for i, pr in enumerate(pens):
            grp = QGroupBox(f"사용자선 {i + 1}")
            h = QHBoxLayout(grp)
            h.addWidget(QLabel("명칭:"))
            ed = QLineEdit(pr.get("name", f"사용자선 {i + 1}"))
            h.addWidget(ed, 1)
            h.addWidget(QLabel("색:"))
            cb = _ColorBtn(pr.get("color", "#ff3030"))
            h.addWidget(cb)
            h.addWidget(QLabel("굵기:"))
            sw = QSpinBox(); sw.setRange(1, 40); sw.setValue(int(pr.get("width", 3)))
            h.addWidget(sw)
            h.addWidget(QLabel("투명도:"))
            sa = QSpinBox(); sa.setRange(10, 100); sa.setSuffix(" %")
            sa.setValue(int(pr.get("alpha", 100)))
            h.addWidget(sa)
            h.addWidget(QLabel("단축키:"))
            ks = QKeySequenceEdit()
            if i < len(keys) and keys[i]:
                ks.setKeySequence(QKeySequence(keys[i]))
            h.addWidget(ks)
            v.addWidget(grp)
            self._rows.append((ed, cb, sw, sa, ks))

        # 일부분 지우개 굵기(얇게/두껍게)
        ew = list(eraser_widths or [12, 30])
        eg = QGroupBox("일부분 지우기 굵기")
        eh = QHBoxLayout(eg)
        eh.addWidget(QLabel("얇게:"))
        self.sp_e1 = QSpinBox(); self.sp_e1.setRange(4, 60)
        self.sp_e1.setValue(int(ew[0]) if len(ew) > 0 else 12); eh.addWidget(self.sp_e1)
        eh.addWidget(QLabel("두껍게:"))
        self.sp_e2 = QSpinBox(); self.sp_e2.setRange(4, 120)
        self.sp_e2.setValue(int(ew[1]) if len(ew) > 1 else 30); eh.addWidget(self.sp_e2)
        eh.addStretch(1)
        v.addWidget(eg)

        row = QHBoxLayout(); row.addStretch(1)
        ok = QPushButton("확인"); ok.clicked.connect(self.accept)
        cancel = QPushButton("취소"); cancel.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(cancel)
        v.addLayout(row)

    def result_pens(self):
        out = []
        for i, (ed, cb, sw, sa, ks) in enumerate(self._rows):
            out.append({"name": ed.text().strip() or f"사용자선 {i + 1}",
                        "color": cb.color_name(), "width": int(sw.value()),
                        "alpha": int(sa.value())})
        return out

    def result_keys(self):
        return [r[4].keySequence().toString() for r in self._rows]

    def result_eraser_widths(self):
        return [int(self.sp_e1.value()), int(self.sp_e2.value())]


class MainDrawSettingsDialog(QDialog):
    """260611-2: 본문·발표 공유 선긋기 설정 — 5펜(색·굵기·투명도) + 지우개 면적 + 하이라이트.

    투명도 의미: 100% = 안 보임, 0% = 불투명(반대로 적용되던 것 수정).
    내부 저장은 불투명도(alpha, 100=불투명)로 유지 → 다이얼로그에서만 변환(alpha=100-투명도).
    """

    def __init__(self, pens, parent=None, eraser_widths=None, highlight_alpha=35):
        super().__init__(parent)
        self.setWindowTitle("선긋기 설정 (색·굵기·투명도)")
        self.resize(440, 380)
        self._rows = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "편집모드 본문/발표에서 왼쪽 드래그로 선을 긋습니다(설정 공유).\n"
            "선 1~5의 색·굵기·투명도를 설정하세요. "
            "투명도 100%=안 보임, 0%=불투명."))
        for i, pr in enumerate(pens):
            grp = QGroupBox(f"선 {i + 1}")
            h = QHBoxLayout(grp)
            h.addWidget(QLabel("색:"))
            cb = _ColorBtn(pr.get("color", "#ff3030"))
            h.addWidget(cb)
            h.addWidget(QLabel("굵기:"))
            sw = QSpinBox(); sw.setRange(1, 40); sw.setValue(int(pr.get("width", 3)))
            h.addWidget(sw)
            h.addWidget(QLabel("투명도:"))
            st = QSpinBox(); st.setRange(0, 100); st.setSuffix(" %")
            st.setValue(100 - int(pr.get("alpha", 100)))     # 불투명도→투명도
            h.addWidget(st)
            h.addStretch(1)
            v.addWidget(grp)
            self._rows.append((cb, sw, st))

        # 하이라이트 전용 투명도
        hg = QGroupBox("하이라이트")
        hh = QHBoxLayout(hg)
        hh.addWidget(QLabel("투명도:"))
        self.sp_hl = QSpinBox(); self.sp_hl.setRange(0, 100); self.sp_hl.setSuffix(" %")
        self.sp_hl.setValue(100 - int(highlight_alpha or 35))
        hh.addWidget(self.sp_hl); hh.addStretch(1)
        v.addWidget(hg)

        # 지우개 작동 면적(얇게/두껍게) — 옵션에서 지정
        ew = list(eraser_widths or [12, 30])
        eg = QGroupBox("지우개 면적(px)")
        eh = QHBoxLayout(eg)
        eh.addWidget(QLabel("얇게:"))
        self.sp_e1 = QSpinBox(); self.sp_e1.setRange(4, 80)
        self.sp_e1.setValue(int(ew[0]) if len(ew) > 0 else 12); eh.addWidget(self.sp_e1)
        eh.addWidget(QLabel("두껍게:"))
        self.sp_e2 = QSpinBox(); self.sp_e2.setRange(4, 160)
        self.sp_e2.setValue(int(ew[1]) if len(ew) > 1 else 30); eh.addWidget(self.sp_e2)
        eh.addStretch(1)
        v.addWidget(eg)

        row = QHBoxLayout(); row.addStretch(1)
        ok = QPushButton("확인"); ok.clicked.connect(self.accept)
        cancel = QPushButton("취소"); cancel.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(cancel)
        v.addLayout(row)

    def result_pens(self):
        out = []
        for i, (cb, sw, st) in enumerate(self._rows):
            out.append({"name": f"선 {i + 1}", "color": cb.color_name(),
                        "width": int(sw.value()),
                        "alpha": 100 - int(st.value())})     # 투명도→불투명도
        return out

    def result_eraser_widths(self):
        return [int(self.sp_e1.value()), int(self.sp_e2.value())]

    def result_highlight_alpha(self):
        return 100 - int(self.sp_hl.value())                 # 투명도→불투명도
