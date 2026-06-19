# -*- coding: utf-8 -*-
"""260611-19: 발표 전체화면 발표시간(프레젠테이션 타이머).

세 요소로 분리(유지보수):
  - ToneEngine          : 내장 사인파 톤 WAV 생성 + QSoundEffect 재생(외부 자산 0)
  - PresTimerController  : 상태머신 + 시간/알람 계산(위젯 비소유 — 순수 로직, 테스트 용이)
  - PresTimerDialog      : 옵션 설정 창
"""
from __future__ import annotations
import os
import math
import time
import wave
import struct
import tempfile
import copy

from PyQt6.QtCore import Qt, QUrl


# ===== 기본 설정 =====
DEFAULT_PRES_TIMER = {
    "rec_on_start": True,                # 260611-28: 기본 체크(타이머 시작 시 녹화)
    "duration_sec": 300,                 # 5분
    "count_dir": "down",                 # down(반대로) | up(0→지정)
    "standby": {
        "lines": [
            {"text": "준비", "size": 64, "font": "맑은 고딕"},
            {"text": "", "size": 32, "font": "맑은 고딕"},
        ],
        "w_frac": 0.5, "h_frac": 0.5,
        "bg_color": "#000000", "bg_alpha": 50,
        "border": "round",               # rect | round
        "image": "",                     # 260611-22: 준비 배경 그림(base64 PNG, cover-crop)
    },
    "pos": "top-right",                  # top-right | top-left
    "margin": 24,
    "font": {
        "family": "돋움", "size": 0, "bold": True,   # size 0 = 자동(화면H/15)
        "color": "auto",                 # auto(배경 보색) | #rrggbb
        "bg": "none",                    # none | color
        "bg_color": "#ffffff", "bg_alpha": 50, "bg_pad_pct": 10,
    },
    "alarm": {
        "end": {"sound": "bell_end", "vol": 80},
        "pre": [{"start_sec": 60, "interval_sec": 0, "sound": "bell", "vol": 70, "count": 0}],
    },
}


def merge_timer_cfg(cfg) -> dict:
    """사용자 설정을 기본값에 깊은 병합(누락 키 보충, 하위호환)."""
    out = copy.deepcopy(DEFAULT_PRES_TIMER)
    if not isinstance(cfg, dict):
        return out
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = copy.deepcopy(v)
    # standby/font/alarm 의 누락 하위키 보충
    for sect in ("standby", "font", "alarm"):
        base = copy.deepcopy(DEFAULT_PRES_TIMER[sect])
        base.update(out.get(sect) or {})
        out[sect] = base
    if not out["standby"].get("lines"):
        out["standby"]["lines"] = copy.deepcopy(DEFAULT_PRES_TIMER["standby"]["lines"])
    return out


# ===== 톤 엔진 =====
class ToneEngine:
    """내장 톤 WAV 를 1회 생성·캐시하고 QSoundEffect 로 재생."""

    PRESETS = {                          # sound key -> 주파수(Hz) 또는 [연속음]
        "beep_high": 1200, "beep_mid": 800, "beep_low": 440, "blip": [1000, 1400],
    }
    # 260611-20: 첨부 종소리 WAV(resources 번들)
    RESOURCE_SOUNDS = {
        "bell_end": "snd_bell_end.wav",   # 종료용(2.0s)
        "bell_high": "snd_bell_high.wav",  # 높은 종소리(1.5s)
        "bell": "snd_bell.wav",            # 종소리(1.5s)
    }
    # (표시명, key) — '없음' 포함. 종소리(첨부)를 앞에.
    NAMES = [("없음", "none"),
             ("종소리(종료)", "bell_end"), ("높은 종소리", "bell_high"), ("종소리", "bell"),
             ("높은음 삑", "beep_high"), ("중간음 딩", "beep_mid"),
             ("낮은음 부저", "beep_low"), ("짧은 2연음", "blip")]

    def __init__(self):
        self._effects = {}
        self._dir = None

    def _gen_wav(self, sound):
        spec = self.PRESETS.get(sound)
        if spec is None:
            return None
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="polypdf_tone_")
        path = os.path.join(self._dir, sound + ".wav")
        if os.path.exists(path):
            return path
        sr = 44100
        freqs = spec if isinstance(spec, list) else [spec]
        seg = 0.18
        frames = []
        for fr in freqs:
            n = int(sr * seg)
            ramp = sr * 0.01
            for i in range(n):
                env = min(1.0, i / ramp, (n - i) / ramp)
                val = int(32767 * 0.6 * env * math.sin(2 * math.pi * fr * i / sr))
                frames.append(struct.pack("<h", val))
        try:
            with wave.open(path, "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(b"".join(frames))
        except Exception:
            return None
        return path

    def _ensure(self, sound):
        if not sound or sound == "none":
            return None
        if sound in self._effects:
            return self._effects[sound]
        path = None
        if sound in self.RESOURCE_SOUNDS:           # 260611-20: 번들 종소리 WAV
            try:
                from viewer.resources_path import resource_path
                path = resource_path(self.RESOURCE_SOUNDS[sound])
            except Exception:
                path = None
        if not path:
            path = self._gen_wav(sound)             # 폴백: 내장 톤 생성
        if not path:
            return None
        try:
            from PyQt6.QtMultimedia import QSoundEffect
            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(path))
            self._effects[sound] = eff
            return eff
        except Exception:
            return None

    def play(self, sound, vol):
        eff = self._ensure(sound)
        if eff is None:
            return False
        try:
            eff.setVolume(max(0.0, min(1.0, float(vol) / 100.0)))
            eff.play()
            return True
        except Exception:
            return False

    def stop_all(self):
        for e in self._effects.values():
            try:
                e.stop()
            except Exception:
                pass


