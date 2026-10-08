"""261008-18(마스터 SOT §14.5 U14): 업데이트 창 — **무엇이 바뀌는지** 버전별로 보여 주고 고르게 한다.

지금 버전 다음부터 새 버전까지 모든 버전의 릴리스 설명(`info["changes"]`, `updater.collect_changes`)을
새 버전부터 차례로 보인다. 두 곳에서 쓴다:
  - mode="manual" : 도움말 → 업데이트 확인  → `업데이트` / `나중에`
  - mode="close"  : 종료할 때 새 버전이 있으면 → `업그레이드 후 종료` / `그냥 종료` / `취소`
결과는 `choice` — "update" | "later" | "quit" | "cancel".

261008-27(다국어 SOT §10.4): 릴리스 설명은 언어별 절(`<!-- lang:ko -->` …)로 온다(`scripts/release_notes.py`).
화면 언어 → 대체 사슬 순으로 절을 고르고, 없으면 한국어 절을 '한국어로만 있다' 안내와 함께 보인다.
표시가 없는 옛 설명은 통째로 한국어 절이다.
"""
from __future__ import annotations

import re

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTextBrowser, QHBoxLayout,
                             QPushButton)

from viewer.i18n import tr, trn, resource_chain

_FULL_CL = re.compile(r"\*\*Full Changelog\*\*:\s*(\S+)")
# scripts/release_notes.py 의 절 머리(언어마다) — 버전 제목 밑에 큰 제목이 반복되지 않게 뺀다
_NOTES_HEAD = re.compile(r"^#{1,6}\s*(바뀐 내용|What's changed)\s*$", re.M)
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
    def __init__(self, info: dict, current: str, mode: str = "manual", parent=None):
        super().__init__(parent)
        self.choice = "cancel" if mode == "close" else "later"
        info = info or {}
        latest = info.get("version", "")
        changes = list(info.get("changes") or [])
        is_beta = any(c.get("pre") for c in changes[:1]) or "-" in str(info.get("tag", ""))
        self.setWindowTitle(tr("베타 업데이트") if is_beta else tr("업데이트"))
        self.resize(640, 520)
        lay = QVBoxLayout(self)

        n = len(changes)
        # 문장을 조각으로 잇지 않는다(다국어 SOT §6) — 베타/정식 문장을 따로 둔다
        title = (tr("<b>새 베타(테스트) 버전이 있습니다.</b>") if is_beta
                 else tr("<b>새 버전이 있습니다.</b>"))
        line = tr("현재 v{cur} → 새 v{new}").format(cur=current, new=latest)
        if n > 1:
            line += "  " + trn("({n}개 버전)", n).format(n=n)
        head = QLabel(title + "<br>" + line)
        head.setWordWrap(True)
        lay.addWidget(head)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(changes_markdown(changes))
        lay.addWidget(self.notes, 1)

        how = QLabel(tr("업데이트 파일을 <b>먼저 받은 뒤</b>, 열린 PolyPDF 창을 모두 닫고 설치합니다.")
                     + ("<br>" + tr("이 버전은 테스트(베타)입니다.") if is_beta else ""))
        how.setWordWrap(True)
        lay.addWidget(how)

        row = QHBoxLayout()
        row.addStretch(1)
        if mode == "close":
            btns = ((tr("업그레이드 후 종료"), "update", True), (tr("그냥 종료"), "quit", False),
                    (tr("취소"), "cancel", False))
        else:
            btns = ((tr("업데이트"), "update", True), (tr("나중에"), "later", False))
        for text, key, default in btns:
            b = QPushButton(text)
            b.setDefault(default)
            b.setAutoDefault(default)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
        lay.addLayout(row)

    def _pick(self, key: str):
        self.choice = key
        self.accept() if key == "update" else self.reject()
