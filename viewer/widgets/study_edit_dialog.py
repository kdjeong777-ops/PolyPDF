"""용어 편집 다이얼로그 — 계층형 사전(dict.db, 사용자 출처)에 등록/수정/삭제 (P5).

- 한글표제어/영문표제어/한자/난이도 + 한글뜻/영어뜻/예시(다중)/참고문헌 입력(모두·일부 가능).
- 좌측 '관련 단어' 목록: 입력 표제어와 부분일치하는 기존 항목을 보여줘 중복 등록 방지·
  일관성 확인(클릭하면 내용 미리보기).
- 저장은 항상 **사용자 단어장(user)** 으로 — 기본(Base) 항목은 보존하고 사용자 우선 적용.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QComboBox, QDialogButtonBox, QPushButton, QSplitter,
    QListWidget, QListWidgetItem, QWidget, QTextBrowser,
)

_LEVELS = ["(자동)", "초급", "중급", "고급", "전문용어"]


class StudyEditDialog(QDialog):
    def __init__(self, entry: Optional[dict] = None, *,
                 related_provider: Optional[Callable[[str], list]] = None,
                 online_provider: Optional[Callable[[str, str], dict]] = None,
                 allow_delete: bool = False, title: str = "용어 편집",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 480)
        self._related_provider = related_provider
        self._online_provider = online_provider
        self._deleted = False
        e = entry or {}

        root = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        # --- 좌: 관련 단어 ---
        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("관련 단어 (기존 항목)"))
        self.lst_related = QListWidget()
        self.lst_related.itemClicked.connect(self._on_related_clicked)
        lv.addWidget(self.lst_related, 1)
        self.prev = QTextBrowser()
        self.prev.setMaximumHeight(120)
        self.prev.setPlaceholderText("관련 단어를 클릭하면 내용이 보입니다.")
        lv.addWidget(self.prev)
        split.addWidget(left)

        # --- 우: 입력 폼 ---
        right = QWidget()
        form = QFormLayout(right)
        self.ed_ko = QLineEdit(e.get("term_ko", ""))
        self.ed_en = QLineEdit(e.get("term_en", ""))
        self.ed_hanja = QLineEdit(e.get("hanja", ""))
        self.cmb_level = QComboBox(); self.cmb_level.addItems(_LEVELS)
        lvl = e.get("level", "")
        self.cmb_level.setCurrentText(lvl if lvl in _LEVELS else "(자동)")
        self.ed_ko_def = QPlainTextEdit(e.get("def_ko", ""))
        self.ed_en_def = QPlainTextEdit(e.get("def_en", ""))
        self.ed_ex = QPlainTextEdit(e.get("examples", ""))
        self.ed_ref = QLineEdit(e.get("reference", ""))
        for w in (self.ed_ko_def, self.ed_en_def, self.ed_ex):
            w.setMinimumHeight(48)
        form.addRow("한글 표제어", self.ed_ko)
        form.addRow("영문 표제어", self.ed_en)
        hb = QHBoxLayout()
        hb.addWidget(self.ed_hanja, 1)
        hb.addWidget(QLabel("난이도")); hb.addWidget(self.cmb_level)
        hw = QWidget(); hw.setLayout(hb)
        form.addRow("한자 / 난이도", hw)
        form.addRow("한글뜻", self.ed_ko_def)
        form.addRow("영어뜻", self.ed_en_def)
        form.addRow("예시(줄바꿈=여러 개)", self.ed_ex)
        form.addRow("참고문헌", self.ed_ref)
        # 260615-8(P10): 그림(이미지) — 썸네일 + 검색/파일/제거
        self._image = e.get("image", "")
        self._image_ref = e.get("image_ref", "")
        self.lbl_img = QLabel(); self.lbl_img.setFixedSize(96, 96)
        self.lbl_img.setStyleSheet("border:1px solid #888;background:#00000010;")
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib = QHBoxLayout()
        btn_isearch = QPushButton("인터넷 검색")
        btn_ifile = QPushButton("파일에서")
        btn_iclear = QPushButton("제거")
        btn_isearch.clicked.connect(self._img_search)
        btn_ifile.clicked.connect(self._img_file)
        btn_iclear.clicked.connect(self._img_clear)
        ivb = QVBoxLayout()
        for b in (btn_isearch, btn_ifile, btn_iclear):
            ivb.addWidget(b)
        ivb.addStretch(1)
        ib.addWidget(self.lbl_img); ib.addLayout(ivb); ib.addStretch(1)
        iw = QWidget(); iw.setLayout(ib)
        form.addRow("그림", iw)
        self._refresh_thumb()
        # 260615-9(P11): 인터넷 사전 조회(옵션 켜짐 + provider 있을 때)
        if self._online_provider is not None:
            self.btn_online = QPushButton("🌐 인터넷 사전 조회 (뜻·예문 채우기)")
            self.btn_online.clicked.connect(self._online_lookup)
            form.addRow("", self.btn_online)
        form.addRow(QLabel("<i>저장 위치: 사용자 단어장(기본 사전보다 우선 적용)</i>"))
        split.addWidget(right)
        split.setSizes([260, 460])

        # --- 버튼 ---
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        if allow_delete:
            btn_del = QPushButton("삭제")
            btn_del.setStyleSheet("color:#c0392b;")
            btn_del.clicked.connect(self._on_delete)
            bb.addButton(btn_del, QDialogButtonBox.ButtonRole.DestructiveRole)
        root.addWidget(bb)

        # 표제어 입력 변화 → 관련 단어 갱신(디바운스)
        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_related)
        for ed in (self.ed_ko, self.ed_en):
            ed.textChanged.connect(lambda _=None: self._timer.start(200))
        self._refresh_related()

    # --- 관련 단어 ---
    def _refresh_related(self) -> None:
        if not self._related_provider:
            return
        q = (self.ed_ko.text() or self.ed_en.text()).strip()
        self.lst_related.clear()
        if len(q) < 1:
            return
        try:
            rows = self._related_provider(q) or []
        except Exception:
            rows = []
        for r in rows[:50]:
            ko = r.get("term_ko", ""); en = r.get("term_en", "")
            tag = "👤" if r.get("src_kind") == "user" else "📘"
            label = f"{tag} {ko}" + (f" ({en})" if en else "")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, r)
            self.lst_related.addItem(it)

    def _on_related_clicked(self, it: QListWidgetItem) -> None:
        r = it.data(Qt.ItemDataRole.UserRole) or {}
        parts = []
        if r.get("term_ko") or r.get("term_en"):
            parts.append(f"<b>{r.get('term_ko','')}</b> {r.get('term_en','')}")
        if r.get("def_ko"):
            parts.append(r["def_ko"])
        if r.get("def_en"):
            parts.append(r["def_en"])
        src = r.get("src_name") or ""
        if src:
            parts.append(f"<i>— {src}</i>")
        self.prev.setHtml("<br>".join(parts))

    # --- 그림(이미지) ---
    def _term_for_img(self) -> str:
        return (self.ed_ko.text().strip() or self.ed_en.text().strip() or "img")

    def _refresh_thumb(self) -> None:
        from viewer.study.image_fetch import image_path
        p = image_path(self._image) if self._image else None
        if p:
            pm = QPixmap(p)
            if not pm.isNull():
                self.lbl_img.setPixmap(pm.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                self.lbl_img.setToolTip(self._image_ref or "")
                return
        self.lbl_img.setPixmap(QPixmap())
        self.lbl_img.setText("(없음)")

    def _img_search(self) -> None:
        from viewer.widgets.image_search_dialog import ImageSearchDialog
        from viewer.study.image_fetch import save_image_for_term
        dlg = ImageSearchDialog(self._term_for_img(), self)
        if dlg.exec() and dlg.chosen():
            r = dlg.chosen()
            try:
                fn, ref = save_image_for_term(self._term_for_img(), r.get("url", ""),
                                              r.get("attribution", ""))
                self._image, self._image_ref = fn, ref
                self._refresh_thumb()
            except Exception as e:
                self.prev.setHtml(f"<span style='color:#c0392b'>이미지 저장 실패: {e}</span>")

    def _img_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from viewer.study.image_fetch import import_local_image
        fn, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not fn:
            return
        try:
            self._image = import_local_image(self._term_for_img(), fn)
            self._image_ref = "사용자 업로드"
            self._refresh_thumb()
        except Exception as e:
            self.prev.setHtml(f"<span style='color:#c0392b'>이미지 불러오기 실패: {e}</span>")

    def _img_clear(self) -> None:
        self._image, self._image_ref = "", ""
        self._refresh_thumb()

    # --- 인터넷 사전 조회 ---
    def _online_lookup(self) -> None:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QCursor

        def _append(edit, items):
            cur = edit.toPlainText().strip()
            have = set(x.strip() for x in cur.splitlines())
            adds = [x for x in items if x.strip() and x.strip() not in have]
            if adds:
                edit.setPlainText((cur + "\n" if cur else "") + "\n".join(adds))

        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            res = self._online_provider(self.ed_ko.text().strip(),
                                        self.ed_en.text().strip()) or {}
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.prev.setHtml(f"<span style='color:#c0392b'>조회 실패: {e}</span>")
            return
        QApplication.restoreOverrideCursor()
        _append(self.ed_ko_def, res.get("def_ko", []))
        _append(self.ed_en_def, res.get("def_en", []))
        _append(self.ed_ex, [e.get("text", "") for e in res.get("examples", [])])
        srcs = ", ".join(res.get("sources", []))
        n = len(res.get("def_ko", [])) + len(res.get("def_en", [])) + len(res.get("examples", []))
        if not res.get("reference") and srcs and not self.ed_ref.text().strip():
            self.ed_ref.setText(srcs)
        self.prev.setHtml(f"인터넷 사전 {n}건 추가" + (f" ({srcs})" if srcs else "")
                          if n else "인터넷 사전 결과 없음(또는 키 미설정/네트워크).")

    # --- 저장/삭제 ---
    def _on_save(self) -> None:
        if not (self.ed_ko.text().strip() or self.ed_en.text().strip()):
            self.prev.setHtml("<span style='color:#c0392b'>표제어(한글 또는 영문)를 입력하세요.</span>")
            return
        self.accept()

    def _on_delete(self) -> None:
        self._deleted = True
        self.accept()

    def is_deleted(self) -> bool:
        return self._deleted

    def values(self) -> dict:
        lvl = self.cmb_level.currentText()
        return {
            "term_ko": self.ed_ko.text().strip(),
            "term_en": self.ed_en.text().strip(),
            "hanja": self.ed_hanja.text().strip(),
            "level": "" if lvl == "(자동)" else lvl,
            "def_ko": self.ed_ko_def.toPlainText().strip(),
            "def_en": self.ed_en_def.toPlainText().strip(),
            "examples": self.ed_ex.toPlainText().strip(),
            "reference": self.ed_ref.text().strip(),
            "image": self._image,
            "image_ref": self._image_ref,
        }
