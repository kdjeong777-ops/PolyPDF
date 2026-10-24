# -*- coding: utf-8 -*-
"""261021-1(사용자 지시, 응답성 SOT §4.7): 가벼운 넘김 — 앱 쪽.

판정은 `viewer.perf_mode` 한 곳이 한다. 여기서는
  - 상태 표시줄 오른쪽에 **'가벼운 넘김'** 표시(켜진 동안만, 누르면 까닭) — 처음 켜질 때 한 번 상태 표시줄로 알린다
  - 쪽이 바뀌면 텍스트 창·단어장은 **넘김이 멈춘 뒤 한 번**(`LITE_FOLLOW_MS`) 따라가게 한다
  - 무거운 작업(OCR·단어장 생성·책갈피 생성·번역·변환)을 시작할 때 '오래 걸릴 수 있다' 고 알린다
    (작업마다 이 실행 동안 한 번) — 창을 막지 않는다(사용자 결정 261021-1 '상태 표시줄 안내').
    폴더 색인은 넣지 않는다 — 자식 프로세스라 화면을 붙들지 않고, 진행 문구가 상태 표시줄을 곧바로 덮는다.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel

from viewer import perf_mode
from viewer.i18n import tr


class LiteMixin:
    LITE_FOLLOW_MS = 300          # 넘김이 이만큼 멈추면 텍스트 창·단어장이 따라간다
    LITE_NOTICE_MS = 10000        # 상태 표시줄 알림을 보여 두는 시간

    def _lite_init(self):
        self._lite_heavy_told = set()
        self._lite_follow = QTimer(self)
        self._lite_follow.setSingleShot(True)
        self._lite_follow.setInterval(self.LITE_FOLLOW_MS)
        self._lite_follow.timeout.connect(self._lite_follow_fire)
        self.lite_badge = QLabel()
        self.lite_badge.setObjectName("liteBadge")
        self.lite_badge.setVisible(False)
        try:
            self.status.addPermanentWidget(self.lite_badge)
        except Exception:
            pass
        perf_mode.on_engaged(self._lite_engaged)

    def _lite_reason_text(self, r: str) -> str:
        return {
            "on": tr("환경설정에서 '가벼운 넘김' 을 항상 켜 두었습니다."),
            "efficiency": tr("Windows 전원 모드가 '최고의 전력 효율' 입니다."),
            "saver": tr("Windows 배터리 절약 모드가 켜져 있습니다."),
            "slow": tr("이 컴퓨터에서 쪽 넘김이 느립니다."),
        }.get(r, "")

    def _lite_refresh(self) -> bool:
        """지금 가벼운 넘김인가 — 표시도 맞춘다(값싼 호출: 전원 상태는 `perf_mode` 가 30초마다만 묻는다)."""
        r = perf_mode.reason()
        on = perf_mode.is_lite()
        try:
            self.lite_badge.setVisible(on)
            if on:
                self.lite_badge.setText(tr("🔋 가벼운 넘김"))
                self.lite_badge.setToolTip(
                    self._lite_reason_text(r) + "\n" +
                    tr("쪽이 부드럽게 넘어가도록 넘김 애니메이션을 끄고, 잇달아 넘기면 가운데 쪽은 건너뛰며, "
                       "텍스트 창은 넘김이 멈춘 뒤 따라갑니다. 환경설정의 '세부 줄 (메뉴 탭 아래 한 줄)' 묶음에서 바꿀 수 있습니다."))
        except Exception:
            pass
        return on

    def _lite_engaged(self, r: str) -> None:
        """처음 켜질 때 한 번 — 왜 켜졌고 무엇이 달라지는지."""
        try:
            self._lite_refresh()
            self.status.showMessage(
                tr("{why} 쪽이 부드럽게 넘어가도록 '가벼운 넘김' 으로 바꿨습니다 — 환경설정의 '세부 줄 (메뉴 탭 아래 한 줄)' 묶음에서 바꿀 수 있습니다.")
                .format(why=self._lite_reason_text(r)), self.LITE_NOTICE_MS)
        except Exception:
            pass

    def _lite_follow_fire(self) -> None:
        mv = getattr(self, "main_view", None)
        if mv is None or mv._doc is None:
            return
        page = mv.current_page()
        try:
            self._on_main_page_changed(page)
            self._on_study_page_changed(page)
        except Exception:
            pass

    def _lite_heavy_notice(self, what: str) -> None:
        """무거운 작업을 시작할 때 — 느린 상태면 '오래 걸릴 수 있다' 고 한 번 알린다(작업마다 이 실행 동안 한 번).

        작업 자체의 상태 표시줄 문구가 바로 뒤에 덮어쓰지 않도록 다음 차례에 띄운다."""
        r = perf_mode.reason()
        if r not in ("efficiency", "saver", "slow") or what in self._lite_heavy_told:
            return
        self._lite_heavy_told.add(what)
        msg = tr("{why} '{what}' 은(는) 평소보다 오래 걸릴 수 있습니다 — Windows 전원 모드를 '균형' 이상으로 바꾸면 빨라집니다.").format(
            why=self._lite_reason_text(r), what=what)
        QTimer.singleShot(0, lambda: self.status.showMessage(msg, self.LITE_NOTICE_MS))
