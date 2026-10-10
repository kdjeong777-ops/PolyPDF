"""261008-17: 정보 창의 저작권·라이선스·오픈소스 고지 — 문구를 한 곳에서 갖는다(마스터 SOT §14.3).

- 저작권은 개발자에게 있고, 배포 조건은 **GNU AGPL v3** 다. PyQt6(GPL v3)·PyMuPDF(AGPL v3)를
  상용 라이선스 없이 쓰므로 'All rights reserved' 는 쓰지 않는다(사용자 결정).
- `OSS` 는 **실제 동봉 구성요소**와 같아야 한다 — 패키지 메타데이터·`ffmpeg -L` 로 확인한 값이다.
  `pip` 는 `requirements.txt` 의 패키지 이름(검사 `test_about_notice.py` 가 대조한다).
"""
from __future__ import annotations

from html import escape
from viewer.i18n import tr, tr_noop, language

COPYRIGHT_YEAR = "2026"
AUTHOR = "KDJ"
EMAIL = "kdjeong777@gmail.com"
SOURCE_URL = "https://github.com/kdjeong777-ops/PolyPDF"
LICENSE_NAME = "GNU Affero General Public License v3.0 (AGPL-3.0)"
LICENSE_URL = "https://www.gnu.org/licenses/agpl-3.0.html"

# (이름, 라이선스, 저작권자·비고, requirements.txt 패키지 이름들)
OSS = (
    ("Python", "PSF License", "Python Software Foundation", ()),
    ("Qt 6", "LGPL v3", "The Qt Company", ()),
    ("PyQt6", "GPL v3", "Riverbank Computing", ("PyQt6",)),
    ("PyMuPDF · MuPDF", "AGPL v3", "Artifex Software", ("PyMuPDF",)),
    ("pdfplumber · pdfminer.six", "MIT", tr_noop("Jeremy Singer-Vine 외"), ("pdfplumber",)),
    ("pypdfium2 · PDFium", "Apache 2.0 / BSD-3-Clause", tr_noop("pypdfium2 팀 · Google"), ("pypdfium2",)),
    ("pypdf", "BSD-3-Clause", tr_noop("pypdf 기여자"), ("pypdf",)),
    ("Pillow", "MIT-CMU", tr_noop("Jeffrey A. Clark 외"), ("Pillow",)),
    ("openpyxl", "MIT", tr_noop("openpyxl 기여자"), ("openpyxl",)),
    ("python-docx", "MIT", tr_noop("Steve Canny 외"), ("python-docx",)),
    ("Send2Trash", "BSD-3-Clause", tr_noop("Andrew Senetar 외"), ("send2trash",)),
    ("SQLite", "Public Domain", "", ()),
    ("Tesseract OCR", "Apache 2.0", tr_noop("Tesseract 기여자"), ()),
    ("pytesseract", "Apache 2.0", tr_noop("Matthias Lee 외"), ("pytesseract",)),
    ("kiwipiepy · kiwipiepy_model", "LGPL v3", "bab2min", ("kiwipiepy", "kiwipiepy_model")),
    ("wordfreq", tr_noop("Apache 2.0 (데이터 CC BY-SA 4.0)"), "Robyn Speer", ("wordfreq",)),
    ("NLTK", "Apache 2.0", "NLTK Project", ("nltk",)),
    ("WordNet", "WordNet License", "Princeton University", ()),
    (tr_noop("kengdic 한영사전"), "CC BY-SA 3.0", "kengdic contributors (garfieldnate/kengdic)", ()),
    ("FFmpeg", "GPL v3", tr_noop("FFmpeg developers — 별도 실행 파일(gyan.dev 빌드)"), ()),
    ("lameenc · LAME", "LGPL", tr_noop("Chris Cooper · LAME 프로젝트"), ("lameenc",)),
    ("pywin32", "PSF License", tr_noop("Mark Hammond 외"), ("pywin32",)),
    ("Anthropic Python SDK", "MIT", "Anthropic", ("anthropic",)),
    # 261010-21: 전자서명(보안 SOT §8)
    ("pyHanko · pyhanko-certvalidator", "MIT", "Matthias Valvekens", ("pyHanko",)),
    ("cryptography", "Apache 2.0 / BSD-3-Clause", "Python Cryptographic Authority", ("cryptography",)),
    ("asn1crypto · oscrypto", "MIT", "Will Bond", ()),
    ("fontTools", "MIT", "fontTools contributors", ()),
    ("uharfbuzz · HarfBuzz", "Apache 2.0 / MIT", "HarfBuzz contributors", ()),
    ("lxml", "BSD-3-Clause", "lxml contributors", ()),
    ("aiohttp", "Apache 2.0", "aiohttp contributors", ()),
    ("PyWinRT", "MIT", "PyWinRT contributors", ("winrt-runtime", "winrt-Windows.Foundation",
                                                "winrt-Windows.Security.Credentials",
                                                "winrt-Windows.Security.Cryptography",
                                                "winrt-Windows.Storage.Streams")),
)


