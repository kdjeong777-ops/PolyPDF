"""261008-18(마스터 SOT §14.5 U14): 업데이트 창 — **무엇이 바뀌는지** 버전별로 보여 주고 고르게 한다.

지금 버전 다음부터 새 버전까지 모든 버전의 릴리스 설명(`info["changes"]`, `updater.collect_changes`)을
새 버전부터 차례로 보인다. 두 곳에서 쓴다:
  - mode="manual" : 도움말 → 업데이트 확인  → `업데이트` / `나중에`
  - mode="check"  : 261026-5 도움말 → 업데이트 확인 — 창이 **먼저 뜨고** '확인 중…' 을 보이다가 결과(`show_result`)로 바뀐다.
                    새 버전이면 manual 과 같은 단추, 아니면 `닫기`. 창 아래에 `업데이트 자동 다운로드`·`베타(테스트) 버전도 받기`
                    (종전 도움말 메뉴의 체크 항목 — 리본 단추로는 체크 상태를 다룰 수 없어 옮겼다, 마스터 §14.5 U14)
  - mode="close"  : 종료할 때 새 버전이 있으면 → `업그레이드 후 종료` / `그냥 종료` / `취소`
결과는 `choice` — "update" | "later" | "quit" | "cancel".

261008-27(다국어 SOT §10.4): 릴리스 설명은 언어별 절(`<!-- lang:ko -->` …)로 온다(`scripts/release_notes.py`).
화면 언어 → 대체 사슬 순으로 절을 고르고, 없으면 한국어 절을 '한국어로만 있다' 안내와 함께 보인다.
표시가 없는 옛 설명은 통째로 한국어 절이다.
"""
from __future__ import annotations

import re

from PyQt6.QtWidgets import (QCheckBox, QDialog, QGroupBox, QVBoxLayout, QLabel, QTextBrowser, QHBoxLayout,
                             QPushButton)

from viewer.i18n import tr, trn, resource_chain

_FULL_CL = re.compile(r"\*\*Full Changelog\*\*:\s*(\S+)")
# scripts/release_notes.py 의 절 머리(언어마다) — 버전 제목 밑에 큰 제목이 반복되지 않게 뺀다
_NOTES_HEAD = re.compile(r"^#{1,6}\s*(바뀐 내용|What's changed)\s*$", re.M)
_CODE_OR_URL = re.compile(r"(`[^`\n]*`|https?://\S+)")


def escape_underscores(text: str) -> str:
    """릴리스 설명 글의 `_` 를 글자 그대로 — 마크다운이 `_review/load_<버전>_` 을 기울임으로 읽어 밑줄이 사라졌다
    (261012-5, 사용자 지시). 코드 표기(`…`)와 주소(URL) 안은 건드리지 않는다(주소가 깨진다)."""
    parts = _CODE_OR_URL.split(text or "")
    return "".join(pt if i % 2 else pt.replace("_", r"\_") for i, pt in enumerate(parts))


_LANG_MARK = re.compile(r"^<!--\s*lang:([A-Za-z_\-]+)\s*-->\s*$", re.M)
_COMPARE = re.compile(r"^\*\*(전체 비교|Full comparison)\*\*:", re.M)


def split_lang_sections(notes: str) -> dict:
    """`<!-- lang:xx -->` 로 나뉜 본문 → {코드: 절}. 표시가 없으면 {"ko": 전체}(옛 릴리스)."""
    notes = notes or ""
    marks = list(_LANG_MARK.finditer(notes))
    if not marks:
        return {"ko": notes}
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(notes)
        out[m.group(1).lower()] = notes[m.end():end].strip()
    return out


def pick_notes(notes: str, chain=None):
    """화면 언어의 절 → (본문, 한국어로 물러났는가)."""
    secs = split_lang_sections(notes)
    chain = list(chain or resource_chain())
    for code in chain:
        if secs.get(code):
            return secs[code], (code == "ko" and chain[0] != "ko")
    body = secs.get("ko") or next(iter(secs.values()), "")
    return body, chain[:1] != ["ko"]


def changes_markdown(changes: list, chain=None) -> str:
    """버전별 설명을 하나의 Markdown 으로. 설명이 없거나 링크뿐이면 릴리스 페이지를 안내한다."""
    parts = []
    for c in changes or []:
        head = "### v%s" % c.get("version", "")
        if c.get("pre"):
            head += tr(" · 베타(테스트)")
        if c.get("date"):
            head += " — %s" % c["date"]
        body, ko_only = pick_notes(c.get("notes") or "", chain)
        body = _FULL_CL.sub(lambda m: "**%s**: %s" % (tr("전체 비교"), m.group(1)), body.strip())
        body = _NOTES_HEAD.sub("", body).strip()
        body = escape_underscores(body)
        only_link = (not body) or all(
            (not ln.strip()) or _COMPARE.match(ln.strip()) for ln in body.splitlines())
        if only_link:
            url = c.get("url") or ""
            link = ("  [%s](%s)" % (tr("릴리스 페이지"), url)) if url else ""
            body = "_%s_%s" % (tr("이 버전에는 자세한 설명이 없습니다."), link) + ("\n\n" + body if body else "")
        elif ko_only:
            body = "_%s_\n\n%s" % (tr("(이 버전의 설명은 한국어로만 있습니다)"), body)
        parts.append(head + "\n\n" + body)
    if not parts:
        return "_%s_" % tr("바뀐 내용을 가져오지 못했습니다.")
    return "\n\n---\n\n".join(parts)


