"""환경설정 '읽기 음성' 쪽 (영상·음성 SOT §1.10, 261108-28) — 엔진(자동/Windows 기본/자연 음성)·목소리·음질.

설정 키 `tts_voice` = {'engine', 'sid', 'quality'}(`tts_engine.normalize_cfg`). 저장은 환경설정 한 길(`result_prefs` →
`_settings_apply` → `_apply_prefs` 허용목록). 자연 음성이 없으면 [구성요소 설치…] 로 받는다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QWidget

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

    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    ready = tts_engine.neural_ready()
    st = QLabel(tr("자연 음성 설치됨 ✓") if ready else tr("자연 음성 미설치 — 지금은 Windows 기본 음성으로 읽습니다"))
    st.setObjectName("lblTtsNeuralState")
    h.addWidget(st, 1)
    btn = QPushButton(tr("구성요소 설치"))
    host = getattr(dlg, "_host", None)
    btn.setEnabled(host is not None and hasattr(host, "_open_components_installer"))
    btn.clicked.connect(lambda: host._open_components_installer())
    h.addWidget(btn)
    f.addRow(row)
    note = QLabel("<small>%s</small>" % tr("자연 음성은 AI 로 만든 소리입니다(모델 라이선스 OpenRAIL-M — 정보 창의 고지). "
                                          "목소리·음질은 자연 음성에만 쓰입니다."))
    note.setWordWrap(True)
    f.addRow(note)
    layout.addWidget(grp)

    def _sync():
        on = cb_eng.currentData() != "sapi"
        cb_sid.setEnabled(on)
        cb_q.setEnabled(on)
    cb_eng.currentIndexChanged.connect(lambda *_: _sync())
    _sync()
    dlg.cmb_tts_engine, dlg.cmb_tts_voice, dlg.cmb_tts_quality = cb_eng, cb_sid, cb_q

    def result():
        return {"tts_voice": {"engine": cb_eng.currentData(), "sid": int(cb_sid.currentData()),
                              "quality": cb_q.currentData()}}
    dlg._extra_results.append(result)