def about_html(version: str) -> str:
    """정보 창 본문(HTML). 문구는 언어팩으로 번역되지만, 효력은 라이선스 원문을 따른다(다국어 SOT §6)."""
    items = "".join(
        "<li>%s — %s%s</li>" % (escape(tr(n)), escape(tr(lic)), (" (%s)" % escape(tr(who))) if who else "")
        for n, lic, who, _pip in OSS)
    note = ""
    if language() != "ko":
        note = "<p><i>%s</i></p>" % escape(tr("이 안내는 번역문이며, 효력은 라이선스 원문을 따릅니다."))
    return (
        "<h3>PolyPDF</h3>"
        "<p>%s</p>" % tr("버전 v{version}").format(version=escape(version))
        + "<p><b>Copyright © %s %s</b><br>" % (COPYRIGHT_YEAR, escape(AUTHOR))
        + tr("이 프로그램의 저작권은 개발자에게 있습니다.") + "<br>"
        + "<b>%s</b>: <a href='mailto:%s'>%s</a></p>" % (tr("이메일"), EMAIL, EMAIL)
        + "<p><b>%s</b><br>" % tr("라이선스")
        + tr("이 프로그램은 {license} 조건으로 배포됩니다. "
             "이 조건에 따라 누구나 사용·수정·재배포할 수 있으며, 수정해 배포하거나 네트워크로 "
             "제공하는 경우에도 같은 조건으로 소스코드를 공개해야 합니다.").format(
                 license="<a href='%s'>%s</a>" % (LICENSE_URL, LICENSE_NAME))
        + "<br><b>%s</b>: <a href='%s'>%s</a> %s</p>" % (
            tr("소스코드"), SOURCE_URL, SOURCE_URL, tr("(이메일로 요청하셔도 보내드립니다)"))
        + "<p><b>%s</b><br>" % tr("보증의 부인")
        + tr("이 프로그램은 '있는 그대로' 제공되며, 관련 법률이 허용하는 범위에서 상품성이나 특정 "
             "목적에의 적합성을 포함한 어떠한 명시적·묵시적 보증도 하지 않습니다. 프로그램 사용으로 "
             "생긴 손해에 대해 저작권자는 책임지지 않습니다(AGPL v3 제15·16조).") + "</p>"
        + note
        + "<hr><p><b>%s</b><br>" % tr("오픈소스 고지")
        + tr("이 프로그램은 다음 오픈소스 구성요소를 사용하며, 각 구성요소의 저작권은 해당 저작권자에게 "
             "있고 각자의 라이선스를 따릅니다:") + "</p>"
        + "<ul>%s</ul>" % items
        + "<p>%s</p>" % tr("각 구성요소의 라이선스 전문은 해당 프로젝트 배포물을 참조하십시오.")
    )


def show_about(parent, version: str):
    """정보 창 — 고지가 길어(약 1,400px) 메시지 상자로는 작은 화면에서 아래가 잘린다 → 스크롤되는 창."""
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QDialogButtonBox
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("PolyPDF — 정보"))
    dlg.resize(620, 640)
    lay = QVBoxLayout(dlg)
    view = QTextBrowser(dlg)
    view.setObjectName("aboutText")
    view.setOpenExternalLinks(True)
    view.setHtml(about_html(version))
    lay.addWidget(view, 1)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dlg)
    bb.accepted.connect(dlg.accept)
    lay.addWidget(bb)
    dlg.exec()
    return dlg


def required_packages() -> set:
    """고지 목록이 다루는 requirements.txt 패키지 이름(소문자) — 검사용."""
    return {p.lower() for *_x, pips in OSS for p in pips}
