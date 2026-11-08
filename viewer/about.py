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
    ("PyMuPDF · MuPDF", "AGPL v3", "Artifex Software", ("pymupdf-lite",)),   # 261101-4: 레이아웃 엔진을 뺀 같은 판(마스터 §14.2)
    ("pdfplumber · pdfminer.six", "MIT", tr_noop("Jeremy Singer-Vine 외"), ("pdfplumber",)),
    ("pypdfium2 · PDFium", "Apache 2.0 / BSD-3-Clause", tr_noop("pypdfium2 팀 · Google"), ("pypdfium2",)),
    ("pypdf", "BSD-3-Clause", tr_noop("pypdf 기여자"), ("pypdf",)),
    ("Pillow", "MIT-CMU", tr_noop("Jeffrey A. Clark 외"), ("Pillow",)),
    ("openpyxl", "MIT", tr_noop("openpyxl 기여자"), ("openpyxl",)),
    ("python-docx", "MIT", tr_noop("Steve Canny 외"), ("python-docx",)),
    # 261014-13(형식 변환 SOT §4.1): 0.5.13 을 가져와 고쳐 넣었다(viewer/_vendor/pdf2docx — POLYPDF_PATCHES.md)
    ("pdf2docx 0.5.13", "MIT", "Artifex Software", ()),
    ("python-hwpx", "Apache 2.0", "python-hwpx Maintainers", ("python-hwpx",)),
    ("python-pptx", "MIT", "Steve Canny", ("python-pptx",)),
    ("XlsxWriter", "BSD-2-Clause", "John McNamara", ("XlsxWriter",)),
    ("Send2Trash", "BSD-3-Clause", tr_noop("Andrew Senetar 외"), ("send2trash",)),
    ("SQLite", "Public Domain", "", ()),
    ("Tesseract OCR", "Apache 2.0", tr_noop("Tesseract 기여자"), ()),
    ("pytesseract", "Apache 2.0", tr_noop("Matthias Lee 외"), ("pytesseract",)),
    ("kiwipiepy · kiwipiepy_model", "LGPL v3", "bab2min", ("kiwipiepy", "kiwipiepy_model")),
    ("wordfreq", tr_noop("Apache 2.0 (데이터 CC BY-SA 4.0)"), "Robyn Speer", ("wordfreq",)),
    ("NLTK", "Apache 2.0", "NLTK Project", ("nltk",)),
    ("WordNet", "WordNet License", "Princeton University", ()),
    (tr_noop("kengdic 한영사전"), "CC BY-SA 3.0", "kengdic contributors (garfieldnate/kengdic)", ()),
    # 261107-27(단어장 SOT §5.1): 사용자가 받아 [가져오기] 한 경우만 — 앱에 들어 있지 않다
    ("Wiktionary (kaikki.org)", "CC BY-SA 4.0", "Wiktionary contributors · wiktextract (Tatu Ylönen) · kaikki.org", ()),
    # 261105-6(태그 SOT §5.7): 사진 위치 → 행정동 — resources/geo/kr_dong.bin(단순화·압축해 넣음). CC BY 4.0 출처 표시
    (tr_noop("행정동 경계 (admdongkor ver20261001)"), "CC BY 4.0",
     tr_noop("통계청 SGIS 행정동 경계(공공누리 제1유형)를 vuski/admdongkor 가 가공 — github.com/vuski/admdongkor, PolyPDF 가 단순화"), ()),
    # 261105-17(사진 보기 SOT §4.29): 고른 사진 지도 — resources/map 의 Leaflet·markercluster 를 브라우저 페이지에 싣는다. 지도 그림은 OpenStreetMap(ODbL)
    ("Leaflet 1.9.4", "BSD-2-Clause", "Volodymyr Agafonkin", ()),
    ("Leaflet.markercluster 1.5.3", "MIT", "David Leaver", ()),
    (tr_noop("OpenStreetMap 지도 그림"), "ODbL", tr_noop("© OpenStreetMap contributors — 지도 페이지에 출처를 보인다"), ()),
    ("FFmpeg", "GPL v3", tr_noop("FFmpeg developers — 별도 실행 파일(gyan.dev 빌드)"), ()),
    ("lameenc · LAME", "LGPL", tr_noop("Chris Cooper · LAME 프로젝트"), ("lameenc",)),
    # 261108-28(영상·음성 SOT §1.10): 자연 음성 — 엔진은 앱에 들고, 모델은 구성요소로 받을 때만(앱에 들어 있지 않다)
    ("sherpa-onnx 2.0.1", "Apache 2.0", "Xiaomi Corporation · k2-fsa", ("sherpa-onnx",)),
    ("ONNX Runtime 1.28.2", "MIT", tr_noop("Microsoft — sherpa-onnx 휠에 든 onnxruntime.dll"), ()),
    (tr_noop("Supertonic 3 음성 모델 (자연 음성 구성요소)"), "OpenRAIL-M",
     tr_noop("Supertone Inc. — 받을 때만, 만든 소리는 AI 합성 음성이다. 사용 제한 조항을 따른다"), ()),
    # 261104-2(사진 보기 SOT 4.9): HEIC 읽기 — 동적 링크 DLL(libheif·libde265 LGPL v3, MinGW libstdc++ GCC 런타임 예외)
    ("pi-heif · libheif · libde265", "BSD-3-Clause / LGPL v3", "Pillow-Heif contributors · struktur AG", ("pi-heif",)),
    # 261017(가상 프린터 SOT §4.2): 가상 프린터 — 포트 모니터(원본을 고쳐 우리 이름으로 빌드)·PS→PDF 변환기
    ("MFILEMON 1.6.1", "GPL v3", tr_noop("Lorenzo Monti — 고쳐 빌드한 포트 모니터(printer/monitor_src)"), ()),
    ("Ghostscript 10.08.0", "AGPL v3", tr_noop("Artifex Software — 별도 실행 파일(가상 프린터 PS→PDF)"), ()),
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
