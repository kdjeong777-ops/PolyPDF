"""설정 다이얼로그.

v1.6.2: 히스토리 패널 제거 — 관련 옵션(`restore_history`, `history_max`) 삭제.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QPushButton,
    QLabel,
    QDialogButtonBox,
    QScrollArea,
    QWidget,
    QLineEdit,
    QFileDialog,
    QKeySequenceEdit,
    QMessageBox,
)
from PyQt6.QtGui import QKeySequence

# 260606-13: 화면 스타일(테마) 옵션
THEME_LABELS = [("auto", "자동 (시스템 설정 따름)"), ("light", "밝게 (화이트)"),
                ("dark", "어둡게 (다크)")]


class SettingsDialog(QDialog):
    """설정 메뉴: 시작 동작 + 스크린샷 한도."""

    def __init__(self, prefs: dict, parent=None, host=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(440)
        self._prefs = dict(prefs)
        self._host = host       # 260609-17(F4): 녹화 테스트·장치 조회용
        self.resize(480, 640)

        # 내용이 길어 스크롤 영역에 담음
        _outer = QVBoxLayout(self)
        _scroll = QScrollArea(); _scroll.setWidgetResizable(True)
        _content = QWidget(); _scroll.setWidget(_content)
        _outer.addWidget(_scroll, 1)
        self._outer = _outer
        self._scroll = _scroll          # 260611-25: 녹화 설정으로 스크롤 이동용
        layout = QVBoxLayout(_content)

        # ── 시작 시 동작 ─────────────────────────────────
        grp_start = QGroupBox("시작 시 동작")
        gl = QVBoxLayout(grp_start)

        self.chk_restore = QCheckBox("프로그램 시작 시 기존 작업 화면을 그대로 복원")
        self.chk_restore.setChecked(bool(self._prefs.get("restore_session", True)))
        self.chk_restore.toggled.connect(self._on_restore_toggled)
        gl.addWidget(self.chk_restore)

        self.chk_last_page = QCheckBox(
            "복원 시 마지막으로 본 페이지 열기 (해제 = 첫 페이지)"   # 260618-18: 앞 공백·└ 제거
        )
        self.chk_last_page.setChecked(bool(self._prefs.get("restore_last_page", True)))
        gl.addWidget(self.chk_last_page)

        # v1.6.2: 히스토리 복원 토글 제거. 스크린샷만 남음.
        self.chk_restore_shots = QCheckBox(
            "프로그램 시작 시 스크린샷 리스트 그대로 복원 (해제 = 비워서 시작)"
        )
        self.chk_restore_shots.setChecked(bool(self._prefs.get("restore_screenshots", True)))
        gl.addWidget(self.chk_restore_shots)

        layout.addWidget(grp_start)

        # ── 스크린샷 한도 ─────────────────────────────────
        grp_hist = QGroupBox("스크린샷 한도 (썸네일 갯수)")
        fl = QFormLayout(grp_hist)

        self.spin_screenshot = QSpinBox()
        self.spin_screenshot.setRange(5, 1000)   # v1.6.2: 일괄 캡쳐 시 자동 확장 대비 상한 ↑
        self.spin_screenshot.setValue(int(self._prefs.get("screenshot_max", 30)))
        self.spin_screenshot.setSuffix(" 개")
        fl.addRow("스크린샷 리스트:", self.spin_screenshot)

        layout.addWidget(grp_hist)

        # ── 패널 토글 툴바 (v1.6.23) ─────────────────────
        # 검색결과/스크린샷 패널의 표시는 설정 메뉴(상단)·툴바에서 토글.
        # 여기서는 상단 토글 툴바 자체의 가시성만 제어 (기본 OFF — 메인 공간 확보).
        grp_panels = QGroupBox("패널 툴바 (기본 보이기)")
        pl = QVBoxLayout(grp_panels)
        self.chk_show_panel_toolbar = QCheckBox(
            "상단 패널 툴바([뷰어모드]·[기능]) 보이기"
        )
        self.chk_show_panel_toolbar.setChecked(
            bool(self._prefs.get("show_panel_toolbar", True)))
        pl.addWidget(self.chk_show_panel_toolbar)
        info_tb = QLabel(
            "<small>해제하면 메인 뷰어 세로 공간이 늘어납니다. 패널 자체의 "
            "보이기/숨기기는 메뉴 → 설정의 두 토글(검색결과/스크린샷)에서 즉시 가능.</small>"
        )
        info_tb.setStyleSheet("color:#666;"); info_tb.setWordWrap(True)
        pl.addWidget(info_tb)
        # 260609-2: 페이지 경계에서 다음/이전 파일로 이동
        self.chk_cross_file_nav = QCheckBox(
            "마지막/첫 페이지에서 다음·이전 파일로 자동 이동 (책갈피창 순서)"
        )
        self.chk_cross_file_nav.setChecked(
            self._prefs.get("cross_file_nav", True) is not False)   # 260609-28: 미설정=켜짐
        pl.addWidget(self.chk_cross_file_nav)
        info_cfn = QLabel(
            "<small>켜면 마지막 페이지에서 '다음'을 누르면 다음 파일의 첫 페이지로, "
            "첫 페이지에서 '이전'을 누르면 이전 파일의 마지막 페이지로 이동합니다.</small>"
        )
        info_cfn.setStyleSheet("color:#666;"); info_cfn.setWordWrap(True)
        pl.addWidget(info_cfn)
        layout.addWidget(grp_panels)

        # 260611-25: '발표(전체화면) 보기' 설정은 전체화면 우클릭 옵션으로 이동(여기서 제거).

        # ── 하이퍼링크 ── 260609-11(C8) ─────────────────
        grp_hl = QGroupBox("하이퍼링크")
        hlf = QFormLayout(grp_hl)
        self.spin_hl_offset = QSpinBox()
        self.spin_hl_offset.setRange(0, 200)
        self.spin_hl_offset.setSuffix(" px")
        self.spin_hl_offset.setValue(int(self._prefs.get("hyperlink_top_offset_px", 10)))
        hlf.addRow("페이지 내 버튼 상단 오프셋:", self.spin_hl_offset)
        layout.addWidget(grp_hl)

        # ── 화면+음성 녹화 ── 260609-17(F4) ─────────────────
        self._build_recording_group(layout)

        # ── 화면 스타일(테마) ─────────────────────────────
        grp_theme = QGroupBox("화면 스타일")
        tl = QFormLayout(grp_theme)
        self.cmb_theme = QComboBox()
        for _val, _lbl in THEME_LABELS:
            self.cmb_theme.addItem(_lbl, _val)
        cur = str(self._prefs.get("theme", "auto"))
        idx = max(0, [v for v, _ in THEME_LABELS].index(cur)
                  if cur in [v for v, _ in THEME_LABELS] else 0)
        self.cmb_theme.setCurrentIndex(idx)
        tl.addRow("테마:", self.cmb_theme)
        layout.addWidget(grp_theme)

        # ── 인터넷 사전(단어장) ─────────────────────────── 260615-9(P11)
        from PyQt6.QtWidgets import QCheckBox as _QCb, QLineEdit as _QLe
        grp_od = QGroupBox("인터넷 사전 (단어장)")
        ol = QFormLayout(grp_od)
        self.chk_online_dict = _QCb("인터넷 사전 포함 (켜면 단어 편집기에서 온라인 조회)")
        self.chk_online_dict.setChecked(bool(self._prefs.get("online_dict_enabled", False)))
        ol.addRow(self.chk_online_dict)
        self.ed_urimal_key = _QLe(str(self._prefs.get("urimalsaem_key", "")))
        self.ed_urimal_key.setPlaceholderText("국립국어원 우리말샘 오픈API 인증키 (무료 발급)")
        ol.addRow("우리말샘 키:", self.ed_urimal_key)
        self.ed_stdict_key = _QLe(str(self._prefs.get("stdict_key", "")))
        self.ed_stdict_key.setPlaceholderText("표준국어대사전 오픈API 인증키 (무료 발급)")
        ol.addRow("표준국어대사전 키:", self.ed_stdict_key)
        self.ed_onterm_key = _QLe(str(self._prefs.get("onterm_key", "")))
        self.ed_onterm_key.setPlaceholderText("국립국어원 온용어(전문용어) 오픈API 인증키 (무료 발급)")
        ol.addRow("온용어 키:", self.ed_onterm_key)
        self.ed_law_oc = _QLe(str(self._prefs.get("law_oc", "")))
        self.ed_law_oc.setPlaceholderText("법제처 국가법령정보 OPEN API OC(이메일 ID, 무료)")
        ol.addRow("법제처 OC:", self.ed_law_oc)
        self.ed_kcsc_key = _QLe(str(self._prefs.get("kcsc_key", "")))   # 260618-37
        self.ed_kcsc_key.setPlaceholderText("국가건설기준센터(KCSC) OPEN API 키 (무료 발급)")
        ol.addRow("KCSC 키:", self.ed_kcsc_key)
        ol.addRow(QLabel("<small>영어 Free Dictionary·Tatoeba 예문은 키 없이 동작. "
                         "한국어 사전은 위 키 입력 시 사용.</small>"))
        layout.addWidget(grp_od)

        info = QLabel(
            "<small>한도 변경은 즉시 반영됩니다. 줄이면 가장 오래된 항목부터 자동 제거됩니다.<br>"
            "검색결과 일괄 캡쳐 시 결과 수가 한도를 넘으면 자동으로 한도가 늘어납니다.</small>"
        )
        info.setStyleSheet("color:#666;")
        layout.addWidget(info)

        # ── 버튼(스크롤 밖, 항상 보이게) ────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        self._outer.addWidget(btns)

        self._on_restore_toggled(self.chk_restore.isChecked())

    def _on_restore_toggled(self, on: bool):
        self.chk_last_page.setEnabled(on)

    def focus_recording(self):
        """260611-25: 녹화 설정 그룹으로 스크롤 이동."""
        try:
            if getattr(self, "_grp_rec", None) is not None:
                self._scroll.ensureWidgetVisible(self._grp_rec)
        except Exception:
            pass

    # ── 260609-17(F4): 화면+음성 녹화 설정 ───────────────────
    def _build_recording_group(self, layout):
        grp = QGroupBox("화면+음성 녹화 (발표 전체화면)")
        self._grp_rec = grp
        f = QFormLayout(grp)

        self.ed_rec_dir = QLineEdit(str(self._prefs.get("recording_dir", "")))
        self.ed_rec_dir.setPlaceholderText("비우면 현재 책갈피 폴더에 저장")
        b_dir = QPushButton("찾기…"); b_dir.clicked.connect(self._pick_rec_dir)
        rd = QHBoxLayout(); rd.addWidget(self.ed_rec_dir, 1); rd.addWidget(b_dir)
        _w1 = QWidget(); _w1.setLayout(rd); f.addRow("저장 위치:", _w1)

        self.cmb_audio = QComboBox()
        for v, t in [("none", "영상만(소리 없음)"), ("mic", "마이크"),
                     ("system", "시스템 소리"), ("both", "마이크 + 시스템")]:
            self.cmb_audio.addItem(t, v)
        am = str(self._prefs.get("recording_audio_mode", "mic"))
        self.cmb_audio.setCurrentIndex(max(0, [self.cmb_audio.itemData(i)
                                               for i in range(self.cmb_audio.count())].index(am)
                                            if am in [self.cmb_audio.itemData(i)
                                                      for i in range(self.cmb_audio.count())] else 1))
        f.addRow("오디오:", self.cmb_audio)

        self.cmb_mic = QComboBox(); self.cmb_mic.setEditable(True)
        self.cmb_mic.setEditText(str(self._prefs.get("recording_mic", "")))
        self.cmb_sys = QComboBox(); self.cmb_sys.setEditable(True)
        self.cmb_sys.setEditText(str(self._prefs.get("recording_system", "")))
        b_dev = QPushButton("오디오 장치 새로고침"); b_dev.clicked.connect(self._refresh_devices)
        f.addRow("마이크 장치:", self.cmb_mic)
        f.addRow("시스템 장치:", self.cmb_sys)
        f.addRow("", b_dev)

        # 260618-18: 'ffmpeg 경로' 입력 제거 — ffmpeg 은 설치 폴더에 동봉/복사되어 자동 탐색됨.
        keys = list(self._prefs.get("recording_keys", []) or [])
        self.ks_rec = QKeySequenceEdit(QKeySequence(keys[0]) if len(keys) > 0 and keys[0]
                                       else QKeySequence("Ctrl+R"))
        self.ks_recstop = QKeySequenceEdit(QKeySequence(keys[1]) if len(keys) > 1 and keys[1]
                                           else QKeySequence("Ctrl+Shift+R"))
        f.addRow("녹화/재개 단축키:", self.ks_rec)
        f.addRow("중지 단축키:", self.ks_recstop)

        b_test = QPushButton("녹화 테스트 (3초)"); b_test.clicked.connect(self._on_rec_test)
        f.addRow("", b_test)
        info = QLabel("<small>코덱 H.264/AAC·192kbps·30fps·CQ23 고정. 시스템 소리는 "
                      "Stereo Mix 또는 가상 오디오 장치가 있어야 녹음됩니다.</small>")
        info.setWordWrap(True); info.setStyleSheet("color:#666;")
        f.addRow(info)
        layout.addWidget(grp)

    def _pick_rec_dir(self):
        d = QFileDialog.getExistingDirectory(self, "녹화 저장 폴더", self.ed_rec_dir.text())
        if d:
            self.ed_rec_dir.setText(d)

    def _refresh_devices(self):
        try:
            from viewer.recorder import (find_ffmpeg, list_audio_devices,
                                         guess_mic_device, guess_system_device)
            ff = find_ffmpeg(self._prefs.get("ffmpeg_path", ""))
            devs = list_audio_devices(ff)
        except Exception:
            devs = []
        if not devs:
            QMessageBox.information(self, "오디오 장치",
                                    "오디오 입력 장치를 찾지 못했습니다(ffmpeg 확인).")
            return
        cur_m, cur_s = self.cmb_mic.currentText(), self.cmb_sys.currentText()
        for cmb in (self.cmb_mic, self.cmb_sys):
            cmb.clear()
            cmb.addItem("")
            for d in devs:
                cmb.addItem(d)
        self.cmb_mic.setEditText(cur_m or guess_mic_device(devs))
        self.cmb_sys.setEditText(cur_s or guess_system_device(devs))

    def _on_rec_test(self):
        if self._host is None or not hasattr(self._host, "_test_recording"):
            return
        # 현재 다이얼로그 값으로 임시 반영 후 테스트
        self._host._prefs["recording_audio_mode"] = self.cmb_audio.currentData()
        self._host._prefs["recording_mic"] = self.cmb_mic.currentText().strip()
        self._host._prefs["recording_system"] = self.cmb_sys.currentText().strip()
        # 260618-26: 사전 확인 없이 바로 테스트 녹화 진행(요청) — 결과만 아래에 표시.
        ok, msg = self._host._test_recording(self)
        # 260611-25: 합격 결과 기록(녹화 시작 전 게이트에서 확인)
        self._host._prefs["recording_test_ok"] = bool(ok)
        try:
            self._host._save_settings_now()
        except Exception:
            pass
        (QMessageBox.information if ok else QMessageBox.warning)(self, "녹화 테스트", msg)

    def result_prefs(self) -> dict:
        return {
            "restore_session": self.chk_restore.isChecked(),
            "restore_last_page": self.chk_last_page.isChecked(),
            "restore_screenshots": self.chk_restore_shots.isChecked(),
            "screenshot_max": int(self.spin_screenshot.value()),
            # v1.6.23: 패널 토글 툴바 가시성
            "show_panel_toolbar": self.chk_show_panel_toolbar.isChecked(),
            # 260609-2: 페이지 경계 파일 이동
            "cross_file_nav": self.chk_cross_file_nav.isChecked(),
            # 260611-25: 발표 보기 옵션은 전체화면 우클릭 옵션에서 설정(여기서 제외)
            # 260609-11(C8): 하이퍼링크 버튼 상단 오프셋
            "hyperlink_top_offset_px": int(self.spin_hl_offset.value()),
            # 260609-17(F4): 녹화
            "recording_dir": self.ed_rec_dir.text().strip(),
            "recording_audio_mode": self.cmb_audio.currentData(),
            "recording_mic": self.cmb_mic.currentText().strip(),
            "recording_system": self.cmb_sys.currentText().strip(),
            "recording_keys": [self.ks_rec.keySequence().toString(),
                               self.ks_recstop.keySequence().toString()],
            "ffmpeg_path": str(self._prefs.get("ffmpeg_path", "")),   # 260618-18: UI 제거, 기존값 보존
            # 260606-13: 화면 스타일(테마)
            "theme": self.cmb_theme.currentData(),
            # 260615-9(P11): 인터넷 사전
            "online_dict_enabled": self.chk_online_dict.isChecked(),
            "urimalsaem_key": self.ed_urimal_key.text().strip(),
            "stdict_key": self.ed_stdict_key.text().strip(),
            "onterm_key": self.ed_onterm_key.text().strip(),
            "law_oc": self.ed_law_oc.text().strip(),
            "kcsc_key": self.ed_kcsc_key.text().strip(),   # 260618-37
        }
