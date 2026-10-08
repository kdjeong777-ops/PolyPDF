"""사용법 다이얼로그 (v1.6.22 — 전면 현행화). 본문은 261008 부터 언어별 리소스 `resources/help/`."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextBrowser, QDialogButtonBox,
)
from viewer.i18n import tr


def usage_html() -> str:
    """사용법 본문 — `resources/help/help_<코드>.html` 을 대체 사슬 차례로 찾는다(다국어 SOT §8).
    한국어가 아닌 도움말은 숨긴 한국 전용 기능(§7)을 빼고 쓴다."""
    from viewer.i18n import resource_chain
    from viewer.resources_path import resource_path
    for code in resource_chain():
        try:
            p = resource_path("help/help_%s.html" % code)
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            continue
    return "<p>%s</p>" % tr("사용법 파일을 찾지 못했습니다.")


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("PolyPDF — 사용법"))
        self.resize(760, 680)

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(usage_html())
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)
