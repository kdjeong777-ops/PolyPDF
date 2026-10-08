"""261008-18(마스터 SOT §14.5 U14): 업데이트 창 — **무엇이 바뀌는지** 버전별로 보여 주고 고르게 한다.

지금 버전 다음부터 새 버전까지 모든 버전의 릴리스 설명(`info["changes"]`, `updater.collect_changes`)을
새 버전부터 차례로 보인다. 두 곳에서 쓴다:
  - mode="manual" : 도움말 → 업데이트 확인  → `업데이트` / `나중에`
  - mode="close"  : 종료할 때 새 버전이 있으면 → `업그레이드 후 종료` / `그냥 종료` / `취소`
결과는 `choice` — "update" | "later" | "quit" | "cancel".
"""
from __future__ import annotations

import re

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTextBrowser, QHBoxLayout,
                             QPushButton)

_FULL_CL = re.compile(r"\*\*Full Changelog\*\*:\s*(\S+)")
_NOTES_HEAD = re.compile(r"^#{1,6}\s*바뀐 내용\s*$", re.M)   # scripts/release_notes.py 의 머리


def changes_markdown(changes: list) -> str:
    """버전별 설명을 하나의 Markdown 으로. 설명이 없거나 링크뿐이면 릴리스 페이지를 안내한다."""
    parts = []
    for c in changes or []:
        head = "### v%s" % c.get("version", "")
        if c.get("pre"):
            head += " · 베타(테스트)"
        if c.get("date"):
            head += " — %s" % c["date"]
        body = (c.get("notes") or "").strip()
        body = _FULL_CL.sub(r"**전체 비교**: \1", body)
        body = _NOTES_HEAD.sub("", body).strip()      # 버전 제목 밑에 '## 바뀐 내용' 큰 제목이 반복되지 않게
        only_link = (not body) or all(
            (not ln.strip()) or ln.strip().startswith("**전체 비교**") for ln in body.splitlines())
        if only_link:
            url = c.get("url") or ""
            body = ("_이 버전에는 자세한 설명이 없습니다._" + ("  [릴리스 페이지](%s)" % url if url else "")
                    + ("\n\n" + body if body else ""))
        parts.append(head + "\n\n" + body)
    if not parts:
        return "_바뀐 내용을 가져오지 못했습니다._"
    return "\n\n---\n\n".join(parts)


class UpdateDialog(QDialog):
    def __init__(self, info: dict, current: str, mode: str = "manual", parent=None):
        super().__init__(parent)
        self.choice = "cancel" if mode == "close" else "later"
        info = info or {}
        latest = info.get("version", "")
        changes = list(info.get("changes") or [])
        is_beta = any(c.get("pre") for c in changes[:1]) or "-" in str(info.get("tag", ""))
        self.setWindowTitle("베타 업데이트" if is_beta else "업데이트")
        self.resize(640, 520)
        lay = QVBoxLayout(self)

        n = len(changes)
        head = QLabel("<b>새 %s이 있습니다.</b><br>현재 v%s → 새 v%s%s" % (
            "베타(테스트) 버전" if is_beta else "버전", current, latest,
            ("  (%d개 버전)" % n) if n > 1 else ""))
        head.setWordWrap(True)
        lay.addWidget(head)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(changes_markdown(changes))
        lay.addWidget(self.notes, 1)

        how = QLabel("업데이트 파일을 <b>먼저 받은 뒤</b>, 열린 PolyPDF 창을 모두 닫고 설치합니다."
                     + ("<br>이 버전은 테스트(베타)입니다." if is_beta else ""))
        how.setWordWrap(True)
        lay.addWidget(how)

        row = QHBoxLayout()
        row.addStretch(1)
        if mode == "close":
            btns = (("업그레이드 후 종료", "update", True), ("그냥 종료", "quit", False),
                    ("취소", "cancel", False))
        else:
            btns = (("업데이트", "update", True), ("나중에", "later", False))
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