# ===== 상태머신 + 시간/알람 계산 =====
class PresTimerController:
    OFF, STANDBY, RUNNING, OVERTIME = "OFF", "STANDBY", "RUNNING", "OVERTIME"

    def __init__(self, cfg):
        self.set_config(cfg)
        self.state = self.OFF
        self._start = None          # running 시작 시각(monotonic 초)
        self._fired = set()         # 이미 울린 알람 키
        self._paused = False        # 260611-22: 중지(시계 멈춤)
        self._pause_elapsed = 0.0

    def set_config(self, cfg):
        cfg = merge_timer_cfg(cfg)
        self.cfg = cfg
        self.duration = max(1, int(cfg.get("duration_sec", 300)))
        self.count_dir = cfg.get("count_dir", "down")
        self.alarm = cfg.get("alarm", {}) or {}

    @staticmethod
    def _now(now=None):
        return time.monotonic() if now is None else float(now)

    # --- 전이 ---
    def off(self):
        self.state = self.OFF
        self._start = None
        self._fired = set()
        self._paused = False

    def arm_standby(self):
        self.state = self.STANDBY
        self._paused = False

    def start_running(self, now=None):
        """준비에서 다음 → 지정시간으로 리셋·시작."""
        self.state = self.RUNNING
        self._start = self._now(now)
        self._fired = set()
        self._paused = False

    def resume_running(self, now=None):
        """뒤로가기 등 — 리셋 없이 연속(지나간 시간 감안)."""
        self._paused = False
        if self._start is None:
            self.start_running(now)
            return
        self.state = self.OVERTIME if self.elapsed(now) >= self.duration else self.RUNNING

    # --- 260611-22: 중지(시계 멈춤)/재개 ---
    def pause(self, now=None):
        if self.state in (self.RUNNING, self.OVERTIME) and not self._paused:
            self._pause_elapsed = self.elapsed(now)
            self._paused = True

    def resume(self, now=None):
        if self._paused:
            self._start = self._now(now) - self._pause_elapsed
            self._paused = False

    def is_paused(self):
        return self._paused and self.state in (self.RUNNING, self.OVERTIME)

    # --- 계산 ---
    def elapsed(self, now=None):
        if self._paused:
            return self._pause_elapsed
        if self._start is None:
            return 0.0
        return max(0.0, self._now(now) - self._start)

    def remaining(self, now=None):
        return self.duration - self.elapsed(now)

    @staticmethod
    def _fmt(sec):
        sec = int(max(0, sec))
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def display(self, now=None):
        """현재 표시 문자열(mm:ss). STANDBY/OFF 는 None."""
        if self.state in (self.OFF, self.STANDBY):
            return None
        el = self.elapsed(now)
        if el < self.duration:
            val = (self.duration - el) if self.count_dir == "down" else el
        else:
            val = el - self.duration        # 초과 — 00:00 부터 증가
        return self._fmt(val)

    def _pre_targets(self, row):
        start = int(row.get("start_sec", 0))
        interval = int(row.get("interval_sec", 0))
        if start <= 0:
            return []
        if interval <= 0:
            targets = [start]
        else:
            targets = list(range(start, 0, -interval))
        count = int(row.get("count", 0) or 0)     # 260611-22: 반복 횟수(0=무제한)
        if count > 0:
            targets = targets[:count]
        return targets

    def tick(self, now=None):
        """200ms 주기 호출. {state,text,fired:[(sound,vol)]} 반환."""
        fired = []
        if self._paused:                          # 260611-22: 중지 중엔 멈춤(알람 없음)
            return {"state": self.state, "text": self.display(now), "fired": fired}
        if self.state in (self.RUNNING, self.OVERTIME):
            el = self.elapsed(now)
            rem = self.duration - el
            # 종료(초과 진입) + 종료 알람
            if el >= self.duration:
                if self.state == self.RUNNING:
                    self.state = self.OVERTIME
                if "end" not in self._fired:
                    self._fired.add("end")
                    a = self.alarm.get("end") or {}
                    if a.get("sound", "none") != "none":
                        fired.append((a.get("sound"), int(a.get("vol", 70))))
            # 사전 알람(시작~종료 반복). 260611-21: 이후(더 늦게 시작=start_sec 더 작은)
            #   알람이 시작되면 이전 알람의 반복을 중지(중복 울림 방지).
            pre = self.alarm.get("pre") or []
            starts = [int(r.get("start_sec", 0)) for r in pre]
            for i, row in enumerate(pre):
                snd = row.get("sound", "none")
                if snd == "none":
                    continue
                vol = int(row.get("vol", 70))
                S = int(row.get("start_sec", 0))
                # 이후 알람의 시작 시각 중 가장 큰 값(=가장 먼저 시작하는 '이후' 알람) 이후로는 중지
                cutoff = max([s for j, s in enumerate(starts) if j != i and s < S], default=0)
                for t in self._pre_targets(row):
                    if t <= cutoff:           # 이후 알람이 시작된 구간 → 반복 중지
                        continue
                    key = f"pre{i}@{t}"
                    if key in self._fired:
                        continue
                    if rem <= t:
                        self._fired.add(key)
                        if rem > 0:           # 종료 전에만(종료는 end 알람이 담당)
                            fired.append((snd, vol))
        return {"state": self.state, "text": self.display(now), "fired": fired}


