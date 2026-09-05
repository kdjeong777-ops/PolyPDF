"""260905(발표 SOT §4.2): 발표 '보기 설정' — 크롭 4방향·홀짝 좌우 + 미리보기.

종전에는 `app.py` 안에서 즉석으로 조립하던 다이얼로그였다. 상·하 크롭 두 개일 때는
그럴 만했지만 4방향·홀짝·미리보기가 붙으면서 위젯이 열 개를 넘어 별도 모듈로 뺐다.

계약(호출부 = `PresentMixin._on_present_view_settings`):
  * 값은 **퍼센트 정수**(0~45)로 주고받는다. 저장은 호출부가 `PageMetaStore` 로 한다.
  * `renderer(page0, dpi) -> QPixmap` 은 **크롭 전** 픽스맵(회전은 반영)을 준다.
  * `preview_pages` 는 미리보기에 늘어놓을 쪽 목록. 좌우 2쪽 보기면 `[좌, 우]`(빈 칸은
    `None`), 아니면 `[현재쪽]`. **상하 2분할은 반영하지 않는다**(사용자 지정 §4.2.3).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

CROP_MAX = 45
PREVIEW_GAP_PX = 8          # 미리보기 펼침 간격
_RAW_TARGET_PX = 700        # 원본 픽스맵 캐시 목표 폭(스핀 조작 때 재렌더하지 않기 위함)
RAW_CACHE_MAX = 8           # 쪽 이동으로 캐시가 무한정 쌓이지 않게(§4.2.3)
AUTOFIT_MIN_GAIN_PX = 20    # 이만큼 못 넓히면 넓히지 않는다(되먹임 방지)
AUTOFIT_MAX_SCREEN = 0.92   # 화면 폭의 이 비율까지만 넓힌다


def _crop4(v):
    seq = (list(v or []) + [0, 0, 0, 0])[:4]
    out = []
    for x in seq:
        try:
            out.append(max(0, min(CROP_MAX, int(round(float(x))))))
        except Exception:
            out.append(0)
    return tuple(out)


def _lr2(v):
    seq = (list(v or []) + [0, 0])[:2]
    out = []
    for x in seq:
        try:
            out.append(max(0, min(CROP_MAX, int(round(float(x))))))
        except Exception:
            out.append(0)
    return tuple(out)


class ViewSettingsDialog(QDialog):
    def __init__(self, *, page_no, global_crop, page_crop, has_page_crop,
                 oddeven, preview_pages, renderer, parent=None,
                 pages_for=None, step=None, page_crop_of=None):
        """pages_for(page0)->[쪽…] / step(page0, ±1)->page0|None 은 발표창이 준다.

        둘 다 없으면 쪽 이동 버튼은 비활성이고 `preview_pages` 만 보여 준다.
        page_crop_of(page0)->(t,b,l,r)|None 은 **저장된** 개별 크롭을 알려 준다(§4.2.3.1)."""
        super().__init__(parent)
        self.setWindowTitle("보기 설정")
        self._renderer = renderer
        self._preview_pages = list(preview_pages or [])
        self._page0 = int(page_no) - 1
        self._cur = self._page0         # 미리보기가 보고 있는 쪽 = 개별 크롭 편집 대상
        self._pages_for = pages_for
        self._step_fn = step
        self._page_crop_of = page_crop_of
        self._page_overrides = {}       # {page0: (t,b,l,r)} — '적용'으로 고정한 쪽(§4.2.3.1)
        self._page_clears = set()       # 체크를 꺼서 개별 크롭을 지울 쪽
        self._had_page_crop = bool(has_page_crop)
        self._raw = {}                  # {page0: QPixmap} — 원본 1회 렌더 캐시(최근 RAW_CACHE_MAX)
        self._reset = False
        self._autofit_busy = False
        self._autofit_left = 3          # 되먹임 방지 — 다이얼로그당 최대 3회만 넓힌다

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.setSpacing(8)
        root.addLayout(left, 0)

        g = _crop4(global_crop)
        p = _crop4(page_crop)
        oe_on, oe_odd, oe_even = oddeven if oddeven else (False, (0, 0), (0, 0))

        left.addWidget(QLabel("페이지 가장자리를 잘라 본문을 크게 봅니다(%).\n"
                              "자른 만큼 실제 발표 화면에서 확대됩니다."))

        grp_g = QGroupBox("크롭 — 전체 페이지(전역)")
        gf = QFormLayout(grp_g)
        self.sp_gt, self.sp_gb = self._spin(g[0]), self._spin(g[1])
        self.sp_gl, self.sp_gr = self._spin(g[2]), self._spin(g[3])
        gf.addRow("상단:", self.sp_gt)
        gf.addRow("하단:", self.sp_gb)
        gf.addRow("좌측:", self.sp_gl)
        gf.addRow("우측:", self.sp_gr)
        left.addWidget(grp_g)

        grp_oe = QGroupBox("홀수/짝수 페이지 좌·우 크롭 달리하기")
        of = QFormLayout(grp_oe)
        self.chk_oe = QCheckBox("쪽번호 홀/짝에 따라 좌·우를 따로 적용")
        self.chk_oe.setToolTip("스캔본의 제본 여백처럼 쪽마다 여백이 좌우로 번갈아 생길 때 씁니다.\n"
                               "판정 기준은 PDF 쪽번호(1부터)이며, 맞쪽 빈 페이지와 무관합니다.")
        self.chk_oe.setChecked(bool(oe_on))
        of.addRow(self.chk_oe)
        self.sp_ol, self.sp_or = self._spin(oe_odd[0]), self._spin(oe_odd[1])
        self.sp_el, self.sp_er = self._spin(oe_even[0]), self._spin(oe_even[1])
        of.addRow("홀수쪽 좌측:", self.sp_ol)
        of.addRow("홀수쪽 우측:", self.sp_or)
        of.addRow("짝수쪽 좌측:", self.sp_el)
        of.addRow("짝수쪽 우측:", self.sp_er)
        left.addWidget(grp_oe)

        self.grp_page = QGroupBox(f"크롭 — 개별 쪽 (p.{int(page_no)})")
        grp_p = self.grp_page
        pf = QFormLayout(grp_p)
        # 체크박스 + '적용' 버튼 한 줄 — 버튼은 체크했을 때만 보인다(§4.2.3.1)
        prow = QHBoxLayout()
        self.chk_page = QCheckBox("이 페이지에만 별도 적용")
        self.chk_page.setChecked(bool(has_page_crop))
        self.btn_apply_page = QPushButton("적용")
        self.btn_apply_page.setAutoDefault(False)
        self.btn_apply_page.setToolTip("지금 미리보기에 보이는 쪽에 위 값을 고정합니다.\n"
                                       "쪽을 옮긴 뒤 다시 누르면 그 쪽에도 적용됩니다.")
        self.btn_apply_page.clicked.connect(self._on_apply_page)
        prow.addWidget(self.chk_page)
        prow.addWidget(self.btn_apply_page)
        prow.addStretch(1)
        pf.addRow(prow)
        self.lbl_pinned = QLabel("")
        self.lbl_pinned.setStyleSheet("color:#666;")
        pf.addRow(self.lbl_pinned)
        self.sp_pt, self.sp_pb = self._spin(p[0]), self._spin(p[1])
        self.sp_pl, self.sp_pr = self._spin(p[2]), self._spin(p[3])
        pf.addRow("상단:", self.sp_pt)
        pf.addRow("하단:", self.sp_pb)
        pf.addRow("좌측:", self.sp_pl)
        pf.addRow("우측:", self.sp_pr)
        left.addWidget(grp_p)

        btn_reset = QPushButton("크롭 초기화(이 파일 전체)")
        btn_reset.clicked.connect(self._on_reset)
        left.addWidget(btn_reset)
        left.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)

        # --- 미리보기(오른쪽) ---
        right = QVBoxLayout()
        self.lbl_preview_title = QLabel("미리보기")
        right.addWidget(self.lbl_preview_title)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 420)
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview.setStyleSheet("background:#111;")
        # ★ 픽스맵이 레이아웃을 밀지 않게 한다 — QLabel 의 sizeHint 는 픽스맵 크기라
        #   그대로 두면 '커진 그림 → 커진 라벨 → 더 큰 그림' 되먹임이 생긴다.
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Ignored)
        self.preview.installEventFilter(self)
        right.addWidget(self.preview, 1)
        # 쪽 이동(§4.2.3) — 이동 단위는 발표 화면과 같다(좌우 2쪽이면 펼침 단위, 숨김은 건너뜀)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.btn_prev = QPushButton("◀ 이전")
        self.btn_next = QPushButton("다음 ▶")
        self.btn_prev.setAutoDefault(False)
        self.btn_next.setAutoDefault(False)
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next.clicked.connect(lambda: self._step(+1))
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addStretch(1)
        right.addLayout(nav)
        wrap = QWidget()
        wrap.setLayout(right)
        root.addWidget(wrap, 1)

        for sp in (self.sp_gt, self.sp_gb, self.sp_gl, self.sp_gr,
                   self.sp_ol, self.sp_or, self.sp_el, self.sp_er,
                   self.sp_pt, self.sp_pb, self.sp_pl, self.sp_pr):
            sp.valueChanged.connect(self._update_preview)
        self.chk_oe.toggled.connect(self._on_oe_toggled)
        self.chk_page.toggled.connect(self._on_page_toggled)
        self._on_oe_toggled(self.chk_oe.isChecked(), seed=False)
        self._sync_page_group()

        self.resize(760, 620)
        self._sync_nav()
        self._update_preview()

    # --- 위젯 ---
    def _spin(self, val):
        s = QSpinBox()
        s.setRange(0, CROP_MAX)
        s.setSuffix(" %")
        s.setValue(int(max(0, min(CROP_MAX, int(round(float(val or 0)))))))
        return s

    def _on_oe_toggled(self, on, seed=True):
        """260905(§4.2.3.2): 사용자가 켜는 순간 네 칸을 **전역 좌·우로 채운다**.

        단 **모두 0 일 때만** 채운다 — 저장해 둔 홀짝 값을 체크를 껐다 켰다는 이유로 잃으면 안 된다."""
        on = bool(on)
        oe = (self.sp_ol, self.sp_or, self.sp_el, self.sp_er)
        if on and seed and not any(sp.value() for sp in oe):
            gl, gr = self.sp_gl.value(), self.sp_gr.value()
            for sp, v in zip(oe, (gl, gr, gl, gr)):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
        for sp in oe:
            sp.setEnabled(on)
        # 홀짝을 켜면 전역 좌·우는 쓰이지 않는다 — 값이 무시되는 것을 눈으로 알린다.
        for sp in (self.sp_gl, self.sp_gr):
            sp.setEnabled(not on)
        self._update_preview()

    # --- 개별 쪽 크롭(§4.2.3.1) ---
    def _live_page_crop(self):
        return (self.sp_pt.value(), self.sp_pb.value(),
                self.sp_pl.value(), self.sp_pr.value())

    def _on_page_toggled(self, on):
        if on:
            self._page_clears.discard(self._cur)
        else:
            # 끄면 그 쪽의 개별 크롭을 지운다(고정분도 함께 취소)
            self._page_overrides.pop(self._cur, None)
            self._page_clears.add(self._cur)
        self._sync_page_group()
        self._update_preview()

    def _on_apply_page(self):
        """지금 보고 있는 쪽에 현재 값을 **고정**한다 — 쪽을 옮겨도 유지된다."""
        if not self.chk_page.isChecked():
            return
        self._page_overrides[int(self._cur)] = self._live_page_crop()
        self._page_clears.discard(int(self._cur))
        self._sync_page_group()
        self._update_preview()

    def _sync_page_group(self):
        on = self.chk_page.isChecked()
        self.btn_apply_page.setVisible(on)
        self.grp_page.setTitle(f"크롭 — 개별 쪽 (p.{int(self._cur) + 1})")
        pinned = sorted(self._page_overrides)
        self.lbl_pinned.setText(
            ("개별 적용된 쪽: " + ", ".join(str(p + 1) for p in pinned)) if pinned else "")

    def _load_page_crop_for(self, page0):
        """쪽을 옮겼을 때 그 쪽의 개별 크롭을 불러온다.

        고정분 ▶ 저장된 값 순으로 찾고, 둘 다 없으면 **체크와 값을 그대로 둔다**
        (같은 값을 여러 쪽에 연속으로 '적용' 하는 흐름을 끊지 않기 위해)."""
        page0 = int(page0)
        vals = self._page_overrides.get(page0)
        if vals is None and page0 not in self._page_clears and self._page_crop_of:
            try:
                got = self._page_crop_of(page0)
            except Exception:
                got = None
            if got is not None:
                vals = _crop4(got)
        if vals is None:
            return
        for sp, v in zip((self.sp_pt, self.sp_pb, self.sp_pl, self.sp_pr), vals):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
        if not self.chk_page.isChecked():
            self.chk_page.blockSignals(True)
            self.chk_page.setChecked(True)
            self.chk_page.blockSignals(False)

    def _on_reset(self):
        self._reset = True
        self.accept()

    # --- 쪽 이동(§4.2.3) ---
    def _step(self, direction):
        if self._step_fn is None:
            return
        try:
            nxt = self._step_fn(self._cur, direction)
        except Exception:
            nxt = None
        if nxt is None:
            return
        self._cur = int(nxt)
        self._preview_pages = self._spread_of(self._cur)
        self._autofit_left = max(self._autofit_left, 1)   # 비율이 바뀌면 폭을 다시 맞춘다
        self._load_page_crop_for(self._cur)               # §4.2.3.1
        self._sync_page_group()
        self._sync_nav()
        self._update_preview()

    def _spread_of(self, page0):
        if self._pages_for is None:
            return [int(page0)]
        try:
            return list(self._pages_for(int(page0)))
        except Exception:
            return [int(page0)]

    def _sync_nav(self):
        has = self._step_fn is not None
        self.btn_prev.setEnabled(has and self._step_fn(self._cur, -1) is not None)
        self.btn_next.setEnabled(has and self._step_fn(self._cur, +1) is not None)
        nums = [str(int(p) + 1) for p in self._preview_pages if p is not None]
        self.lbl_preview_title.setText(
            "미리보기 — " + ("·".join(nums) + "쪽" if nums else "표시할 쪽 없음"))

    # --- 크롭 계산(저장소 우선순위와 같아야 한다 — 발표 SOT §4.2.1) ---
    def effective_crop(self, page0):
        if page0 is None:
            return (0, 0, 0, 0)
        page0 = int(page0)
        # 편집 중인 쪽은 스핀 값이 실시간, 그 외 고정분은 저장된 값(§4.2.3.1)
        if self.chk_page.isChecked() and page0 == int(self._cur):
            return self._live_page_crop()
        if page0 in self._page_overrides:
            return self._page_overrides[page0]
        t, b = self.sp_gt.value(), self.sp_gb.value()
        if self.chk_oe.isChecked():
            if (int(page0) + 1) % 2:                 # 1-based 홀수쪽
                return (t, b, self.sp_ol.value(), self.sp_or.value())
            return (t, b, self.sp_el.value(), self.sp_er.value())
        return (t, b, self.sp_gl.value(), self.sp_gr.value())

    # --- 미리보기 ---
    def _raw_pixmap(self, page0):
        """원본(크롭 전) 픽스맵 — 쪽당 1회만 렌더해 캐시(§4.2.3)."""
        if page0 is None or self._renderer is None:
            return None
        key = int(page0)
        if key in self._raw:
            return self._raw[key]
        pm = None
        try:
            pm = self._renderer(key, 96)
            if pm is not None and not pm.isNull() and pm.width() > _RAW_TARGET_PX:
                pm = pm.scaledToWidth(_RAW_TARGET_PX,
                                      Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pm = None
        # 쪽 이동으로 무한정 쌓이지 않게 삽입 순서대로 오래된 것부터 버린다.
        while len(self._raw) >= RAW_CACHE_MAX:
            self._raw.pop(next(iter(self._raw)), None)
        self._raw[key] = pm
        return pm

    def _cropped(self, page0):
        pm = self._raw_pixmap(page0)
        if pm is None or pm.isNull():
            return None
        t, b, l, r = self.effective_crop(page0)
        W, H = pm.width(), pm.height()
        x = int(W * l / 100.0)
        y = int(H * t / 100.0)
        w = max(1, W - x - int(W * r / 100.0))
        h = max(1, H - y - int(H * b / 100.0))
        return pm.copy(min(x, W - 1), min(y, H - 1), w, h)

    def _update_preview(self, *_):
        area = self.preview.size()
        aw, ah = max(40, area.width() - 8), max(40, area.height() - 8)
        pages = self._preview_pages or [self._page0]
        pms = {}
        for pg in pages:
            if pg is not None:
                pms[int(pg)] = self._cropped(pg)
        real = [pm for pm in pms.values() if pm is not None and not pm.isNull()]
        if not real:
            self.preview.setText("미리보기를 표시할 수 없습니다.")
            return
        ref = real[0]
        gap = PREVIEW_GAP_PX if len(pages) > 1 else 0
        widths = []
        heights = []
        for pg in pages:
            pm = pms.get(int(pg)) if pg is not None else None
            pm = pm if (pm is not None and not pm.isNull()) else ref   # 빈 칸도 자리를 잡는다
            widths.append(pm.width())
            heights.append(pm.height())
        tot_w = sum(widths) + gap * (len(pages) - 1)
        tot_h = max(heights)
        scale = min(aw / max(1, tot_w), ah / max(1, tot_h))
        cw, ch = max(1, int(tot_w * scale)), max(1, int(tot_h * scale))
        canvas = QPixmap(cw, ch)
        canvas.fill(QColor("#111111"))
        p = QPainter(canvas)
        x = 0
        for i, pg in enumerate(pages):
            w = max(1, int(widths[i] * scale))
            h = max(1, int(heights[i] * scale))
            pm = pms.get(int(pg)) if pg is not None else None
            if pm is not None and not pm.isNull():
                p.drawPixmap(x, (ch - h) // 2,
                             pm.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
            x += w + gap
        p.end()
        self.preview.setPixmap(canvas)
        self._autofit_width(tot_w / max(1, tot_h), aw, ah)

    def _autofit_width(self, content_aspect, aw, ah):
        """260905(§4.2.3): 좌우 2쪽처럼 가로로 긴 내용이면 **다이얼로그를 넓혀** 위아래 여백을 줄인다.

        ⚠ 넓히면 라벨 resize → 다시 그리기 → 또 넓히기 로 되먹임하기 쉽다.
        `_autofit_busy` 가드 + 최소 이득 + 횟수 제한 세 겹으로 막는다."""
        if self._autofit_busy or self._autofit_left <= 0 or content_aspect <= 0:
            return
        need = int(content_aspect * ah)          # 높이를 꽉 채우는 데 필요한 폭
        gain = need - aw
        if gain < AUTOFIT_MIN_GAIN_PX:
            return
        try:
            avail = self.screen().availableGeometry().width()
        except Exception:
            avail = 1920
        cap = int(avail * AUTOFIT_MAX_SCREEN)
        new_w = min(cap, self.width() + gain)
        if new_w - self.width() < AUTOFIT_MIN_GAIN_PX:
            self._autofit_left = 0               # 더 넓힐 여지가 없다 — 재시도 중단
            return
        self._autofit_busy = True
        self._autofit_left -= 1
        try:
            self.resize(new_w, self.height())
        finally:
            self._autofit_busy = False

    def eventFilter(self, obj, ev):
        # 다이얼로그가 아니라 **미리보기 라벨**이 실제로 커진 시점에 다시 그린다.
        if obj is self.preview and ev.type() == QEvent.Type.Resize:
            self._update_preview()
        return super().eventFilter(obj, ev)

    # --- 결과 ---
    def result_values(self):
        """dict: reset / global(t,b,l,r) / oddeven_enabled / odd(l,r) / even(l,r) /
        page_crops({page0: (t,b,l,r)}) / page_clears([page0…]).

        `page_enabled`·`page` 는 편집 중인 쪽의 상태(호환용).
        확인 시에는 **고정분 + 편집 중인 쪽**을 함께 저장한다(§4.2.3.1)."""
        crops = dict(self._page_overrides)
        if self.chk_page.isChecked():
            crops[int(self._cur)] = self._live_page_crop()
        clears = set(self._page_clears) - set(crops)
        # 연 시점에 개별 크롭이 있었는데 이번에 저장 대상이 아니면 지운다(종전 동작)
        if self._had_page_crop and self._page0 not in crops:
            clears.add(self._page0)
        return {
            "reset": self._reset,
            "global": (self.sp_gt.value(), self.sp_gb.value(),
                       self.sp_gl.value(), self.sp_gr.value()),
            "page_crops": {int(k): tuple(v) for k, v in crops.items()},
            "page_clears": sorted(int(x) for x in clears),
            "page_enabled": self.chk_page.isChecked(),
            "page": self._live_page_crop(),
            "oddeven_enabled": self.chk_oe.isChecked(),
            "odd": (self.sp_ol.value(), self.sp_or.value()),
            "even": (self.sp_el.value(), self.sp_er.value()),
        }
