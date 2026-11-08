"""환경설정 '읽기 음성' 쪽 (영상·음성 SOT §1.10, 261108-28) — 엔진(자동/Windows 기본/자연 음성)·목소리·음질.

설정 키 `tts_voice` = {'engine', 'sid', 'quality'}(`tts_engine.normalize_cfg`). 저장은 환경설정 한 길(`result_prefs` →
`_settings_apply` → `_apply_prefs` 허용목록). 자연 음성이 없으면 [구성요소 설치…] 로 받는다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QTableWidget, QVBoxLayout, QWidget)

from viewer.i18n import tr


def attach(dlg, layout) -> None:
    """설정 창 `dlg` 의 쪽 `layout` 에 '읽기 음성' 묶음을 단다. dlg._extra_results 에 결과 함수를 더한다."""
    from viewer.study import tts_engine, neural_tts
    cur = tts_engine.normalize_cfg((getattr(dlg, "_prefs", None) or {}).get("tts_voice"))
    grp = QGroupBox(tr("읽기 음성"))
    f = QFormLayout(grp)

    cb_eng = QComboBox()
    cb_eng.setObjectName("cmbTtsEngine")
    for key, label in (("auto", tr("자동 (자연 음성이 있으면 그것)")),
                       ("neural", tr("자연 음성 (Supertonic 3)")),
                       ("sapi", tr("Windows 기본 음성 (SAPI)"))):
        cb_eng.addItem(label, key)
    cb_eng.setCurrentIndex(max(0, cb_eng.findData(cur["engine"])))
    f.addRow(tr("엔진"), cb_eng)

    cb_sid = QComboBox()
    cb_sid.setObjectName("cmbTtsVoice")
    for i in range(neural_tts.SPEAKERS):
        cb_sid.addItem(tr("목소리 {n}").format(n=i + 1), i)
    cb_sid.setCurrentIndex(max(0, cb_sid.findData(cur["sid"])))
    f.addRow(tr("목소리"), cb_sid)

    cb_q = QComboBox()
    cb_q.setObjectName("cmbTtsQuality")
    cb_q.addItem(tr("빠름 (기본)"), "fast")
    cb_q.addItem(tr("고음질 (첫 소리가 늦다)"), "high")
    cb_q.setCurrentIndex(max(0, cb_q.findData(cur["quality"])))
    f.addRow(tr("음질"), cb_q)

    # 261108-28(SOT §1.10 '앞단'): 사용자가 들어 보고 고른다 — 기본 둘 다 켬
    ck_norm = QCheckBox(tr("숫자·단위 풀어 읽기 (25 mm → 25 밀리미터, 3개 → 세 개)"))
    ck_norm.setObjectName("chkTtsNormalize")
    ck_norm.setChecked(cur["normalize"])
    f.addRow(ck_norm)
    ck_split = QCheckBox(tr("한국어 문장 속 긴 영어 구절은 영어로 읽기"))
    ck_split.setObjectName("chkTtsSplitLang")
    ck_split.setChecked(cur["split_lang"])
    f.addRow(ck_split)

    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    st = QLabel()
    st.setObjectName("lblTtsNeuralState")

    def _show_state():
        st.setText(tr("자연 음성 설치됨 ✓") if tts_engine.neural_ready()
                   else tr("자연 음성 미설치 — 지금은 Windows 기본 음성으로 읽습니다"))
    _show_state()
    h.addWidget(st, 1)
    btn = QPushButton(tr("구성요소 설치"))
    btn.setObjectName("btnTtsComponents")
    host = getattr(dlg, "_host", None)
    btn.setEnabled(host is not None and hasattr(host, "_open_components_installer"))
    # 261108-32(디자인 SOT §2.14 '모달 위 창'): 환경설정(모달) 위에 뜨도록 이 창을 부모로 — 메인을 부모로 띄우면 뒤에 숨었다
    btn.clicked.connect(lambda: host._open_components_installer(parent=dlg))
    h.addWidget(btn)
    if host is not None:
        def _on_comp_done(key, ok):                    # 설치가 끝나면 상태 글을 곧바로
            if key == "voice":
                tts_engine.invalidate()
                _show_state()
        host.__dict__.setdefault("_comp_listeners", []).append(_on_comp_done)

        def _on_closed(*_):
            """환경설정을 닫을 때 그 위에 단 구성요소 창은 메인 창으로 옮겨 단다(받는 중이면 계속 보이게)."""
            try:
                host._comp_listeners.remove(_on_comp_done)
            except (AttributeError, ValueError):
                pass
            cd = getattr(host, "_comp_dlg", None)
            try:
                if cd is not None and cd.parent() is dlg:
                    vis = cd.isVisible()
                    cd.setParent(host, cd.windowFlags())
                    if vis:
                        cd.show()
            except RuntimeError:
                pass
        if hasattr(dlg, "finished"):
            dlg.finished.connect(_on_closed)
    f.addRow(row)
    note = QLabel("<small>%s</small>" % tr("자연 음성은 AI 로 만든 소리입니다(모델 라이선스 OpenRAIL-M — 정보 창의 고지). "
                                          "목소리·음질과 위의 두 칸은 자연 음성에만 쓰입니다."))
    note.setWordWrap(True)
    f.addRow(note)
    layout.addWidget(grp)

    # ── 261108-33: 목소리 이름 · Windows 성우 쓰지 않음 · 미리 듣기 ──────────────────────
    pv = _Preview(dlg, host, cur, cb_q)
    dlg.tts_preview = pv

    g_n = QGroupBox(tr("자연 음성 목소리 — 이름 붙이기·미리 듣기"))
    vn = QVBoxLayout(g_n)
    tb_n = QTableWidget(tts_engine.SPEAKERS, 2)
    tb_n.setObjectName("tblTtsNeuralVoices")
    tb_n.setHorizontalHeaderLabels([tr("이름 (비우면 '목소리 N')"), ""])
    tb_n.verticalHeader().setVisible(False)
    tb_n.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    tb_n.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    ready = tts_engine.neural_ready()
    for i in range(tts_engine.SPEAKERS):
        ed = QLineEdit(cur["names"][i])
        ed.setPlaceholderText(tr("목소리 {n}").format(n=i + 1))
        ed.setMaxLength(40)
        tb_n.setCellWidget(i, 0, ed)
        b = _play_button()
        b.setObjectName("btnPreviewNeural%d" % i)
        b.setToolTip(tr("들어 보기"))
        b.setEnabled(ready)                                # 자연 음성 미설치면 끈다
        b.clicked.connect(lambda _c=False, s=i: pv.toggle(("neural", s)))
        tb_n.setCellWidget(i, 1, b)
        pv.buttons[("neural", i)] = b
    tb_n.setMinimumHeight(min(10, tts_engine.SPEAKERS) * 26 + 30)
    vn.addWidget(tb_n)
    layout.addWidget(g_n)

    def _names():
        return [tb_n.cellWidget(i, 0).text().strip() for i in range(tts_engine.SPEAKERS)]

    def _relabel(*_):                                    # 이름을 고치면 '목소리' 고르기에도 곧바로
        c = dict(cur, names=_names())
        for i in range(cb_sid.count()):
            cb_sid.setItemText(i, tts_engine.voice_label(c, i))
    for i in range(tts_engine.SPEAKERS):
        tb_n.cellWidget(i, 0).textChanged.connect(_relabel)
    _relabel()

    g_w = QGroupBox(tr("Windows 음성 — 쓰지 않을 성우 끄기·미리 듣기"))
    vw = QVBoxLayout(g_w)
    sapi_names = []
    try:
        if host is not None:
            sapi_names = host._study_get_tts().all_voice_names()
    except Exception:
        sapi_names = []
    tb_w = QTableWidget(len(sapi_names), 2)
    tb_w.setObjectName("tblTtsSapiVoices")
    tb_w.setHorizontalHeaderLabels([tr("사용"), ""])
    tb_w.verticalHeader().setVisible(False)
    tb_w.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    tb_w.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    for i, nm in enumerate(sapi_names):
        ck = QCheckBox(nm)
        ck.setChecked(nm not in cur["hidden_sapi"])
        tb_w.setCellWidget(i, 0, ck)
        b = _play_button()
        b.setToolTip(tr("들어 보기"))
        b.clicked.connect(lambda _c=False, n=nm: pv.toggle(("sapi", n)))
        tb_w.setCellWidget(i, 1, b)
        pv.buttons[("sapi", nm)] = b
    tb_w.setMinimumHeight(max(1, len(sapi_names)) * 26 + 30)
    vw.addWidget(tb_w)
    vw.addWidget(_small(tr(
        "끈 성우는 읽기 메뉴의 성우 목록과 언어별 기본 음성에서 빠집니다. 시스템에 설치된 음성 자체는 지우지 않습니다"
        "(Windows 설정 › 시간 및 언어 › 음성). 한 언어의 성우를 모두 끄면 자연 음성이 없거나 실패할 때만 그중 하나로 읽습니다.")))
    layout.addWidget(g_w)

    g_s = QGroupBox(tr("미리 듣기 글"))
    vs = QVBoxLayout(g_s)
    # 한국어 한 줄·영어 한 줄(설정 `sample` 에는 두 줄을 줄바꿈으로 이어 둔다 — 빈칸이면 기본)
    d_ko, d_en = (tts_engine.DEFAULT_SAMPLE.split("\n") + [""])[:2]
    s_lines = [x for x in (cur["sample"] or "").split("\n")]
    ed_ko = QLineEdit(s_lines[0] if s_lines and s_lines[0] else "")
    ed_ko.setObjectName("edTtsSampleKo")
    ed_ko.setPlaceholderText(d_ko)
    ed_en = QLineEdit(s_lines[1] if len(s_lines) > 1 else "")
    ed_en.setObjectName("edTtsSampleEn")
    ed_en.setPlaceholderText(d_en)
    fs = QFormLayout()
    fs.addRow(tr("한국어"), ed_ko)
    fs.addRow(tr("영어"), ed_en)
    vs.addLayout(fs)
    pv.status = QLabel("")
    pv.status.setObjectName("lblTtsPreview")
    vs.addWidget(pv.status)
    vs.addWidget(_small(tr(
        "자연 음성은 글 전체를, Windows 성우는 그 성우 언어의 줄만 읽습니다. 지금 고른 음질로 읽습니다.")))
    layout.addWidget(g_s)
    pv.sample = lambda: "\n".join([ed_ko.text().strip() or d_ko, ed_en.text().strip() or d_en])
    if hasattr(dlg, "finished"):
        dlg.finished.connect(lambda *_: pv.stop())       # 창을 닫으면 멈춘다

    def _sync():
        on = cb_eng.currentData() != "sapi"
        cb_sid.setEnabled(on)
        cb_q.setEnabled(on)
        ck_norm.setEnabled(on)
        ck_split.setEnabled(on)
    cb_eng.currentIndexChanged.connect(lambda *_: _sync())
    _sync()
    dlg.cmb_tts_engine, dlg.cmb_tts_voice, dlg.cmb_tts_quality = cb_eng, cb_sid, cb_q
    dlg.chk_tts_normalize, dlg.chk_tts_split = ck_norm, ck_split
    dlg.tbl_tts_names, dlg.tbl_tts_sapi = tb_n, tb_w
    dlg.ed_tts_sample_ko, dlg.ed_tts_sample_en = ed_ko, ed_en

    def result():
        hidden = [tb_w.cellWidget(i, 0).text() for i in range(tb_w.rowCount())
                  if not tb_w.cellWidget(i, 0).isChecked()]
        # 목록에 안 보인(지금 설치되지 않은) 이름도 숨김 값은 지킨다
        hidden = sorted(set(hidden) | (set(cur["hidden_sapi"]) - set(sapi_names)))
        ko, en = ed_ko.text().strip(), ed_en.text().strip()
        sample = (ko + "\n" + en) if (ko or en) else ""
        return {"tts_voice": {"engine": cb_eng.currentData(), "sid": int(cb_sid.currentData()),
                              "quality": cb_q.currentData(), "normalize": ck_norm.isChecked(),
                              "split_lang": ck_split.isChecked(), "names": _names(), "hidden_sapi": hidden,
                              "sample": sample}}
    dlg._extra_results.append(result)


def _small(text: str) -> QLabel:
    """표 아래 작은 글씨 풀이 — 줄바꿈(설정 창이 가로로 늘지 않게, 디자인 SOT §2.14)."""
    lab = QLabel("<small>%s</small>" % text)
    lab.setWordWrap(True)
    return lab


def _play_button():
    """▶/■ 미리 듣기 단추 — 글리프 대신 색 아이콘(디자인 SOT §4.5 — 글리프 ▶ 는 기준선 탓에 처진다)."""
    from PyQt6.QtCore import QSize
    from viewer.widgets.icons import color_icon
    b = QPushButton()
    b.setIcon(color_icon("play"))
    b.setIconSize(QSize(14, 14))
    b.setProperty("previewPlaying", False)
    return b


class _Preview:
    """261108-33: 환경설정 미리 듣기 — 한 번에 하나. 같은 단추를 다시 누르거나 다른 성우를 누르면 앞 소리를 멈춘다.

    자연 음성은 `NeuralReader`(배경 일꾼 스레드가 싣고 합성 — 메인에서 합성·싣기 없음, 응답성 SOT §4.8), 모델을 처음 싣는 동안
    '준비 중…'. Windows 성우는 SAPI 를 그 성우로 잠깐 고정해 그 언어 줄만 읽는다(비동기)."""

    def __init__(self, dlg, host, cur, cb_quality):
        from PyQt6.QtCore import QTimer
        self.dlg, self.host, self.cur, self.cb_q = dlg, host, cur, cb_quality
        self.buttons = {}
        self.playing = None
        self.status = None
        self.sample = lambda: ""
        self._nr = None
        self._t = QTimer(dlg)
        self._t.setInterval(120)
        self._t.timeout.connect(self._poll)

    def neural(self):
        """자연 음성 읽개 — 창의 것을 다시 쓴다(모델을 두 번 싣지 않게). 창이 없으면(검사) 따로 만든다."""
        if self._nr is None:
            from viewer.study.neural_tts import NeuralReader
            nr = getattr(self.host, "_neural_reader", None) if self.host is not None else None
            if nr is None:
                nr = NeuralReader(self.host if self.host is not None else self.dlg)
                if self.host is not None:
                    self.host._neural_reader = nr
            self._nr = nr
        return self._nr

    def sapi(self):
        return self.host._study_get_tts() if self.host is not None else None

    def _set(self, key, playing):
        b = self.buttons.get(key)
        if b is not None:
            try:
                from viewer.widgets.icons import color_icon
                b.setIcon(color_icon("stop" if playing else "play"))
                b.setProperty("previewPlaying", bool(playing))
            except RuntimeError:
                pass

    def toggle(self, key):
        again = (self.playing == key)
        self.stop()
        if again:
            return                                     # 같은 단추를 다시 누름 = 멈춤
        kind, who = key
        text = self.sample()
        ok = False
        if kind == "neural":
            from viewer.study import neural_tts
            nr = self.neural()
            q = self.cb_q.currentData() if self.cb_q is not None else "fast"
            nr.configure(nr.sid, q, nr.normalize, nr.split_lang)
            nr.warm_up()
            ok = nr.speak_reading(text, sid=int(who))
        else:
            t = self.sapi()
            if t is not None:
                import re
                lang = t.voice_lang(who) or "en"
                lines = [ln for ln in text.splitlines() if ln.strip()
                         and (bool(re.search(r"[가-힣]", ln)) == (lang == "ko"))]
                say = " ".join(lines) or text
                old = getattr(t, "_forced_name", None)
                t.set_voice_name(who)
                ok = t.speak(say, "kor" if lang == "ko" else "eng")
                t.set_voice_name(old)
        if ok:
            self.playing = key
            self._set(key, True)
            if self.status is not None:
                self.status.setText(tr("준비 중…") if kind == "neural" else "")
            self._t.start()

    def _engine(self):
        if self.playing is None:
            return None
        return self.neural() if self.playing[0] == "neural" else self.sapi()

    def _poll(self):
        e = self._engine()
        if e is None:
            self._t.stop()
            return
        if self.playing[0] == "neural" and self.status is not None:
            fed = getattr(e, "_fed", 0)
            self.status.setText(tr("준비 중…") if (fed == 0 and e.is_speaking()) else tr("재생 중"))
        if not e.is_speaking():
            self.stop()

    def stop(self):
        e = self._engine()
        if e is not None:
            try:
                e.stop()
            except Exception:
                pass
        if self.playing is not None:
            self._set(self.playing, False)
        self.playing = None
        self._t.stop()
        if self.status is not None:
            try:
                self.status.setText("")
            except RuntimeError:
                pass