# ===== 설정 다이얼로그 =====
def open_settings_dialog(parent, cfg):
    """모달 실행. 확인 시 새 cfg(dict) 반환, 취소 시 None."""
    dlg = PresTimerDialog(parent, cfg)
    from PyQt6.QtWidgets import QDialog
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.get_config()
    return None


def _mmss(sec):
    sec = int(max(0, sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _pix_to_b64(pm):
    """QPixmap → base64 PNG 문자열."""
    from PyQt6.QtCore import QBuffer, QByteArray
    import base64
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(ba)).decode("ascii")


def b64_to_pix(b64):
    """base64 PNG → QPixmap."""
    from PyQt6.QtGui import QPixmap
    import base64
    pm = QPixmap()
    try:
        pm.loadFromData(base64.b64decode(b64), "PNG")
    except Exception:
        pass
    return pm


def _parse_mmss(text, default=0):
    try:
        parts = str(text).strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(float(text))
    except Exception:
        return default


class PresTimerDialog:
    """절차적 구성 — QDialog 를 감싼 빌더. get_config() 로 결과 dict."""

    def __init__(self, parent, cfg):
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QScrollArea, QWidget,
                                     QDialogButtonBox)
        self.cfg = merge_timer_cfg(cfg)
        self._tone = ToneEngine()
        self.dlg = QDialog(parent)
        self.dlg.setWindowTitle("발표시간 설정")
        self.dlg.resize(820, 860)
        self.dlg.setMinimumWidth(760)
        outer = QVBoxLayout(self.dlg)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); self.form = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._build()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.dlg.accept)
        bb.rejected.connect(self.dlg.reject)
        outer.addWidget(bb)

    # --- 헬퍼 ---
    def _group(self, title):
        from PyQt6.QtWidgets import QGroupBox, QVBoxLayout
        g = QGroupBox(title)
        v = QVBoxLayout(g)
        self.form.addWidget(g)
        return v

    def _sound_combo(self, cur):
        from PyQt6.QtWidgets import QComboBox
        c = QComboBox()
        for name, key in ToneEngine.NAMES:
            c.addItem(name, key)
        idx = max(0, [k for _, k in ToneEngine.NAMES].index(cur) if cur in
                  [k for _, k in ToneEngine.NAMES] else 0)
        c.setCurrentIndex(idx)
        return c

    def _vol_slider(self, cur):
        from PyQt6.QtWidgets import QSlider
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, 100); s.setValue(int(cur)); s.setFixedWidth(120)
        return s

    def _mmss_input(self, total):
        """260611-20: 분/초를 명확히 입력하는 위젯. w._get()=총 초."""
        from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSpinBox, QLabel
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(2)
        mm = QSpinBox(); mm.setRange(0, 999); mm.setValue(int(total) // 60)
        mm.setSuffix("분"); mm.setFixedWidth(64)
        ss = QSpinBox(); ss.setRange(0, 59); ss.setValue(int(total) % 60)
        ss.setSuffix("초"); ss.setFixedWidth(60)
        h.addWidget(mm); h.addWidget(QLabel(":")); h.addWidget(ss)
        w._get = lambda: mm.value() * 60 + ss.value()
        return w

    def _color_btn(self, cur):
        from PyQt6.QtWidgets import QPushButton
        from PyQt6.QtGui import QColor
        b = QPushButton(cur)
        b._color = cur

        def pick():
            from PyQt6.QtWidgets import QColorDialog
            col = QColorDialog.getColor(QColor(b._color), self.dlg)
            if col.isValid():
                b._color = col.name()
                b.setText(b._color)
                b.setStyleSheet(f"background:{b._color};")
        b.clicked.connect(pick)
        b.setStyleSheet(f"background:{cur};")
        return b

    def _build(self):
        from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QSpinBox,
                                     QComboBox, QLineEdit, QFontComboBox, QRadioButton,
                                     QPushButton, QWidget, QSlider, QButtonGroup,
                                     QGridLayout)
        from PyQt6.QtGui import QFont
        c = self.cfg
        self._standby_img = c["standby"].get("image", "")

        # 260611-28: '타이머 시작시 녹화시작'은 전체화면 우클릭 메뉴로 이동(여기서 제거).

        # 2) 준비내용
        g = self._group("준비내용")
        self.sb_lines = []
        for i in range(2):
            ln = (c["standby"]["lines"] + [{}, {}])[i]
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{i+1}줄"))
            ed = QLineEdit(str(ln.get("text", "")))
            fc = QFontComboBox(); fc.setCurrentFont(QFont(ln.get("font", "맑은 고딕")))
            sz = QSpinBox(); sz.setRange(8, 300); sz.setValue(int(ln.get("size", 48)))
            row.addWidget(ed, 1); row.addWidget(fc); row.addWidget(QLabel("크기")); row.addWidget(sz)
            g.addLayout(row)
            self.sb_lines.append((ed, fc, sz))
        srow = QHBoxLayout()
        srow.addWidget(QLabel("박스 폭%"))
        self.sb_wfrac = QSpinBox(); self.sb_wfrac.setRange(10, 100)
        self.sb_wfrac.setValue(int(c["standby"]["w_frac"] * 100)); srow.addWidget(self.sb_wfrac)
        srow.addWidget(QLabel("높이%"))
        self.sb_hfrac = QSpinBox(); self.sb_hfrac.setRange(10, 100)
        self.sb_hfrac.setValue(int(c["standby"]["h_frac"] * 100)); srow.addWidget(self.sb_hfrac)
        srow.addWidget(QLabel("배경"))
        self.bt_sbg = self._color_btn(c["standby"]["bg_color"]); srow.addWidget(self.bt_sbg)
        srow.addWidget(QLabel("투명도%"))
        self.sb_salpha = QSpinBox(); self.sb_salpha.setRange(0, 100)
        self.sb_salpha.setValue(int(c["standby"]["bg_alpha"])); srow.addWidget(self.sb_salpha)
        g.addLayout(srow)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("테두리 모양"))
        self.cmb_border = QComboBox()
        self.cmb_border.addItem("직사각형", "rect")
        self.cmb_border.addItem("원형테두리 직사각형", "round")
        self.cmb_border.setCurrentIndex(0 if c["standby"]["border"] == "rect" else 1)
        brow.addWidget(self.cmb_border); brow.addStretch(1)
        g.addLayout(brow)
        # 배경 그림(첨부) — 박스 크기에 cover-crop, 박스 투명도를 그림 투명도로 적용
        irow = QHBoxLayout()
        irow.addWidget(QLabel("배경 그림"))
        bt_img = QPushButton("그림 첨부…")
        bt_img.clicked.connect(self._pick_standby_image)
        bt_paste = QPushButton("클립보드 붙여넣기")
        bt_paste.clicked.connect(self._paste_standby_image)
        bt_clr = QPushButton("그림 제거")
        bt_clr.clicked.connect(self._clear_standby_image)
        self.lbl_img = QLabel("")
        irow.addWidget(bt_img); irow.addWidget(bt_paste)
        irow.addWidget(bt_clr); irow.addWidget(self.lbl_img)
        irow.addStretch(1)
        g.addLayout(irow)
        self._update_img_label()

        # 3) 발표시간 + 카운트 방향
        g = self._group("발표시간")
        trow = QHBoxLayout()
        trow.addWidget(QLabel("5분 단위"))
        self.cmb_dur = QComboBox()
        for m in range(5, 65, 5):
            self.cmb_dur.addItem(f"{m}분", m * 60)
        trow.addWidget(self.cmb_dur)
        trow.addWidget(QLabel("직접입력(분)"))
        self.sb_dur = QSpinBox(); self.sb_dur.setRange(1, 100000)
        self.sb_dur.setValue(max(1, int(c["duration_sec"]) // 60))
        trow.addWidget(self.sb_dur); trow.addStretch(1)
        g.addLayout(trow)
        # 콤보 ↔ 직접입력 동기
        self.cmb_dur.activated.connect(
            lambda _i: self.sb_dur.setValue(self.cmb_dur.currentData() // 60))
        drow = QHBoxLayout()
        self.rb_down = QRadioButton("반대로 카운트 (지정 → 0)")
        self.rb_up = QRadioButton("0 → 지정")
        (self.rb_down if c["count_dir"] == "down" else self.rb_up).setChecked(True)
        bg = QButtonGroup(self.dlg); bg.addButton(self.rb_down); bg.addButton(self.rb_up)
        drow.addWidget(self.rb_down); drow.addWidget(self.rb_up); drow.addStretch(1)
        g.addLayout(drow)

        # 4) 시간표시 위치
        g = self._group("시간 표시 위치")
        prow = QHBoxLayout()
        self.rb_tr = QRadioButton("우상단"); self.rb_tl = QRadioButton("좌상단")
        (self.rb_tr if c["pos"] == "top-right" else self.rb_tl).setChecked(True)
        bg2 = QButtonGroup(self.dlg); bg2.addButton(self.rb_tr); bg2.addButton(self.rb_tl)
        prow.addWidget(self.rb_tr); prow.addWidget(self.rb_tl)
        prow.addWidget(QLabel("끝단 거리(px)"))
        self.sb_margin = QSpinBox(); self.sb_margin.setRange(0, 600)
        self.sb_margin.setValue(int(c["margin"])); prow.addWidget(self.sb_margin)
        prow.addStretch(1)
        g.addLayout(prow)

        # 5) 글자
        g = self._group("글자")
        f = c["font"]
        frow = QHBoxLayout()
        frow.addWidget(QLabel("폰트"))
        self.fc_font = QFontComboBox(); self.fc_font.setCurrentFont(QFont(f.get("family", "돋움")))
        frow.addWidget(self.fc_font)
        frow.addWidget(QLabel("크기(0=자동)"))
        self.sb_fsize = QSpinBox(); self.sb_fsize.setRange(0, 500); self.sb_fsize.setValue(int(f.get("size", 0)))
        frow.addWidget(self.sb_fsize)
        self.cb_bold = QCheckBox("굵게"); self.cb_bold.setChecked(bool(f.get("bold", True)))
        frow.addWidget(self.cb_bold); frow.addStretch(1)
        g.addLayout(frow)
        crow = QHBoxLayout()
        self.cb_auto_col = QCheckBox("색 자동(배경 보색)")
        self.cb_auto_col.setChecked(f.get("color", "auto") == "auto")
        crow.addWidget(self.cb_auto_col)
        crow.addWidget(QLabel("사용자 색"))
        self.bt_fcol = self._color_btn(f.get("color") if f.get("color", "auto") != "auto" else "#ffffff")
        crow.addWidget(self.bt_fcol); crow.addStretch(1)
        g.addLayout(crow)
        brow2 = QHBoxLayout()
        self.cb_fbg = QCheckBox("글자 배경 사용")
        self.cb_fbg.setChecked(f.get("bg", "none") == "color")
        brow2.addWidget(self.cb_fbg)
        brow2.addWidget(QLabel("배경색"))
        self.bt_fbg = self._color_btn(f.get("bg_color", "#ffffff")); brow2.addWidget(self.bt_fbg)
        brow2.addWidget(QLabel("투명도%"))
        self.sb_fbg_alpha = QSpinBox(); self.sb_fbg_alpha.setRange(0, 100)
        self.sb_fbg_alpha.setValue(int(f.get("bg_alpha", 50))); brow2.addWidget(self.sb_fbg_alpha)
        brow2.addWidget(QLabel("여백%"))
        self.sb_fbg_pad = QSpinBox(); self.sb_fbg_pad.setRange(0, 200)
        self.sb_fbg_pad.setValue(int(f.get("bg_pad_pct", 10))); brow2.addWidget(self.sb_fbg_pad)
        g.addLayout(brow2)

        # 6) 알람
        g = self._group("알람")
        a = c["alarm"]
        erow = QHBoxLayout()
        erow.addWidget(QLabel("종료 알람 소리"))
        self.cmb_end_snd = self._sound_combo((a.get("end") or {}).get("sound", "beep_mid"))
        erow.addWidget(self.cmb_end_snd)
        erow.addWidget(QLabel("음량"))
        self.sl_end_vol = self._vol_slider((a.get("end") or {}).get("vol", 70))
        erow.addWidget(self.sl_end_vol)
        bt = QPushButton("테스트")
        bt.clicked.connect(lambda: self._tone.play(self.cmb_end_snd.currentData(),
                                                   self.sl_end_vol.value()))
        erow.addWidget(bt); erow.addStretch(1)
        g.addLayout(erow)
        g.addWidget(QLabel("사전 알람 (최대 7행) — 시작=종료 전 시각(분:초), 간격=분:초(0=1회), 반복=횟수(0=무제한)"))
        self.pre_rows = []
        self.pre_box = QGridLayout()
        hdr = ["시작(종료 전)", "간격", "소리", "음량", "반복", "", ""]
        for ci, h in enumerate(hdr):
            self.pre_box.addWidget(QLabel(h), 0, ci)
        g.addLayout(self.pre_box)
        addr = QHBoxLayout()
        self.bt_add_pre = QPushButton("＋ 행 추가")
        self.bt_add_pre.clicked.connect(lambda: self._add_pre_row())
        addr.addWidget(self.bt_add_pre); addr.addStretch(1)
        g.addLayout(addr)
        for row in (a.get("pre") or []):
            self._add_pre_row(row)

    def _add_pre_row(self, row=None):
        from PyQt6.QtWidgets import QPushButton, QSpinBox
        if len(self.pre_rows) >= 7:
            return
        row = row or {}
        r = self.pre_box.rowCount()
        w_start = self._mmss_input(int(row.get("start_sec", 60)))
        w_int = self._mmss_input(int(row.get("interval_sec", 0)))
        cmb = self._sound_combo(row.get("sound", "bell"))
        vol = self._vol_slider(int(row.get("vol", 70)))
        cnt = QSpinBox(); cnt.setRange(0, 99); cnt.setValue(int(row.get("count", 0) or 0))
        cnt.setSuffix("회"); cnt.setFixedWidth(64); cnt.setToolTip("0=무제한")
        test = QPushButton("테스트")
        test.clicked.connect(lambda _=False, c=cmb, v=vol: self._tone.play(c.currentData(), v.value()))
        rm = QPushButton("✕")
        item = (w_start, w_int, cmb, vol, cnt, test, rm)
        self.pre_box.addWidget(w_start, r, 0)
        self.pre_box.addWidget(w_int, r, 1)
        self.pre_box.addWidget(cmb, r, 2)
        self.pre_box.addWidget(vol, r, 3)
        self.pre_box.addWidget(cnt, r, 4)
        self.pre_box.addWidget(test, r, 5)
        self.pre_box.addWidget(rm, r, 6)
        self.pre_rows.append(item)

        def remove():
            for w in item:
                w.setParent(None)
            if item in self.pre_rows:
                self.pre_rows.remove(item)
        rm.clicked.connect(remove)

    def _update_img_label(self):
        self.lbl_img.setText("첨부됨 ✓" if self._standby_img else "없음")

    def _pick_standby_image(self):
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtGui import QPixmap
        fn, _ = QFileDialog.getOpenFileName(
            self.dlg, "준비 배경 그림 선택", "",
            "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not fn:
            return
        pm = QPixmap(fn)
        if pm.isNull():
            return
        if pm.width() > 1200 or pm.height() > 1200:
            pm = pm.scaled(1200, 1200, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self._standby_img = _pix_to_b64(pm)
        self._update_img_label()

    def _paste_standby_image(self):
        """260611-28: 클립보드 이미지를 준비 배경 그림으로."""
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from PyQt6.QtGui import QPixmap, QImage
        cb = QApplication.clipboard()
        pm = QPixmap()
        img = cb.image()
        if img is not None and not img.isNull():
            pm = QPixmap.fromImage(img)
        if pm.isNull():
            md = cb.mimeData()
            if md is not None and md.hasImage():
                qi = md.imageData()
                if isinstance(qi, QImage) and not qi.isNull():
                    pm = QPixmap.fromImage(qi)
        if pm.isNull():
            QMessageBox.information(self.dlg, "붙여넣기", "클립보드에 이미지가 없습니다.")
            return
        if pm.width() > 1200 or pm.height() > 1200:
            pm = pm.scaled(1200, 1200, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self._standby_img = _pix_to_b64(pm)
        self._update_img_label()

    def _clear_standby_image(self):
        self._standby_img = ""
        self._update_img_label()

    def exec(self):
        return self.dlg.exec()

    def get_config(self):
        from PyQt6.QtWidgets import QDialog
        c = copy.deepcopy(self.cfg)   # rec_on_start 는 메뉴에서 관리(여기선 보존)
        # 준비내용
        lines = []
        for ed, fc, sz in self.sb_lines:
            lines.append({"text": ed.text(), "font": fc.currentFont().family(),
                          "size": int(sz.value())})
        c["standby"]["lines"] = lines
        c["standby"]["w_frac"] = self.sb_wfrac.value() / 100.0
        c["standby"]["h_frac"] = self.sb_hfrac.value() / 100.0
        c["standby"]["bg_color"] = self.bt_sbg._color
        c["standby"]["bg_alpha"] = self.sb_salpha.value()
        c["standby"]["border"] = self.cmb_border.currentData()
        c["standby"]["image"] = self._standby_img
        # 발표시간
        c["duration_sec"] = max(1, int(self.sb_dur.value()) * 60)
        c["count_dir"] = "down" if self.rb_down.isChecked() else "up"
        # 위치
        c["pos"] = "top-right" if self.rb_tr.isChecked() else "top-left"
        c["margin"] = int(self.sb_margin.value())
        # 글자
        c["font"]["family"] = self.fc_font.currentFont().family()
        c["font"]["size"] = int(self.sb_fsize.value())
        c["font"]["bold"] = self.cb_bold.isChecked()
        c["font"]["color"] = "auto" if self.cb_auto_col.isChecked() else self.bt_fcol._color
        c["font"]["bg"] = "color" if self.cb_fbg.isChecked() else "none"
        c["font"]["bg_color"] = self.bt_fbg._color
        c["font"]["bg_alpha"] = self.sb_fbg_alpha.value()
        c["font"]["bg_pad_pct"] = self.sb_fbg_pad.value()
        # 알람
        end = {"sound": self.cmb_end_snd.currentData(), "vol": self.sl_end_vol.value()}
        pre = []
        for w_start, w_int, cmb, vol, cnt, _t, _r in self.pre_rows:
            pre.append({"start_sec": int(w_start._get()),
                        "interval_sec": int(w_int._get()),
                        "sound": cmb.currentData(), "vol": vol.value(),
                        "count": int(cnt.value())})
        c["alarm"] = {"end": end, "pre": pre}
        return c
