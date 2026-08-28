"""260628: 다단(N-up) 프리셋 UI 공통 믹스인 — 인쇄·이미지→PDF·병합 공통.

배경(감사 260628): `_reload_presets`/`_on_preset_pick`/`_open_nup` 세 메서드가
`print_dialog.py` 와 `image_to_pdf_dialog.py` 에 **바이트 단위로 동일하게** 복붙돼
있었고 `merge_dialog.py` 에 경량 변형이 하나 더 있었다. 한쪽만 고치면 다이얼로그마다
다단 동작이 갈라진다.

사용법 — 다이얼로그가 아래 속성만 준비하면 된다(마스터 SOT §11.10):
    self.cmb_preset   : QComboBox   (프리셋 선택)
    self.chk_nup      : QCheckBox   (다단 사용)
    self.btn_nup      : QPushButton (설정… — 선택)
    self._nup_settings: dict        (현재 다단 설정)
    self._preset_api  : dict|None   ({'get_presets': callable, ...})
    self._sample      : any         (미리보기 샘플 — TwoUpSettingsDialog 로 전달)

    class MyDialog(NupPresetMixin, QDialog): ...

레이아웃 엔진 자체는 `viewer/twoup.py` + `widgets/twoup_dialog.TwoUpSettingsDialog`
하나만 쓴다(인쇄·병합·이미지→PDF 결과가 일치해야 함).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog

__all__ = ["NupPresetMixin"]


class NupPresetMixin:
    """다단 프리셋 콤보 + '설정' 버튼 동작 공통 구현."""

    def _reload_presets(self):
        """프리셋 콤보 재구성. preset_api 가 없으면 콤보를 비활성화."""
        self.cmb_preset.clear()
        self.cmb_preset.addItem("(기본 설정)", None)
        try:
            for p in ((self._preset_api or {}).get("get_presets", lambda: [])() or []):
                self.cmb_preset.addItem(p.get("name", "(이름없음)"), p)
        except Exception:
            pass
        if not self._preset_api:
            self.cmb_preset.setEnabled(False)

    def _on_preset_pick(self, *_):
        """프리셋 선택 시 설정 반영 + 다단 자동 체크."""
        p = self.cmb_preset.currentData()
        if isinstance(p, dict):
            self._nup_settings = dict(p)
            self.chk_nup.setChecked(True)

    def _on_nup_toggle(self, on):
        """'다단' 체크 상태에 따라 '설정' 버튼 활성화."""
        try:
            self.btn_nup.setEnabled(bool(on))
        except Exception:
            pass

    def _open_nup(self):
        """다단 설정 다이얼로그 → 결과 반영 + (저장된 프리셋이면) 콤보 선택 동기화."""
        from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
        dlg = TwoUpSettingsDialog(self._nup_settings, self,
                                  preset_api=self._preset_api, sample=self._sample)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._nup_settings = dlg.get_settings()
        cur = dlg.current_preset_name() if hasattr(dlg, "current_preset_name") else ""
        self._reload_presets()
        if cur:
            i = self.cmb_preset.findText(cur)
            if i >= 0:
                self.cmb_preset.setCurrentIndex(i)
                self.chk_nup.setChecked(True)

    def nup_enabled(self) -> bool:
        return self.chk_nup.isChecked()
