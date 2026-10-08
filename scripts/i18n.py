# -*- coding: utf-8 -*-
"""언어팩 도구 — 다국어(언어팩) SOT §3.5. Babel 은 개발·빌드 의존성만(실행 파일에 넣지 않는다).

  python scripts/i18n.py compile      모든 resources/locale/<코드>/LC_MESSAGES/polypdf.po → .mo
                                      (fuzzy·빈 번역은 빼고 — 그 문구는 대체 사슬로 보인다)
  python scripts/i18n.py clean-pseudo 가짜 언어(qps_ploc) 폴더를 지운다 — resources/ 는 통째로 빌드에
                                      실리므로 빌드 전에 부른다(SOT §3.7)

Phase 0 은 위 둘만. extract·update·init·report·pseudo·inno 는 Phase 0b(SOT §11).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALE = ROOT / "resources" / "locale"
DOMAIN = "polypdf"
PSEUDO = "qps_ploc"


def compile_all() -> int:
    from babel.messages.pofile import read_po
    from babel.messages.mofile import write_mo
    n = 0
    for po in sorted(LOCALE.glob("*/LC_MESSAGES/%s.po" % DOMAIN)):
        if po.parts[-3] == PSEUDO:
            continue
        with open(po, "rb") as f:
            cat = read_po(f, locale=po.parts[-3])
        mo = po.with_suffix(".mo")
        with open(mo, "wb") as f:
            write_mo(f, cat, use_fuzzy=False)
        done = sum(1 for m in cat if m.id and m.string and not m.fuzzy
                   and (all(m.string) if isinstance(m.string, (list, tuple)) else True))
        total = sum(1 for m in cat if m.id)
        print("compiled %s  (%d/%d)" % (mo.relative_to(ROOT), done, total))
        n += 1
    return n


def clean_pseudo() -> None:
    p = LOCALE / PSEUDO
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
        print("removed", p.relative_to(ROOT))


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "compile":
        compile_all()
        return 0
    if cmd == "clean-pseudo":
        clean_pseudo()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