class UpdateDialog(QDialog):
    def __init__(self, info, current: str, mode: str = "manual", parent=None, options=None):
        """options(261026-5): {"auto_download": bool, "beta": bool, "beta_locked": bool, "on_auto_download": fn, "on_beta": fn}
        — 주면 창 아래에 두 체크를 둔다(mode manual·check). 바꾸면 곧바로 그 함수를 부른다(저장은 부른 쪽)."""
        super().__init__(parent)
        self.mode = mode
        self.choice = "cancel" if mode == "close" else "later"
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        lay.addWidget(self.notes, 1)
        self.how = QLabel()
        self.how.setWordWrap(True)
        lay.addWidget(self.how)

        self.chk_auto_download = self.chk_beta = None
        if options is not None and mode != "close":
            grp = QGroupBox(tr("업데이트 설정"))
            gv = QVBoxLayout(grp)
            self.chk_auto_download = QCheckBox(tr("업데이트 자동 다운로드"))
            self.chk_auto_download.setToolTip(tr("시작할 때 새 버전이 있으면 미리 받아 둡니다(설치는 종료할 때 묻습니다)."))
            self.chk_auto_download.setChecked(bool(options.get("auto_download", True)))
            self.chk_beta = QCheckBox(tr("베타(테스트) 버전도 받기"))
            self.chk_beta.setChecked(bool(options.get("beta", False)))
            if options.get("beta_locked"):
                self.chk_beta.setEnabled(False)
                self.chk_beta.setToolTip(tr("1.0 이전에는 항상 베타(테스트) 버전을 받습니다."))
            if options.get("on_auto_download"):
                self.chk_auto_download.toggled.connect(options["on_auto_download"])
            if options.get("on_beta"):
                self.chk_beta.toggled.connect(options["on_beta"])
            gv.addWidget(self.chk_auto_download)
            gv.addWidget(self.chk_beta)
            lay.addWidget(grp)

        self._btn_row = QHBoxLayout()
        lay.addLayout(self._btn_row)
        if mode == "check" and not info:
            self._show_checking()
        else:
            self.show_result(info, current)

    def _set_buttons(self, btns) -> None:
        while self._btn_row.count():
            it = self._btn_row.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._btn_row.addStretch(1)
        for text, key, default in btns:
            b = QPushButton(text)
            b.setDefault(default)
            b.setAutoDefault(default)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self._btn_row.addWidget(b)

    def _show_checking(self) -> None:
        self.setWindowTitle(tr("업데이트"))
        self.head.setText(tr("<b>업데이트를 확인하는 중…</b>"))
        self.notes.setVisible(False)
        self.how.setVisible(False)
        self._set_buttons(((tr("닫기"), "later", True),))

    def show_message(self, text: str) -> None:
        """261026-5 새 버전이 없거나 확인하지 못했을 때 — 그 한 줄과 `닫기`."""
        self.setWindowTitle(tr("업데이트"))
        self.head.setText(text)
        self.notes.setVisible(False)
        self.how.setVisible(False)
        self._set_buttons(((tr("닫기"), "later", True),))

    def show_result(self, info, current: str) -> None:
        """새 버전 정보 — 바뀐 내용·설치 안내·단추."""
        info = info or {}
        latest = info.get("version", "")
        changes = list(info.get("changes") or [])
        is_beta = any(c.get("pre") for c in changes[:1]) or "-" in str(info.get("tag", ""))
        self.setWindowTitle(tr("베타 업데이트") if is_beta else tr("업데이트"))
        n = len(changes)
        # 문장을 조각으로 잇지 않는다(다국어 SOT §6) — 베타/정식 문장을 따로 둔다
        title = (tr("<b>새 베타(테스트) 버전이 있습니다.</b>") if is_beta
                 else tr("<b>새 버전이 있습니다.</b>"))
        line = tr("현재 v{cur} → 새 v{new}").format(cur=current, new=latest)
        if n > 1:
            line += "  " + trn("({n}개 버전)", n).format(n=n)
        self.head.setText(title + "<br>" + line)
        self.notes.setMarkdown(changes_markdown(changes))
        self.notes.setVisible(True)
        self.how.setText(tr("업데이트 파일을 <b>먼저 받은 뒤</b>, 열린 PolyPDF 창을 모두 닫고 설치합니다.")
                         + ("<br>" + tr("이 버전은 테스트(베타)입니다.") if is_beta else ""))
        self.how.setVisible(True)
        if self.mode == "close":
            self._set_buttons(((tr("업그레이드 후 종료"), "update", True), (tr("그냥 종료"), "quit", False),
                               (tr("취소"), "cancel", False)))
        else:
            self._set_buttons(((tr("업데이트"), "update", True), (tr("나중에"), "later", False)))

    def _pick(self, key: str):
        self.choice = key
        self.accept() if key == "update" else self.reject()
