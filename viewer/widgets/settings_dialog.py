"""환경설정 창.

v1.6.2: 히스토리 패널 제거 — 관련 옵션(`restore_history`, `history_max`) 삭제.
261107-12(디자인 SOT §2.14, 사용자 결정): 왼쪽 목록(일반/고급) + 쪽 · 설정 찾기 · [확인][적용][취소] —
따로 뜨던 고급(외부 연결)·발표 녹화·단축키·모음 메뉴 관리 창은 이 한 창의 쪽(`AdvancedPanel`·`RecordingPanel`·
`ShortcutsPanel`·`RibbonCustomizePanel`). 설정 키 이름은 그대로.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from viewer.i18n import tr, trp, tr_noop, korea_only_visible


class _AntLoginWorker(QThread):
    """260621-P3: ant 자동 설치 + 브라우저 로그인(백그라운드)."""
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def run(self):
        try:
            from ..study import ant_cli
        except Exception as e:
            self.done.emit(False, tr('모듈 오류: {e}').format(e=e))
            return
        try:
            ant_cli.ensure_installed(progress=self.progress.emit)
        except Exception as e:
            self.done.emit(False, tr('Anthropic CLI 설치 실패: {e}').format(e=str(e)[:120]))
            return
        self.progress.emit(tr("브라우저에서 로그인 완료를 기다리는 중…"))
        ok, msg = ant_cli.login()
        self.done.emit(ok, msg)


def _verify_external_key(kind: str, key: str):
    """260621-P3: 외부 API 키 확인 디스패치 → (성공여부, 메시지)."""
    try:
        if kind == "law":
            from ..study import law_api
            return law_api.verify_oc_debug(key)
        if kind == "kcsc":
            from ..study import kcsc_api
            return kcsc_api.verify_key_debug(key)
        if kind == "kipo":
            from ..study import kipo_api
            return kipo_api.verify_key_debug(key)
        if kind in ("stdict", "onterm"):
            from ..study import online_dict
            return online_dict.verify_provider_debug(kind, key)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"
    return False, tr("알 수 없는 항목")


class _KeyVerifyWorker(QThread):
    """260621-P3: 외부 API 키 확인(백그라운드)."""
    done = pyqtSignal(bool, str)

    def __init__(self, kind, key):
        super().__init__()
        self._kind, self._key = kind, key

    def run(self):
        ok, msg = _verify_external_key(self._kind, self._key)
        self.done.emit(ok, msg)


class _ConnTestWorker(QThread):
    """260621-P3: 입력된 키/로그인으로 연결·인증 확인(count_tokens — 무료, 크레딧 불요)."""
    done = pyqtSignal(int, list)

    def __init__(self, key, model, auth):
        super().__init__()
        self._key, self._model, self._auth = key, model, auth

    def run(self):
        try:
            from ..study import translate_api as tapi
            n, dbg = tapi.count_tokens_debug(
                self._key, tr("연결 확인 ping"), model=self._model, auth=self._auth)
        except Exception as e:
            n, dbg = -1, [f"ERR {type(e).__name__}: {str(e)[:120]}"]
        self.done.emit(n, dbg)
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
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QAbstractItemView,
)
from PyQt6.QtGui import QKeySequence

# 260606-13: 화면 스타일(테마) 옵션
THEME_LABELS = [("auto", tr_noop("자동 (시스템 설정 따름)")), ("light", tr_noop("밝게 (화이트)")),
                ("dark", tr_noop("어둡게 (다크)"))]

# 261107-12(디자인 SOT §2.14, 사용자 결정): 왼쪽 목록 — (id, 이름, 묶음). 묶음 머리글 '일반'·'고급' 은 고를 수 없다.
PAGES = (
    ("general", tr_noop("일반"), "general"),
    ("view", tr_noop("보기·넘김"), "general"),
    ("photo", tr_noop("사진"), "general"),
    ("tags", tr_noop("해시태그"), "general"),
    ("shots", tr_noop("스크린샷"), "general"),
    ("shortcuts", tr_noop("단축키"), "advanced"),
    ("ribbon", tr_noop("리본 메뉴"), "advanced"),
    ("external", tr_noop("외부 연결"), "advanced"),
    ("dict", tr_noop("사전"), "advanced"),          # 261107-17(단어장 SOT §11.1): 한국 전용 — 외부 연결과 같은 숨김
    ("recording", tr_noop("발표 녹화"), "advanced"),
    ("tuning", tr_noop("세부 조정"), "advanced"),
    ("manage", tr_noop("관리"), "advanced"),
)
GROUP_NAMES = {"general": tr_noop("일반"), "advanced": tr_noop("고급")}


def page_name(key: str) -> str:
    """목록 이름 — 문맥 'settings'(같은 원문 '일반' 이 파일 탭에서는 '저장 일반' 이라 번역이 다르다)."""
    return {
        "general": trp("settings", "일반"), "view": trp("settings", "보기·넘김"), "photo": trp("settings", "사진"),
        "tags": trp("settings", "해시태그"), "shots": trp("settings", "스크린샷"), "shortcuts": trp("settings", "단축키"),
        "ribbon": trp("settings", "리본 메뉴"), "external": trp("settings", "외부 연결"), "dict": trp("settings", "사전"), "recording": trp("settings", "발표 녹화"),
        "tuning": trp("settings", "세부 조정"), "manage": trp("settings", "관리"),
        "g:general": trp("settings", "일반"), "g:advanced": trp("settings", "고급"),
    }[key]
MIN_W, MIN_H = 640, 480
PAGE_ROLE = Qt.ItemDataRole.UserRole


def _small(text: str) -> QLabel:
    """묶음 아래 작은 글씨 풀이(디자인 SOT §2.14 — 체크박스 글자에 긴 설명 금지)."""
    lab = QLabel("<small>%s</small>" % text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color:#666;")
    lab.setProperty("settingsInfo", True)
    return lab


class AdvancedPanel(QWidget):
    """261025-2 → 261107-12(디자인 SOT §2.14): '고급 › 외부 연결' 쪽 — 외부 API 설정.
    인터넷 사전(표준국어대사전·온용어·법제처·KCSC·특허 키, 특허 PDF 저장 폴더)·번역(Claude)·API 키 표시.
    값 모양·저장·키 보호는 종전과 같다(마스터 §8.2.0) — 키 이름도 그대로. 둘 다 한국 전용(다국어 SOT §7)."""

    def __init__(self, prefs: dict, parent=None, check_login: bool = True):
        super().__init__(parent)
        self._prefs = dict(prefs)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── 인터넷 사전(단어장) ─────────────────────────── 260615-9(P11)
        from PyQt6.QtWidgets import QCheckBox as _QCb, QLineEdit as _QLe
        grp_od = QGroupBox(tr("인터넷 사전 (단어장)"))
        self.grp_online_dict = grp_od
        ol = QFormLayout(grp_od)
        self.chk_online_dict = _QCb(tr("인터넷 사전 포함"))
        self.chk_online_dict.setToolTip(tr("켜면 단어 편집기에서 온라인으로 조회합니다."))
        self.chk_online_dict.setChecked(bool(self._prefs.get("online_dict_enabled", False)))
        ol.addRow(self.chk_online_dict)
        self.ed_stdict_key = _QLe(str(self._prefs.get("stdict_key", "")))
        self.ed_stdict_key.setPlaceholderText(tr("표준국어대사전 오픈API 인증키 (무료 발급)"))
        ol.addRow(tr("표준국어대사전 키:"), self._keyrow(self.ed_stdict_key, "stdict"))
        self.ed_onterm_key = _QLe(str(self._prefs.get("onterm_key", "")))
        self.ed_onterm_key.setPlaceholderText(tr("국립국어원 온용어(전문용어) 오픈API 인증키 (무료 발급)"))
        ol.addRow(tr("온용어 키:"), self._keyrow(self.ed_onterm_key, "onterm"))
        _info_od = QLabel(tr("<small>영어 Free Dictionary·Tatoeba 예문은 키 없이 동작. "
                             "한국어 사전은 위 키 입력 시 사용.</small>"))
        _info_od.setWordWrap(True)           # 261009-10(디자인 SOT §2.14)
        ol.addRow(_info_od)
        layout.addWidget(grp_od)
        grp_od.setVisible(korea_only_visible())      # 한국 사전 키 — 한국 전용(다국어 SOT §7)
        # 261107-17(단어장 SOT §11.1): 위 '인터넷 사전 (단어장)' 은 환경설정 '고급 › 사전' 쪽이 옮겨 단다. 법령·KCSC·특허는 여기에
        grp_lw = QGroupBox(tr("법령·건설기준·특허"))
        self.grp_law = grp_lw
        ol = QFormLayout(grp_lw)
        self.ed_law_oc = _QLe(str(self._prefs.get("law_oc", "")))
        self.ed_law_oc.setPlaceholderText(tr("법제처 국가법령정보 OPEN API OC(이메일 ID, 무료)"))
        ol.addRow(tr("법제처 OC:"), self._keyrow(self.ed_law_oc, "law"))
        self.ed_kcsc_key = _QLe(str(self._prefs.get("kcsc_key", "")))   # 260618-37
        self.ed_kcsc_key.setPlaceholderText(tr("국가건설기준센터(KCSC) OPEN API 키 (무료 발급)"))
        ol.addRow(tr("KCSC 키:"), self._keyrow(self.ed_kcsc_key, "kcsc"))
        self.ed_kipo_key = _QLe(str(self._prefs.get("kipo_signkey", "")))   # 260618-43/44
        self.ed_kipo_key.setPlaceholderText(tr("KIPRIS Plus ServiceKey (특허 명칭·내용 검색)"))
        ol.addRow(tr("특허(KIPRIS) 키:"), self._keyrow(self.ed_kipo_key, "kipo"))
        # 260618-47: 특허(전자명세서) PDF 저장 폴더 + 찾아보기
        self.ed_patent_dir = _QLe(str(self._prefs.get("patent_save_dir", "")))
        self.ed_patent_dir.setPlaceholderText(tr("비우면 문서\\PolyPDF_특허"))
        _pw = QWidget(); _ph = QHBoxLayout(_pw); _ph.setContentsMargins(0, 0, 0, 0)
        _pbtn = QPushButton(tr("찾아보기"))
        _pbtn.clicked.connect(self._pick_patent_dir)
        _ph.addWidget(self.ed_patent_dir, 1); _ph.addWidget(_pbtn)
        ol.addRow(tr("특허 PDF 저장 폴더:"), _pw)
        layout.addWidget(grp_lw)
        grp_lw.setVisible(korea_only_visible())      # 법령·KCSC·KIPO 키 — 한국 전용(다국어 SOT §7)

        # ── 번역 (Claude) ─────────────────────────── 260621-P0 (PDF 번역·요약)
        try:
            from ..study import translate_api as _tapi
            _MODELS = _tapi.MODELS
            _DEFMODEL = _tapi.DEFAULT_MODEL
        except Exception:
            _MODELS = [("claude-opus-4-8", "Claude Opus 4.8", 5.0, 25.0)]
            _DEFMODEL = "claude-opus-4-8"
        grp_tr = QGroupBox(tr("번역 (Claude)"))
        self.grp_translate = grp_tr
        trl = QFormLayout(grp_tr)
        self.cmb_translate_auth = QComboBox()
        self.cmb_translate_auth.addItem(tr("API 키"), "api")
        self.cmb_translate_auth.addItem(tr("Claude 로그인 (구독·OAuth)"), "login")
        _cur_a = str(self._prefs.get("translate_auth", "api"))
        _ai = self.cmb_translate_auth.findData(_cur_a)
        self.cmb_translate_auth.setCurrentIndex(_ai if _ai >= 0 else 0)
        trl.addRow(tr("인증 방식:"), self.cmb_translate_auth)
        self.ed_anthropic_key = _QLe(str(self._prefs.get("anthropic_api_key", "")))
        self.ed_anthropic_key.setPlaceholderText(tr("sk-ant-… (로그인 모드면 비워둠)"))
        trl.addRow(tr("Claude API 키:"), self.ed_anthropic_key)
        self.cmb_translate_model = QComboBox()
        for mid, label, *_ in _MODELS:
            self.cmb_translate_model.addItem(tr(label), mid)
        _cur_m = str(self._prefs.get("translate_model", _DEFMODEL))
        _mi = self.cmb_translate_model.findData(_cur_m)
        self.cmb_translate_model.setCurrentIndex(_mi if _mi >= 0 else 0)
        trl.addRow(tr("번역 모델:"), self.cmb_translate_model)
        # 260621-P3: 구독 로그인 — 앱 내 'Claude 로그인' 버튼(ant 자동설치+브라우저)
        _lw = QWidget(); _lh = QHBoxLayout(_lw); _lh.setContentsMargins(0, 0, 0, 0)
        self.lbl_login_status = QLabel("")
        self.btn_ant_login = QPushButton(tr("Claude 로그인"))
        self.btn_ant_logout = QPushButton(tr("로그아웃"))
        self.btn_ant_login.clicked.connect(self._ant_login)
        self.btn_ant_logout.clicked.connect(self._ant_logout)
        _lh.addWidget(self.lbl_login_status, 1)
        _lh.addWidget(self.btn_ant_login)
        _lh.addWidget(self.btn_ant_logout)
        trl.addRow(tr("구독 로그인:"), _lw)

        # 260621-P3: 연결·인증 확인(무료 count_tokens — 크레딧 없이 토큰/인증 점검)
        _cw = QWidget(); _ch = QHBoxLayout(_cw); _ch.setContentsMargins(0, 0, 0, 0)
        self.lbl_conn_status = QLabel("")
        self.btn_test_conn = QPushButton(tr("연결 확인"))
        self.btn_test_conn.setToolTip(tr("입력한 키/로그인으로 Claude 에 연결·인증되는지 확인(무료)"))
        self.btn_test_conn.clicked.connect(self._test_translate_conn)
        _ch.addWidget(self.lbl_conn_status, 1)
        _ch.addWidget(self.btn_test_conn)
        trl.addRow(tr("연결 확인:"), _cw)

        self.chk_translate_consent = _QCb(tr("번역 시 본문 전송에 동의"))
        self.chk_translate_consent.setToolTip(tr("번역 시 논문 본문이 Anthropic(Claude) 서버로 전송됨에 동의"))
        self.chk_translate_consent.setChecked(bool(self._prefs.get("translate_consent", False)))
        trl.addRow(self.chk_translate_consent)
        _hlp_tr = QLabel(
            tr("<small><b>API 키</b>: 콘솔(console.anthropic.com)에서 발급·과금 설정. 가장 안정적.<br>"
               "<b>Claude 로그인</b>: 콘솔 키 없이 구독 계정 사용 — 위 <b>[Claude 로그인]</b> 버튼을 누르면 "
               "필요 시 Anthropic CLI 를 자동 설치하고 <b>브라우저로 로그인</b>합니다(터미널 불필요).<br>"
               "<b>주의</b>: 번역(Messages API)은 <b>API 크레딧</b>이 필요합니다 — Claude 구독(Pro/Max)은 "
               "API 사용에 적용되지 않으니, console.anthropic.com → Billing 에서 크레딧을 충전하세요. "
               "민감 문서 전송에 주의.</small>"))
        _hlp_tr.setWordWrap(True)
        trl.addRow(_hlp_tr)
        layout.addWidget(grp_tr)
        grp_tr.setVisible(korea_only_visible())      # 영→한 번역 — 한국 전용(사용자 결정 261008-25)
        self.cmb_translate_auth.currentIndexChanged.connect(self._on_translate_auth_changed)
        self._login_checked = False
        self._on_translate_auth_changed()
        if check_login:
            self.check_login_once()

        # 260621-P3: 모든 API 키를 *** 로 가림 + '키 표시' 토글
        self._key_edits = [self.ed_stdict_key, self.ed_onterm_key,
                           self.ed_law_oc, self.ed_kcsc_key, self.ed_kipo_key,
                           self.ed_anthropic_key]
        for _e in self._key_edits:
            _e.setEchoMode(_QLe.EchoMode.Password)
        self.chk_show_keys = _QCb(tr("API 키 표시"))
        self.chk_show_keys.setToolTip(tr("체크를 풀면 키를 *** 로 가립니다."))
        self.chk_show_keys.setChecked(False)
        self.chk_show_keys.toggled.connect(self._toggle_show_keys)
        layout.addWidget(self.chk_show_keys)
        self.chk_show_keys.setVisible(korea_only_visible())
        layout.addStretch(1)

    def has_visible(self) -> bool:
        """한국 전용 묶음이 숨으면 남는 것이 없다 — 환경설정 목록에서 '외부 연결' 을 숨긴다(디자인 SOT §2.14)."""
        return korea_only_visible()

    def _toggle_show_keys(self, on):
        from PyQt6.QtWidgets import QLineEdit as _QLe
        m = _QLe.EchoMode.Normal if on else _QLe.EchoMode.Password
        for _e in self._key_edits:
            _e.setEchoMode(m)

    def _pick_patent_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("특허 PDF 저장 폴더 선택"), self.ed_patent_dir.text().strip() or "")
        if d:
            self.ed_patent_dir.setText(d)

    def check_login_once(self) -> None:
        """로그인 상태 조회는 쪽을 처음 볼 때 한 번(응답성 SOT §5 — `ant_cli` 조회가 메인을 잡지 않게 미룬다)."""
        if self._login_checked:
            return
        self._login_checked = True
        self._refresh_login_status()

    # ── 번역 구독 로그인(ant) ──────────────────────────── 260621-P3
    def _on_translate_auth_changed(self):
        login = (self.cmb_translate_auth.currentData() == "login")
        for w in (self.lbl_login_status, self.btn_ant_login, self.btn_ant_logout):
            w.setEnabled(login)
        self.ed_anthropic_key.setEnabled(not login)
        if login and self._login_checked:
            self._refresh_login_status()
        elif not login:
            self.lbl_login_status.setText("")

    def _refresh_login_status(self):
        if self.cmb_translate_auth.currentData() != "login":
            self.lbl_login_status.setText("")
            return
        try:
            from ..study import ant_cli
        except Exception:
            self.lbl_login_status.setText(tr("모듈 없음"))
            return
        if not ant_cli.is_installed():
            self.lbl_login_status.setText(tr("<span style='color:#888'>미설치 — [Claude 로그인]을 누르세요</span>"))
        elif ant_cli.is_logged_in():
            self.lbl_login_status.setText(tr("<span style='color:#0a0'>로그인됨 ✓</span>"))
        else:
            self.lbl_login_status.setText(tr("<span style='color:#c60'>로그인 필요</span>"))

    def _ant_login(self):
        self.btn_ant_login.setEnabled(False)
        self.lbl_login_status.setText(tr("준비 중…"))
        self._ant_worker = _AntLoginWorker()
        self._ant_worker.progress.connect(self.lbl_login_status.setText)
        self._ant_worker.done.connect(self._on_ant_login_done)
        self._ant_worker.start()

    def _on_ant_login_done(self, ok: bool, msg: str):
        self.btn_ant_login.setEnabled(True)
        if ok:
            QMessageBox.information(self, tr("Claude 로그인"), tr("로그인되었습니다. 이제 번역을 사용할 수 있습니다."))
        else:
            QMessageBox.warning(self, tr("Claude 로그인"), tr('로그인하지 못했습니다.\n{msg}').format(msg=msg or ''))
        self._login_checked = True
        self._refresh_login_status()

    def _ant_logout(self):
        try:
            from ..study import ant_cli
            ant_cli.logout()
        except Exception:
            pass
        self._refresh_login_status()

    def _keyrow(self, edit, kind):
        """260621-P3: [키 입력칸 | 확인 버튼 | 상태] 한 줄 위젯(외부 API 키 확인용)."""
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        btn = QPushButton(tr("확인")); btn.setFixedWidth(46)
        lbl = QLabel(""); lbl.setMinimumWidth(70)
        h.addWidget(edit, 1); h.addWidget(btn); h.addWidget(lbl)
        btn.clicked.connect(lambda: self._do_verify_key(kind, edit, btn, lbl))
        return w

    def _do_verify_key(self, kind, edit, btn, lbl):
        key = edit.text().strip()
        if not key:
            lbl.setText(tr("<span style='color:#c00'>키 없음</span>"))
            return
        btn.setEnabled(False)
        lbl.setText(tr("확인 중…"))
        if not hasattr(self, "_verify_workers"):
            self._verify_workers = []
        w = _KeyVerifyWorker(kind, key)
        self._verify_workers.append(w)

        def _fin(ok, msg, b=btn, l=lbl, ww=w):
            b.setEnabled(True)
            color = "#0a0" if ok else "#c00"
            mark = "✓" if ok else "✗"
            l.setText(f"<span style='color:{color}'>{mark} {msg[:16]}</span>")
            l.setToolTip(msg)
            try:
                self._verify_workers.remove(ww)
            except Exception:
                pass
        w.done.connect(_fin)
        w.start()

    def _test_translate_conn(self):
        """현재 입력값(키·모델·인증)으로 연결·인증 확인(저장 전에도 테스트 가능)."""
        auth = self.cmb_translate_auth.currentData()
        key = self.ed_anthropic_key.text().strip()
        model = self.cmb_translate_model.currentData()
        self.btn_test_conn.setEnabled(False)
        self.lbl_conn_status.setText(tr("확인 중…"))
        self._conn_worker = _ConnTestWorker(key, model, auth)
        self._conn_worker.done.connect(self._on_conn_test_done)
        self._conn_worker.start()

    def _on_conn_test_done(self, n: int, dbg: list):
        self.btn_test_conn.setEnabled(True)
        if n >= 0:
            self.lbl_conn_status.setText(
                tr("<span style='color:#0a0'>정상 ✓ (입력 토큰 {n}) — 번역은 API 크레딧 필요</span>").format(n=n))
        else:
            msg = (dbg[-1] if dbg else tr("실패"))
            self.lbl_conn_status.setText(tr("<span style='color:#c00'>실패: {msg}</span>").format(msg=msg))

    def result_prefs(self) -> dict:
        return {
            # 260615-9(P11): 인터넷 사전
            "online_dict_enabled": self.chk_online_dict.isChecked(),
            "stdict_key": self.ed_stdict_key.text().strip(),
            "onterm_key": self.ed_onterm_key.text().strip(),
            "law_oc": self.ed_law_oc.text().strip(),
            "kcsc_key": self.ed_kcsc_key.text().strip(),   # 260618-37
            "kipo_signkey": self.ed_kipo_key.text().strip(),   # 260618-43
            "patent_save_dir": self.ed_patent_dir.text().strip(),   # 260618-47
            # 260621-P0: 번역(Claude)
            "translate_auth": self.cmb_translate_auth.currentData(),
            "anthropic_api_key": self.ed_anthropic_key.text().strip(),
            "translate_model": self.cmb_translate_model.currentData(),
            "translate_consent": self.chk_translate_consent.isChecked(),
        }


class RecordingPanel(QWidget):
    """261025-6 → 261107-12(디자인 SOT §2.14): '고급 › 발표 녹화' 쪽 — 종전 '화면+음성 녹화 (발표 전체화면)' 묶음.
    키 이름·값 모양은 그대로(영상·음성 SOT)."""

    def __init__(self, prefs: dict, parent=None, host=None):
        super().__init__(parent)
        self._prefs = dict(prefs)
        self._host = host
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self._build_recording_group(v)
        v.addStretch(1)

    # ── 260609-17(F4): 화면+음성 녹화 설정 ───────────────────
    def _build_recording_group(self, layout):
        grp = QGroupBox(tr("화면+음성 녹화 (발표 전체화면)"))
        self._grp_rec = grp
        f = QFormLayout(grp)

        self.ed_rec_dir = QLineEdit(str(self._prefs.get("recording_dir", "")))
        self.ed_rec_dir.setPlaceholderText(tr("비우면 현재 책갈피 폴더에 저장"))
        b_dir = QPushButton(tr("찾기")); b_dir.clicked.connect(self._pick_rec_dir)
        # 260628(UI): 래퍼 QWidget 의 기본 여백 때문에 입력칸이 안쪽으로 밀렸다 → 여백 0·간격 4
        _w1 = QWidget()
        rd = QHBoxLayout(_w1)
        rd.setContentsMargins(0, 0, 0, 0); rd.setSpacing(4)
        rd.addWidget(self.ed_rec_dir, 1); rd.addWidget(b_dir)
        f.addRow(tr("저장 위치:"), _w1)

        self.cmb_audio = QComboBox()
        for v, t in [("none", tr("영상만(소리 없음)")), ("mic", tr("마이크")),
                     ("system", tr("시스템 소리")), ("both", tr("마이크 + 시스템"))]:
            self.cmb_audio.addItem(t, v)
        am = str(self._prefs.get("recording_audio_mode", "mic"))
        _ai = self.cmb_audio.findData(am)
        self.cmb_audio.setCurrentIndex(_ai if _ai >= 0 else 1)
        f.addRow(tr("오디오:"), self.cmb_audio)

        self.cmb_mic = QComboBox(); self.cmb_mic.setEditable(True)
        self.cmb_mic.setEditText(str(self._prefs.get("recording_mic", "")))
        self.cmb_sys = QComboBox(); self.cmb_sys.setEditable(True)
        self.cmb_sys.setEditText(str(self._prefs.get("recording_system", "")))
        b_dev = QPushButton(tr("오디오 장치 새로고침")); b_dev.clicked.connect(self._refresh_devices)
        f.addRow(tr("마이크 장치:"), self.cmb_mic)
        f.addRow(tr("시스템 장치:"), self.cmb_sys)
        f.addRow("", b_dev)

        # 260618-18: 'ffmpeg 경로' 입력 제거 — ffmpeg 은 설치 폴더에 동봉/복사되어 자동 탐색됨.
        keys = list(self._prefs.get("recording_keys", []) or [])
        self.ks_rec = QKeySequenceEdit(QKeySequence(keys[0]) if len(keys) > 0 and keys[0]
                                       else QKeySequence("Ctrl+R"))
        self.ks_recstop = QKeySequenceEdit(QKeySequence(keys[1]) if len(keys) > 1 and keys[1]
                                           else QKeySequence("Ctrl+Shift+R"))
        f.addRow(tr("녹화/재개 단축키:"), self.ks_rec)
        f.addRow(tr("중지 단축키:"), self.ks_recstop)

        b_test = QPushButton(tr("녹화 테스트 (3초)")); b_test.clicked.connect(self._on_rec_test)
        f.addRow("", b_test)
        info = QLabel(tr("<small>코덱 H.264/AAC·192kbps·30fps·CQ23 고정. 시스템 소리는 "
                         "Stereo Mix 또는 가상 오디오 장치가 있어야 녹음됩니다.</small>"))
        info.setWordWrap(True); info.setStyleSheet("color:#666;")
        f.addRow(info)
        layout.addWidget(grp)

    def _pick_rec_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("녹화 저장 폴더"), self.ed_rec_dir.text())
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
            QMessageBox.information(self, tr("오디오 장치"),
                                    tr("오디오 입력 장치를 찾지 못했습니다(ffmpeg 확인)."))
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
        # 현재 값으로 임시 반영 후 테스트
        self._host._prefs["recording_audio_mode"] = self.cmb_audio.currentData()
        self._host._prefs["recording_mic"] = self.cmb_mic.currentText().strip()
        self._host._prefs["recording_system"] = self.cmb_sys.currentText().strip()
        ok, msg = self._host._test_recording(self)
        # 260611-25: 합격 결과 기록(녹화 시작 전 게이트에서 확인)
        self._host._prefs["recording_test_ok"] = bool(ok)
        try:
            self._host._save_settings_now()
        except Exception:
            pass
        (QMessageBox.information if ok else QMessageBox.warning)(self, tr("녹화 테스트"), msg)

    def result_prefs(self) -> dict:
        return {
            # 260609-17(F4): 녹화
            "recording_dir": self.ed_rec_dir.text().strip(),
            "recording_audio_mode": self.cmb_audio.currentData(),
            "recording_mic": self.cmb_mic.currentText().strip(),
            "recording_system": self.cmb_sys.currentText().strip(),
            "recording_keys": [self.ks_rec.keySequence().toString(),
                               self.ks_recstop.keySequence().toString()],
            "ffmpeg_path": str(self._prefs.get("ffmpeg_path", "")),   # 260618-18: UI 제거, 기존값 보존
        }


class _PanelDialog(QDialog):
    """판 하나를 담은 창(호환 — 앱은 환경설정 한 창을 쓴다, `open_sub_settings`). 속성은 판으로 넘긴다."""

    _title = ""

    def __init__(self, panel: QWidget, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr(self._title))
        self.setMinimumWidth(440)
        self.panel = panel
        v = QVBoxLayout(self)
        area = QScrollArea(); area.setWidgetResizable(True)
        area.setWidget(panel)
        v.addWidget(area, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(520, 600)

    def __getattr__(self, name):
        panel = self.__dict__.get("panel")
        if panel is not None and not name.startswith("__"):
            return getattr(panel, name)
        raise AttributeError(name)

    def result_prefs(self) -> dict:
        return self.panel.result_prefs()


class AdvancedSettingsDialog(_PanelDialog):
    _title = tr_noop("외부 연결")

    def __init__(self, prefs: dict, parent=None):
        super().__init__(AdvancedPanel(prefs), parent)


class RecordingSettingsDialog(_PanelDialog):
    _title = tr_noop("발표 녹화")

    def __init__(self, prefs: dict, parent=None, host=None):
        super().__init__(RecordingPanel(prefs, host=host), parent)


def open_sub_settings(cls, host, parent, saved_msg: str = "", local_prefs=None):
    """261107-12(디자인 SOT §2.14): 따로 뜨던 창은 없다 — 환경설정 한 창의 그 항목으로 연다(`open_settings(page=…)`).
    host 가 없으면(검사) 종전처럼 판 하나를 담은 창. 연 창을 돌려준다."""
    page = "recording" if cls is RecordingSettingsDialog else "external"
    if host is not None and hasattr(host, "open_settings"):
        return host.open_settings(page=page, parent=parent)
    base = dict(local_prefs or {})
    dlg = cls(base, parent, host=host) if cls is RecordingSettingsDialog else cls(base, parent)
    if dlg.exec() == QDialog.DialogCode.Accepted and local_prefs is not None:
        local_prefs.update(dlg.result_prefs())
    return dlg


class SettingsDialog(QDialog):
    """261107-12(디자인 SOT §2.14, 사용자 결정): 환경설정 — 왼쪽 목록(일반/고급) + 쪽, 위에 '설정 찾기', 아래 [확인][적용][취소].
    설정 키는 하나도 바꾸지 않는다(배치만). 저장은 host 의 `_settings_apply` 한 길."""

    def __init__(self, prefs: dict, parent=None, host=None, page: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("환경설정"))
        self._prefs = dict(prefs)
        self._host = host       # 260609-17(F4): 녹화 테스트·장치 조회·저장용
        self._extra_results = []         # 해시태그 내용 등 — add_result_fn
        self._hits = {}                  # 찾기로 강조한 위젯 → 원래 스타일
        self.setMinimumSize(MIN_W, MIN_H)

        outer = QVBoxLayout(self)
        self._outer = outer
        # ── 설정 찾기 ──
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(tr("설정 찾기"))
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._on_search)
        outer.addWidget(self.ed_search)

        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.nav = QListWidget()
        self.nav.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self._page_index = {}            # id → stack 번호
        self._page_items = {}            # id → 목록 줄
        self._scrolls = {}               # id → QScrollArea
        self._group_items = {}
        last_group = None
        for pid, name, group in PAGES:
            if group != last_group:
                hi = QListWidgetItem(page_name("g:" + group))
                hi.setFlags(Qt.ItemFlag.NoItemFlags)       # 머리글 — 고를 수 없다
                f = hi.font(); f.setBold(True); hi.setFont(f)
                self.nav.addItem(hi)
                self._group_items[group] = hi
                last_group = group
            it = QListWidgetItem("   " + page_name(pid))
            it.setData(PAGE_ROLE, pid)
            self.nav.addItem(it)
            self._page_items[pid] = it
            sc = QScrollArea(); sc.setWidgetResizable(True)
            sc.setFrameShape(QScrollArea.Shape.NoFrame)
            content = QWidget(); lay = QVBoxLayout(content)
            sc.setWidget(content)
            self._scrolls[pid] = sc
            self._page_index[pid] = self.stack.addWidget(sc)
            getattr(self, "_build_" + pid)(lay)
            lay.addStretch(1)
        fm = self.nav.fontMetrics()
        self.nav.setFixedWidth(max(fm.horizontalAdvance(self.nav.item(i).text()) for i in range(self.nav.count())) + 36)
        self.nav.currentItemChanged.connect(self._on_nav)

        # ── 단추 ──
        self.btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Apply
                                     | QDialogButtonBox.StandardButton.Cancel, self)
        self.btn_ok = self.btns.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_apply = self.btns.button(QDialogButtonBox.StandardButton.Apply)
        self.btn_cancel = self.btns.button(QDialogButtonBox.StandardButton.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)
        self.btn_apply.clicked.connect(self.apply)
        outer.addWidget(self.btns)

        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.ed_search.setFocus(), self.ed_search.selectAll()))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._step_page(+1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._step_page(-1))

        self._on_restore_toggled(self.rb_start_last.isChecked())
        self._sync_photo_item()
        self._page_items["external"].setHidden(not self.adv.has_visible())
        self._page_items["dict"].setHidden(not self.adv.has_visible())     # 261107-17: 한국 전용 — 같은 규칙
        # 261009-14(디자인 SOT §2.14): 콤보는 가장 긴 항목이 아니라 최소 길이만 요구한다
        for _cb in self.findChildren(QComboBox):
            _cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            _cb.setMinimumContentsLength(14)
        self._connect_changes()
        from viewer.widgets.tag_rules_panel import attach as _attach_tag_rules
        _attach_tag_rules(self)              # 261107-10(태그 SOT §5.8): '해시태그 내용 자리' — 형식 낱말·별칭·사진 종류
        self._applied = self.result_prefs()
        self._update_dirty()

        mem = (host._prefs.get("settings_window") if host is not None and isinstance(getattr(host, "_prefs", None), dict)
               else None) or {}
        try:
            self.resize(max(MIN_W, int(mem.get("w", 760))), max(MIN_H, int(mem.get("h", 560))))
        except (TypeError, ValueError):
            self.resize(760, 560)
        self.open_page(page or mem.get("page") or "general")
        self._fit_width_to_content()
        self._fitted_on_show = False

    # ── 쪽 만들기 ──────────────────────────────────────────────
    def _build_general(self, layout):
        # 언어 — 261009-10(다국어 SOT §4): 묶음 이름을 두 언어로(어느 언어 화면에서도 읽힌다)
        grp_lang = QGroupBox(tr("언어 / Language"))
        ll = QFormLayout(grp_lang)
        from viewer import i18n as _i18n
        self.cmb_language = QComboBox()
        for _code, _name, _status in _i18n.available_languages():
            self.cmb_language.addItem(_name if _status == "complete" else _name + " (β)", _code)
        _cur_lang = str(self._prefs.get("language") or _i18n.language())
        _li = self.cmb_language.findData(_cur_lang)
        self.cmb_language.setCurrentIndex(_li if _li >= 0 else 0)
        ll.addRow(tr("화면 언어 (다시 시작 뒤):"), self.cmb_language)
        layout.addWidget(grp_lang)

        grp_theme = QGroupBox(tr("테마"))
        tl = QFormLayout(grp_theme)
        self.cmb_theme = QComboBox()
        for _val, _lbl in THEME_LABELS:
            self.cmb_theme.addItem(tr(_lbl), _val)
        cur = str(self._prefs.get("theme", "auto"))
        vals = [v for v, _ in THEME_LABELS]
        self.cmb_theme.setCurrentIndex(vals.index(cur) if cur in vals else 0)
        tl.addRow(tr("테마:"), self.cmb_theme)
        layout.addWidget(grp_theme)

        # 시작 — 260906-3(사용자 결정): 파일·폴더를 지정하지 않고 실행했을 때 무엇을 열지 — 3택
        grp_start = QGroupBox(tr("시작"))
        gl = QVBoxLayout(grp_start)
        from PyQt6.QtWidgets import QRadioButton, QButtonGroup
        self.rb_start_last = QRadioButton(tr("마지막에 열었던 폴더·파일 열기 (기본)"))
        self.rb_start_path = QRadioButton(tr("지정한 폴더·파일 열기:"))
        self.rb_start_none = QRadioButton(tr("아무것도 열지 않고 빈 화면으로 시작"))
        self._start_group = QButtonGroup(self)
        for _rb in (self.rb_start_last, self.rb_start_path, self.rb_start_none):
            self._start_group.addButton(_rb)
        _sm = str(self._prefs.get("startup_mode", "last"))
        {"path": self.rb_start_path, "none": self.rb_start_none}.get(_sm, self.rb_start_last).setChecked(True)
        gl.addWidget(self.rb_start_last)
        prow = QHBoxLayout()
        prow.addWidget(self.rb_start_path)
        self.ed_startup_path = QLineEdit(str(self._prefs.get("startup_path", "") or ""))
        self.ed_startup_path.setPlaceholderText(tr("폴더 또는 PDF 파일 경로"))
        prow.addWidget(self.ed_startup_path, 1)
        _bf = QPushButton(tr("폴더")); _bf.clicked.connect(self._pick_startup_folder)
        _bf.setToolTip(tr("시작 시 열 폴더 선택"))
        _bp = QPushButton(tr("파일")); _bp.clicked.connect(self._pick_startup_file)
        _bp.setToolTip(tr("시작 시 열 PDF 선택"))
        prow.addWidget(_bf); prow.addWidget(_bp)
        gl.addLayout(prow)
        gl.addWidget(self.rb_start_none)
        # 종전 키(`restore_session`)는 다운그레이드 호환으로만 저장한다 — 화면에는 없다.
        self.rb_start_last.toggled.connect(self._on_restore_toggled)
        self.chk_last_page = QCheckBox(tr("복원 시 마지막으로 본 페이지 열기 (해제 = 첫 페이지)"))
        self.chk_last_page.setChecked(bool(self._prefs.get("restore_last_page", True)))
        gl.addWidget(self.chk_last_page)
        # 260822: PolyPDF 시작 모드 — 편집 / 보기 (기본 = 편집)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel(tr("PolyPDF 시작 모드:")))
        self.cmb_open_mode = QComboBox()
        self.cmb_open_mode.addItem(tr("편집 모드 (수정·저장 가능)"), "edit")
        self.cmb_open_mode.addItem(tr("보기 모드 (읽기 전용)"), "view")
        self.cmb_open_mode.setCurrentIndex(0 if bool(self._prefs.get("open_edit_mode", True)) else 1)
        mrow.addWidget(self.cmb_open_mode, 1)
        gl.addLayout(mrow)
        layout.addWidget(grp_start)

        # 보기 종류 — 261104-2(사진 보기 SOT 4.10, 사용자 결정 D12): PDF 전용 / 혼용(PDF ↔ 사진 모드 토글)
        grp_vk = QGroupBox(tr("보기 종류"))
        vl = QFormLayout(grp_vk)
        self.cmb_view_kind = QComboBox()
        self.cmb_view_kind.addItem(tr("PDF 전용"), "pdf")
        self.cmb_view_kind.addItem(tr("혼용 (PDF 모드 ↔ 사진 모드)"), "mixed")
        self._pic = self._prefs.get("picture") if isinstance(self._prefs.get("picture"), dict) else {}
        self.cmb_view_kind.setCurrentIndex(1 if self._pic.get("view_kind") == "mixed" else 0)
        self.cmb_view_kind.setToolTip(tr("혼용이면 리본 맨 왼쪽 단추로 사진 모드(PolyPix)를 켜고 끕니다. "
                                         "PDF 전용이면 사진 모드를 쓰지 않습니다."))
        self.cmb_view_kind.currentIndexChanged.connect(lambda *_: self._sync_photo_item())
        vl.addRow(tr("보기 종류:"), self.cmb_view_kind)
        layout.addWidget(grp_vk)

        # 원본 백업 — 261106-15(사진 펴기 [저장] 이 원본을 대체할 때)·261107-29(PDF 첫 덮어쓰기 저장 때) 사진·PDF 공용(사진 보기 SOT §4.43,
        #   마스터 §4.7.5). 보기 종류가 PDF 전용이어도 보이게 사진 쪽에서 일반 쪽으로 옮겼다(키 `picture.warp_backup_dir` 그대로)
        grp_bk = QGroupBox(tr("원본 백업"))
        bl = QVBoxLayout(grp_bk)
        bl.addWidget(QLabel(tr("원본 백업 폴더 (사진·PDF):")))
        row_bk = QHBoxLayout()
        self.ed_warp_backup = QLineEdit(str(self._pic.get("warp_backup_dir") or ""))
        self.ed_warp_backup.setReadOnly(True)
        from viewer.photo_backup import BACKUP_DIRNAME
        self.ed_warp_backup.setPlaceholderText(tr("그 파일 폴더 안 '{name}' (기본)").format(name=BACKUP_DIRNAME))
        self.ed_warp_backup.setToolTip(tr("PDF 를 처음 덮어써 저장할 때·펼친 사진으로 원본을 바꿀 때 손대지 않은 원본을 이 폴더에 남깁니다 — "
                                          "우클릭 '원본으로 되돌리기' 로 되돌립니다."))
        row_bk.addWidget(self.ed_warp_backup, 1)
        b_pick = QPushButton(tr("고르기"))
        b_pick.setToolTip(tr("원본 백업 폴더"))
        b_pick.clicked.connect(self._pick_warp_backup)
        b_def = QPushButton(tr("기본으로"))
        b_def.clicked.connect(lambda: self.ed_warp_backup.setText(""))
        row_bk.addWidget(b_pick)
        row_bk.addWidget(b_def)
        bl.addLayout(row_bk)
        layout.addWidget(grp_bk)

    def _build_view(self, layout):
        grp = QGroupBox(tr("넘김"))
        pl = QVBoxLayout(grp)
        # 260914-1(입력 SOT §2.9·§2.10): 페이지 이동 방식 · 쪽 넘김 애니메이션
        row_psm = QHBoxLayout()
        row_psm.addWidget(QLabel(tr("페이지 이동 방식:")))
        self.cmb_page_scroll_mode = QComboBox()
        self.cmb_page_scroll_mode.addItem(tr("한 쪽씩"), "page")
        self.cmb_page_scroll_mode.addItem(tr("이어 보기 (앞뒤 쪽을 붙여 조금씩 스크롤)"), "continuous")
        self.cmb_page_scroll_mode.setCurrentIndex(
            1 if self._prefs.get("page_scroll_mode", "page") == "continuous" else 0)
        row_psm.addWidget(self.cmb_page_scroll_mode, 1)
        pl.addLayout(row_psm)
        pl.addWidget(_small(tr("이어 보기는 지금 쪽 위아래에 이전·다음 쪽을 붙여 보여 주고, 화면 가운데에 "
                               "온 쪽을 지금 쪽으로 삼습니다(텍스트 창도 그 쪽을 따라갑니다). "
                               "2쪽 보기와 스크린샷 보기는 한 쪽씩입니다.")))
        self.chk_page_flip_anim = QCheckBox(tr("쪽 넘김 애니메이션 (한 쪽씩일 때 위아래로 밀기)"))
        self.chk_page_flip_anim.setChecked(self._prefs.get("page_flip_anim", True) is not False)
        pl.addWidget(self.chk_page_flip_anim)
        # 260609-2 · 260912-6(입력 SOT §2.4): 경계 이동 스위치 — 물음은 그 안의 확인
        self.chk_cross_file_nav = QCheckBox(tr("마지막/첫 페이지에서 다음·이전 파일로 이동 (책갈피창 순서)"))
        self.chk_cross_file_nav.setChecked(self._prefs.get("cross_file_nav", True) is not False)   # 미설정=켜짐
        pl.addWidget(self.chk_cross_file_nav)
        pl.addWidget(_small(tr("켜면 마지막 페이지에서 '다음'을 누를 때 다음 파일의 이름과 첫 쪽을 "
                               "보여 주고 물은 뒤에 옮깁니다(첫 페이지에서 '이전' 도 같습니다). "
                               "책갈피창에서 항목을 골라 옮길 때는 물지 않습니다. 끄면 경계에서 아예 옮기지 않습니다.")))
        layout.addWidget(grp)

        grp_rb = QGroupBox(tr("리본"))
        rl = QVBoxLayout(grp_rb)
        self.chk_show_panel_toolbar = QCheckBox(tr("리본 메뉴 보이기"))
        self.chk_show_panel_toolbar.setChecked(bool(self._prefs.get("show_panel_toolbar", True)))
        rl.addWidget(self.chk_show_panel_toolbar)
        rl.addWidget(_small(tr("해제하면 메인 뷰어 세로 공간이 늘어납니다. 메뉴 탭을 누르면 리본이 잠깐 보이고, "
                               "명령을 고르거나 다른 곳을 누르면 다시 숨습니다. 탭 줄을 우클릭해도 바꿀 수 있습니다.")))
        layout.addWidget(grp_rb)

    def _build_photo(self, layout):
        grp = QGroupBox(tr("사진 모드"))
        pl = QVBoxLayout(grp)
        # 261104-7(사진 보기 SOT 4.12): 슬라이드쇼 자동 넘김 간격(초, 0 = 끔)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("슬라이드쇼 자동 넘김:")))
        self.sp_slide_s = QSpinBox()
        self.sp_slide_s.setRange(0, 600)
        self.sp_slide_s.setSuffix(tr(" 초"))
        self.sp_slide_s.setSpecialValueText(tr("끔"))
        try:
            self.sp_slide_s.setValue(int(self._pic.get("slide_interval_s", 0) or 0))
        except (TypeError, ValueError):
            self.sp_slide_s.setValue(0)
        self.sp_slide_s.setToolTip(tr("사진 모드에서 발표보기(F5)로 연 슬라이드쇼가 이 간격마다 다음 사진으로 넘어갑니다. 0 이면 넘기지 않습니다."))
        row.addWidget(self.sp_slide_s)
        row.addStretch(1)
        pl.addLayout(row)
        layout.addWidget(grp)

    def _build_tags(self, layout):
        grp = QGroupBox(tr("자동 해시태그"))
        gl = QVBoxLayout(grp)
        # 260830(태그 SOT §3.5, 사용자 결정): 태그 자동 부여는 옵트인 — 기본 꺼짐
        self.chk_auto_tag = QCheckBox(tr("파일 해시태그·키워드 자동 부여"))
        self.chk_auto_tag.setChecked(bool(self._prefs.get("auto_tag_enabled", False)))
        gl.addWidget(self.chk_auto_tag)
        gl.addWidget(_small(tr("인덱싱 뒤 백그라운드에서 붙입니다. 자동 태그는 ·# 로 구분되고, "
                               "도구 탭 '태그 ▾' 에서 되돌릴 수 있습니다.")))
        # 261105-6(태그 SOT §5.7, 사용자 결정): 사진 자동 태그 — 기본 켬
        self.chk_photo_tag = QCheckBox(tr("사진 자동 해시태그 (촬영일·지역·장비·스크린샷)"))
        self.chk_photo_tag.setChecked(bool(self._prefs.get("photo_auto_tag", True)))
        gl.addWidget(self.chk_photo_tag)
        self.chk_photo_kind = QCheckBox(tr("사진 종류도 구분 (영수증·명함·서류 — 글자 있는 사진만 OCR)"))
        self.chk_photo_kind.setChecked(bool(self._prefs.get("photo_kind_ocr", True)))
        self.chk_photo_kind.setEnabled(self.chk_photo_tag.isChecked())
        self.chk_photo_tag.toggled.connect(self.chk_photo_kind.setEnabled)
        gl.addWidget(self.chk_photo_kind)
        gl.addWidget(_small(tr("사진 모드에서 폴더를 열면 백그라운드에서 붙입니다. 위치는 동봉한 행정동 자료로 "
                               "찾아 밖으로 보내지 않습니다(국내만). 읽은 글은 종류 판정에만 쓰고 저장하지 않습니다.")))
        layout.addWidget(grp)
        # 해시태그 내용(261107-10 태그 세션이 붙인다 — 디자인 SOT §2.14 '해시태그 내용 자리')
        self.tag_content_box = QWidget()
        self.tag_content_layout = QVBoxLayout(self.tag_content_box)
        self.tag_content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tag_content_box)

    def _build_shots(self, layout):
        grp = QGroupBox(tr("스크린샷"))
        fl = QFormLayout(grp)
        self.spin_screenshot = QSpinBox()
        self.spin_screenshot.setRange(5, 1000)   # v1.6.2: 일괄 캡쳐 시 자동 확장 대비 상한 ↑
        self.spin_screenshot.setValue(int(self._prefs.get("screenshot_max", 30)))
        self.spin_screenshot.setSuffix(tr(" 개"))
        fl.addRow(tr("스크린샷 리스트:"), self.spin_screenshot)
        fl.addRow(_small(tr("한도 변경은 즉시 반영됩니다. 줄이면 가장 오래된 항목부터 자동 제거됩니다.<br>"
                            "검색결과 일괄 캡쳐 시 결과 수가 한도를 넘으면 자동으로 한도가 늘어납니다.")))
        # 260906-3(사용자 결정): 시작은 항상 빈 목록, 종료 때 목록이 있으면 PDF 저장 여부를 묻는다(스크린샷 SOT)
        fl.addRow(_small(tr("캡처 목록은 항상 빈 상태로 시작합니다. 종료할 때 목록이 있으면 PDF 저장 여부를 묻습니다.")))
        layout.addWidget(grp)

    def _build_shortcuts(self, layout):
        defs = getattr(self._host, "_sc_defs", None)
        if not defs:
            self.sc_panel = None
            layout.addWidget(QLabel(tr("단축키 표가 없습니다.")))
            return
        from viewer.widgets.shortcuts_dialog import ShortcutsPanel
        self.sc_panel = ShortcutsPanel(defs, dict(self._prefs.get("shortcuts") or {}), self,
                                       capture_global=bool(self._prefs.get("capture_global", False)), scroll=False)
        self.sc_panel.changed.connect(self.mark_changed)
        layout.addWidget(self.sc_panel)

    def _build_ribbon(self, layout):
        if self._host is None or not hasattr(self._host, "ribbon_catalog"):
            self.ribbon_panel = None
            layout.addWidget(QLabel(tr("모음 메뉴 정보가 없습니다.")))
            return
        from viewer.widgets.ribbon import RibbonCustomizePanel
        catalog, labels = self._host.ribbon_catalog()
        current = [str(x) for x in (self._prefs.get("ribbon_collection") or [])] or list(self._host._collection_ids())
        self.ribbon_panel = RibbonCustomizePanel(catalog, current, labels, self)
        self.ribbon_panel.changed.connect(self.mark_changed)
        grp = QGroupBox(tr("모음 메뉴 관리"))
        gl = QVBoxLayout(grp)
        gl.addWidget(self.ribbon_panel)
        layout.addWidget(grp)

    def _build_external(self, layout):
        self.adv = AdvancedPanel(self._prefs, self, check_login=False)
        layout.addWidget(self.adv)

    def _build_dict(self, layout):
        """261107-17(단어장 SOT §11.1): '고급 › 사전' — 인터넷 사전 키(외부 연결 판에서 옮겨 단다) · 기본 선택 판 · 바로 실행 묶음."""
        layout.addWidget(self.adv.grp_online_dict)
        from viewer.widgets.dict_manager_dialog import attach_settings
        attach_settings(self, layout)

    def _build_recording(self, layout):
        self.rec = RecordingPanel(self._prefs, self, host=self._host)
        layout.addWidget(self.rec)

    def _build_tuning(self, layout):
        grp = QGroupBox(tr("넘김"))
        fl = QFormLayout(grp)
        # 261021-1(응답성 SOT §4.7): 가벼운 넘김 — 느린 컴퓨터·절전 모드
        self.cmb_lite_flip = QComboBox()
        self.cmb_lite_flip.addItem(tr("자동 (절전 모드이거나 넘김이 느릴 때)"), "auto")
        self.cmb_lite_flip.addItem(tr("항상"), "on")
        self.cmb_lite_flip.addItem(tr("끄기"), "off")
        _li = self.cmb_lite_flip.findData(str(self._prefs.get("lite_flip", "auto")))
        self.cmb_lite_flip.setCurrentIndex(_li if _li >= 0 else 0)
        self.cmb_lite_flip.setToolTip(tr("켜지면 넘김 애니메이션을 끄고, 잇달아 넘기면 가운데 쪽은 건너뛰며, "
                                         "텍스트 창은 넘김이 멈춘 뒤 따라가고, 다음 쪽을 미리 그려 둡니다."))
        fl.addRow(tr("가벼운 넘김(느린 컴퓨터):"), self.cmb_lite_flip)
        layout.addWidget(grp)
        # 260609-11(C8): 하이퍼링크 버튼 상단 오프셋
        grp_hl = QGroupBox(tr("하이퍼링크"))
        hlf = QFormLayout(grp_hl)
        self.spin_hl_offset = QSpinBox()
        self.spin_hl_offset.setRange(0, 200)
        self.spin_hl_offset.setSuffix(" px")
        self.spin_hl_offset.setValue(int(self._prefs.get("hyperlink_top_offset_px", 10)))
        hlf.addRow(tr("페이지 내 버튼 상단 오프셋:"), self.spin_hl_offset)
        layout.addWidget(grp_hl)

    def _build_manage(self, layout):
        grp = QGroupBox(tr("언어팩"))
        gl = QVBoxLayout(grp)
        # 261008-29(다국어 SOT §3.4, 사용자 결정): 외부 언어팩 — 기본 꺼짐, 다시 시작할 때 읽는다
        from viewer import i18n as _i18n
        self.chk_ext_lang = QCheckBox(tr("외부 언어팩 사용 (다시 시작 뒤)"))
        self.chk_ext_lang.setToolTip(tr("설정 폴더의 locale\\<코드>\\ 에 둔 언어팩(.mo·pack.json)을 언어 목록에 더합니다. "
                                        "같은 코드면 내장 팩 대신 씁니다. 번역자가 릴리스 없이 시험할 때 씁니다."))
        self.chk_ext_lang.setChecked(bool(self._prefs.get("external_language_packs", False)))
        self.chk_ext_lang.toggled.connect(self._on_ext_lang_toggled)   # 처음 값을 넣은 뒤 — 켤 때만 확인
        btn_ext = QPushButton(tr("폴더 열기"))
        btn_ext.setToolTip(str(_i18n.external_dir()))
        btn_ext.clicked.connect(self._open_external_lang_dir)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.chk_ext_lang); row.addWidget(btn_ext); row.addStretch(1)
        gl.addLayout(row)
        layout.addWidget(grp)
        # 261016-3(사용자 지시): 기본값 저장(배포용) 아래 설정 초기화 — 둘 다 지금 **저장된** 설정을 다룬다
        grp_def = QGroupBox(tr("설정 값"))
        dl = QVBoxLayout(grp_def)
        self.btn_save_default = QPushButton(tr("현재 설정을 기본값으로 저장(배포용)"))
        self.btn_reset_default = QPushButton(tr("설정 초기화(기본값으로 되돌리기)"))
        dl.addWidget(self.btn_save_default)
        dl.addWidget(self.btn_reset_default)
        dl.addWidget(_small(tr("둘 다 지금 저장된 설정을 다룹니다 — 이 창에서 바꾼 것은 [적용] 뒤에 들어갑니다. "
                               "초기화하면 PolyPDF 를 다시 시작합니다.")))
        host = self._host
        if host is not None:
            from PyQt6.QtCore import QTimer as _QT
            self.btn_save_default.clicked.connect(lambda: host._save_current_as_default())
            self.btn_reset_default.clicked.connect(lambda: (self.reject(), _QT.singleShot(0, host._reset_to_defaults)))
        else:
            self.btn_save_default.setEnabled(False)
            self.btn_reset_default.setEnabled(False)
        layout.addWidget(grp_def)

    # ── 목록·쪽 ──────────────────────────────────────────────
    def page_ids(self) -> list:
        return [p for p, _n, _g in PAGES]

    def current_page(self) -> str:
        it = self.nav.currentItem()
        return it.data(PAGE_ROLE) if it is not None else ""

    def open_page(self, pid: str) -> None:
        it = self._page_items.get(pid)
        if it is None or it.isHidden():
            it = next((self._page_items[p] for p in self.page_ids() if not self._page_items[p].isHidden()), None)
        if it is not None:
            self.nav.setCurrentItem(it)

    def _on_nav(self, cur, _prev):
        pid = cur.data(PAGE_ROLE) if cur is not None else None
        if not pid:
            return
        self.stack.setCurrentIndex(self._page_index[pid])
        if pid == "external":
            self.adv.check_login_once()          # 느린 조회는 이 쪽을 처음 볼 때(응답성 SOT §5)

    def _step_page(self, d: int) -> None:
        ids = [p for p in self.page_ids() if not self._page_items[p].isHidden()]
        cur = self.current_page()
        if cur in ids:
            self.open_page(ids[(ids.index(cur) + d) % len(ids)])

    def _sync_photo_item(self) -> None:
        """'사진' 은 보기 종류가 혼용일 때만 목록에(디자인 SOT §2.14)."""
        on = (self.cmb_view_kind.currentData() == "mixed")
        self._page_items["photo"].setHidden(not on)
        if not on and self.current_page() == "photo":
            self.open_page("general")

    # ── 찾기 ────────────────────────────────────────────────
    @staticmethod
    def _texts_of(w) -> list:
        import re as _re
        out = []
        for getter in ("text", "title", "toolTip", "placeholderText"):
            fn = getattr(w, getter, None)
            if callable(fn):
                try:
                    t = fn()
                except TypeError:
                    continue
                if isinstance(t, str) and t:
                    out.append(_re.sub(r"<[^>]+>", " ", t))
        if isinstance(w, QComboBox):
            out += [w.itemText(i) for i in range(w.count())]
        return out

    def _search_hits(self, pid: str, needle: str) -> list:
        content = self._scrolls[pid].widget()
        hits = []
        for w in content.findChildren(QWidget):
            if not w.isVisibleTo(content) or isinstance(w, (QScrollArea,)):
                continue
            if any(needle in t.lower() for t in self._texts_of(w)):
                hits.append(w)
        return hits

    def _clear_hits(self) -> None:
        for w, ss in list(self._hits.items()):
            try:
                w.setStyleSheet(ss)
            except RuntimeError:
                pass
        self._hits = {}

    def _on_search(self, text: str) -> None:
        self._clear_hits()
        needle = (text or "").strip().lower()
        if not needle:
            for pid in self.page_ids():
                self._page_items[pid].setHidden(False)
            self._page_items["external"].setHidden(not self.adv.has_visible())
            self._page_items["dict"].setHidden(not self.adv.has_visible())
            self._sync_photo_item()
            return
        hl = self.palette().color(self.palette().ColorRole.Highlight)
        css = "background-color: rgba(%d,%d,%d,70);" % (hl.red(), hl.green(), hl.blue())
        first_page = None
        for pid, name, _g in PAGES:
            visible_ok = not (pid in ("external", "dict") and not self.adv.has_visible()) and not (
                pid == "photo" and self.cmb_view_kind.currentData() != "mixed")
            hits = self._search_hits(pid, needle) if visible_ok else []
            name_hit = visible_ok and needle in page_name(pid).lower()
            self._page_items[pid].setHidden(not (hits or name_hit))
            for w in hits:
                self._hits[w] = w.styleSheet()
                w.setStyleSheet((w.styleSheet() or "") + css)
            if (hits or name_hit) and first_page is None:
                first_page = (pid, hits)
        if first_page is not None:
            pid, hits = first_page
            if self.current_page() != pid and (self._page_items.get(self.current_page()) is None
                                               or self._page_items[self.current_page()].isHidden()):
                self.open_page(pid)
            cur = self.current_page()
            cur_hits = [w for w in self._hits if self._scrolls[cur].widget().isAncestorOf(w)]
            if cur_hits:
                self._scrolls[cur].ensureWidgetVisible(cur_hits[0])

    # ── 바뀜·저장 ────────────────────────────────────────────
    def _connect_changes(self) -> None:
        from PyQt6.QtWidgets import QAbstractButton
        for w in self.stack.findChildren(QLineEdit):
            w.textChanged.connect(self.mark_changed)
        for w in self.stack.findChildren(QAbstractButton):
            if w.isCheckable():
                w.toggled.connect(self.mark_changed)
        for w in self.stack.findChildren(QComboBox):
            w.currentIndexChanged.connect(self.mark_changed)
            if w.isEditable():
                w.editTextChanged.connect(self.mark_changed)
        for w in self.stack.findChildren(QSpinBox):
            w.valueChanged.connect(self.mark_changed)
        for w in self.stack.findChildren(QKeySequenceEdit):
            w.keySequenceChanged.connect(self.mark_changed)

    def mark_changed(self, *_a) -> None:
        """값이 바뀌었을 수 있다 — [적용] 을 켜고 끈다(붙인 위젯도 이 함수를 잇는다)."""
        self._update_dirty()

    def add_result_fn(self, fn) -> None:
        """저장할 값을 더 내는 함수(fn() → dict)를 건다 — 해시태그 내용(261107-10) 등."""
        self._extra_results.append(fn)
        self._applied = self.result_prefs()
        self._update_dirty()

    def is_dirty(self) -> bool:
        return getattr(self, "_applied", None) != self.result_prefs()

    def _update_dirty(self) -> None:
        if hasattr(self, "btn_apply"):
            self.btn_apply.setEnabled(self.is_dirty())

    def apply(self) -> bool:
        """[적용] — 저장하고 창은 그대로. 바뀐 것이 없으면 아무 일도 하지 않는다."""
        if not self.is_dirty():
            return False
        new = self.result_prefs()
        fn = getattr(self._host, "_settings_apply", None)
        if callable(fn):
            fn(new)
        self._applied = new
        self._prefs.update(new)
        self._update_dirty()
        return True

    def _remember(self) -> None:
        host = self._host
        if host is not None and isinstance(getattr(host, "_prefs", None), dict):
            host._prefs["settings_window"] = {"page": self.current_page() or "general",
                                              "w": int(self.width()), "h": int(self.height())}

    def accept(self):
        self.apply()
        self._remember()
        super().accept()

    def reject(self):
        """[취소] — 마지막 [적용] 뒤의 바꿈은 버린다(저장하지 않는다)."""
        self._remember()
        super().reject()

    # ── 그 밖 ───────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        # 처음 보일 때 한 번 더 — 스타일·글꼴이 실제 화면 것으로 입혀진 뒤의 크기로(261009-14)
        if not getattr(self, "_fitted_on_show", True):
            self._fitted_on_show = True
            self._fit_width_to_content()

    def _fit_width_to_content(self):
        """261009-10(디자인 SOT §2.14): 쪽에 **가로 스크롤바가 생기지 않게** 창 폭을 가장 넓은 쪽 내용에 맞춘다(그만큼만)."""
        m = self._outer.contentsMargins()
        widest = 0
        for pid in self.page_ids():
            if pid in ("external", "dict") and not self.adv.has_visible():
                continue                         # 261107-17: 한국 전용 쪽은 이 화면에서 늘 숨는다 — 폭에 넣지 않는다
            sc = self._scrolls[pid]
            widest = max(widest, sc.widget().minimumSizeHint().width() + sc.verticalScrollBar().sizeHint().width()
                         + 2 * sc.frameWidth())
        need = widest + self.nav.width() + self._outer.spacing() + 12 + m.left() + m.right()
        self.setMinimumWidth(max(MIN_W, need))
        if self.width() < need:
            self.resize(need, self.height())

    def _on_restore_toggled(self, on: bool):
        """'마지막에 열었던 …' 일 때만 '마지막 페이지' 항목이 뜻을 가진다."""
        self.chk_last_page.setEnabled(bool(on))

    def _pick_startup_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("시작 시 열 폴더 선택"), self.ed_startup_path.text() or "")
        if d:
            self.ed_startup_path.setText(d)
            self.rb_start_path.setChecked(True)

    def _pick_startup_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("시작 시 열 PDF 선택"), self.ed_startup_path.text() or "", "PDF (*.pdf)")
        if f:
            self.ed_startup_path.setText(f)
            self.rb_start_path.setChecked(True)

    def _pick_warp_backup(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("원본 백업 폴더"), self.ed_warp_backup.text() or "")
        if d:
            self.ed_warp_backup.setText(d)

    def result_prefs(self) -> dict:
        out = {
            "startup_mode": ("path" if self.rb_start_path.isChecked()
                             else "none" if self.rb_start_none.isChecked() else "last"),
            "startup_path": self.ed_startup_path.text().strip(),
            # 다운그레이드 호환 — 구버전은 이 키만 본다(있으면 '마지막 것 열기'로 동작).
            "restore_session": not self.rb_start_none.isChecked(),
            "restore_last_page": self.chk_last_page.isChecked(),
            "restore_screenshots": False,          # 260906-3: 시작은 항상 빈 목록
            "auto_tag_enabled": self.chk_auto_tag.isChecked(),      # 260830: 옵트인(태그 SOT §3.5)
            "photo_auto_tag": self.chk_photo_tag.isChecked(),       # 261105-6(태그 SOT §5.7): 기본 켬
            "photo_kind_ocr": self.chk_photo_kind.isChecked(),
            "open_edit_mode": (self.cmb_open_mode.currentData() == "edit"),
            "screenshot_max": int(self.spin_screenshot.value()),
            "show_panel_toolbar": self.chk_show_panel_toolbar.isChecked(),
            "cross_file_nav": self.chk_cross_file_nav.isChecked(),
            "page_flip_anim": self.chk_page_flip_anim.isChecked(),         # 260914-1
            "lite_flip": str(self.cmb_lite_flip.currentData() or "auto"),  # 261021-1(응답성 SOT §4.7)
            "picture": dict(self._pic, view_kind=str(self.cmb_view_kind.currentData() or "pdf"),
                            slide_interval_s=int(self.sp_slide_s.value()),    # 261104-2 · 261104-7
                            warp_backup_dir=self.ed_warp_backup.text().strip()),   # 261106-15
            "page_scroll_mode": self.cmb_page_scroll_mode.currentData() or "page",
            "hyperlink_top_offset_px": int(self.spin_hl_offset.value()),   # 260609-11(C8)
            "theme": self.cmb_theme.currentData(),                          # 260606-13
            "language": self.cmb_language.currentData(),     # 261008(다국어 SOT §4)
            "external_language_packs": self.chk_ext_lang.isChecked(),   # 261008-29(다국어 SOT §3.4)
        }
        if getattr(self, "ribbon_panel", None) is not None:
            from viewer.widgets.ribbon import DEFAULT_COLLECTION
            ids = [str(x) for x in self.ribbon_panel.result_ids()]
            out["ribbon_collection"] = [] if ids == [str(x) for x in DEFAULT_COLLECTION] else ids   # 빈 값 = 기본값
        else:
            out["ribbon_collection"] = [str(x) for x in (self._prefs.get("ribbon_collection") or [])]
        if getattr(self, "sc_panel", None) is not None:
            out["shortcuts"] = self.sc_panel.result_shortcuts()
            out["capture_global"] = bool(self.sc_panel.result_capture_global())
        out.update(self.adv.result_prefs())
        out.update(self.rec.result_prefs())
        for fn in self._extra_results:
            try:
                out.update(fn() or {})
            except Exception:
                pass
        return out

    def _on_ext_lang_toggled(self, on: bool):
        """외부 언어팩을 켤 때 한 번 확인한다(다국어 SOT §13 '외부 팩의 신뢰'). 끌 때는 묻지 않는다."""
        if not on:
            return
        ans = QMessageBox.question(
            self, tr("외부 언어팩 사용"),
            tr("외부 언어팩은 릴리스와 함께 검사받지 않은 번역입니다.\n"
               "프로그램을 바꾸지는 못하지만 단추·안내 문구를 다르게 보이게 할 수 있습니다.\n"
               "믿을 수 있는 곳에서 받은 언어팩만 쓰세요.\n\n켤까요?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            self.chk_ext_lang.setChecked(False)

    def _open_external_lang_dir(self):
        """외부 언어팩 폴더를 만들고(없으면) 탐색기로 연다(다국어 SOT §3.4)."""
        from viewer import i18n as _i18n
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        d = _i18n.external_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
