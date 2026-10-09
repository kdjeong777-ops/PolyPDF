# -*- coding: utf-8 -*-
"""언어팩 도구 — 다국어(언어팩) SOT §3.5. Babel 은 개발·빌드 의존성만(실행 파일에 넣지 않는다).

  python scripts/i18n.py extract        viewer/·main.py 의 tr·trp·trn·tr_noop 키 → resources/locale/polypdf.pot
  python scripts/i18n.py update         .pot 의 새 키를 모든 팩 .po 에 빈칸으로, 바뀐 원문은 비슷한 번역을 fuzzy 로,
                                        사라진 키는 #~(obsolete)로
  python scripts/i18n.py init <코드>    새 언어 팩(.po — Plural-Forms 는 CLDR 로 자동, pack.json 뼈대)
  python scripts/i18n.py compile        모든 팩 .po → .mo (fuzzy·빈 번역은 빼고 — 그 문구는 대체 사슬로 보인다)
  python scripts/i18n.py report         팩별 완성도·빈칸·fuzzy·자리표시 불일치
  python scripts/i18n.py pseudo         가짜 언어 qps_ploc 를 .pot 에서 만들고 .mo 까지(개발·검사 전용, SOT §3.7)
  python scripts/i18n.py clean-pseudo   가짜 언어 폴더를 지운다(build_ci.bat 가 빌드 전에 부른다)
  python scripts/i18n.py inno           내장 팩·번역으로 installer/languages.iss 를 만든다(build_ci.bat — SOT §10)

추출기는 우리 것(AST): `trn(text, n)` 은 인자 하나로 단·복수를 겸하고 `trp(문맥, 원문)` 은 문맥이 앞이라
Babel 기본 키워드 규칙으로는 못 뽑는다. 키는 **문자열 리터럴**이어야 한다 — 아니면 추출 경고(SOT §6).
설치 프로그램 문구는 `installer/installer_text.py` 에서 `msgctxt "installer"` 로 뽑는다.
"""
import ast
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALE = ROOT / "resources" / "locale"
DOMAIN = "polypdf"
PSEUDO = "qps_ploc"
FUNCS = {"tr": "plain", "trp": "ctx", "trn": "plural", "tr_noop": "plain"}
_PH = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


# ── 추출 ──────────────────────────────────────────────────────────────────
def _func_name(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _lit(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def extract_from(files, base: Path):
    """[(msgid, ctx|None, plural:bool, 'path:line')], [경고] — 파일 순·줄 순."""
    out, warns = [], []
    for p in files:
        try:
            tree = ast.parse(Path(p).read_text(encoding="utf-8"))
        except Exception as e:
            warns.append("%s: 파싱 실패 %s" % (p, e))
            continue
        rel = Path(p).resolve().relative_to(base.resolve()).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kind = FUNCS.get(_func_name(node) or "")
            if not kind or not node.args:
                continue
            loc = "%s:%d" % (rel, node.lineno)
            if kind == "ctx":
                if len(node.args) < 2:
                    continue
                ctx, text = _lit(node.args[0]), _lit(node.args[1])
                if ctx is None or text is None:
                    warns.append(loc + ": trp 의 문맥·원문이 문자열 리터럴이 아니다")
                    continue
                out.append((text, ctx, False, loc))
            else:
                text = _lit(node.args[0])
                if text is None:
                    # 변수(`tr(_t)`)는 허용 — 그 원문은 목록에서 tr_noop() 으로 표시해 뽑힌다(SOT §6).
                    #   f-string·이어 붙이기·.format() 결과처럼 **키가 매번 달라지는 것**만 막는다.
                    a0 = node.args[0]
                    if isinstance(a0, (ast.JoinedStr, ast.BinOp)) or (
                            isinstance(a0, ast.Call) and isinstance(a0.func, ast.Attribute)
                            and a0.func.attr == "format"):
                        warns.append(loc + ": %s 의 원문이 f-string·이어 붙이기·format 결과다(키가 달라진다, SOT §6)"
                                     % _func_name(node))
                    continue
                out.append((text, None, kind == "plural", loc))
    return out, warns


def source_files(base: Path = ROOT):
    files = [base / "main.py"] if (base / "main.py").is_file() else []
    files += sorted(p for p in (base / "viewer").rglob("*.py")
                    if "__pycache__" not in p.parts and "_vendor" not in p.parts)
    if (base / "installer" / "installer_text.py").is_file():      # 설치 프로그램 문구(SOT §10.4)
        files.append(base / "installer" / "installer_text.py")
    return files


def build_template(entries):
    from babel.messages.catalog import Catalog
    cat = Catalog(project="PolyPDF", domain=DOMAIN, charset="utf-8", copyright_holder="KDJ",
                  msgid_bugs_address="https://github.com/kdjeong777-ops/PolyPDF/issues")
    for text, ctx, plural, loc in entries:
        path, line = loc.rsplit(":", 1)
        mid = (text, text) if plural else text
        m = cat.get(text, context=ctx)
        if m is None:
            cat.add(mid, context=ctx, locations=[(path, int(line))])
        else:
            m.locations.append((path, int(line)))
            if plural and not m.pluralizable:          # 같은 원문을 단·복수로 둘 다 쓰면 복수 키로
                m.id = mid
    return cat


_VOLATILE = (b'"POT-Creation-Date:', b'"PO-Revision-Date:')


def _write_po(cat, path: Path, **kw) -> bool:
    """내용이 바뀐 경우에만 쓴다 — 머리의 생성 시각만 다른 것은 변경으로 보지 않는다
    (추출·병합을 돌릴 때마다 의미 없는 diff 가 생기지 않게). 썼으면 True."""
    import io
    from babel.messages.pofile import write_po
    buf = io.BytesIO()
    kw.setdefault("include_lineno", False)   # 261009(재검토 F3): 위치는 파일만 — 코드 몇 줄만 바뀌어도 diff 가 수천 줄 나던 것
    write_po(buf, cat, width=0, sort_by_file=False, **kw)
    new = buf.getvalue()

    def key(b):
        return b"\n".join(l for l in b.splitlines() if not l.startswith(_VOLATILE))
    if path.is_file() and key(path.read_bytes()) == key(new):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(new)
    return True


def _read_po(path: Path, locale=None):
    from babel.messages.pofile import read_po
    with open(path, "rb") as f:
        return read_po(f, locale=locale)


def extract(base: Path = ROOT, pot: Path = None):
    entries, warns = extract_from(source_files(base), base)
    cat = build_template(entries)
    pot = pot or (base / "resources" / "locale" / (DOMAIN + ".pot"))
    _write_po(cat, pot, omit_header=False)
    return cat, warns


# ── 팩 ────────────────────────────────────────────────────────────────────
def packs(locale_dir: Path = LOCALE):
    return sorted(p.parent.parent for p in locale_dir.glob("*/LC_MESSAGES/%s.po" % DOMAIN)
                  if p.parts[-3] != PSEUDO)


def update(locale_dir: Path = LOCALE, pot: Path = None):
    """모든 팩 .po 를 .pot 에 맞춘다(Babel Catalog.update — 비슷한 원문은 fuzzy 로 번역을 살린다)."""
    tmpl = _read_po(pot or locale_dir / (DOMAIN + ".pot"))
    done = []
    for d in packs(locale_dir):
        po = d / "LC_MESSAGES" / (DOMAIN + ".po")
        cat = _read_po(po, locale=d.name)
        cat.update(tmpl, no_fuzzy_matching=False, update_header_comment=False)
        _write_po(cat, po, ignore_obsolete=False, include_previous=True)
        done.append(d.name)
    return done


def init(code: str, locale_dir: Path = LOCALE, pot: Path = None):
    """새 언어: .po(Plural-Forms 는 CLDR 로) + pack.json 뼈대. 이미 있으면 건드리지 않는다."""
    from babel import Locale
    from babel.messages.catalog import Catalog
    d = locale_dir / code
    po = d / "LC_MESSAGES" / (DOMAIN + ".po")
    if po.exists():
        raise FileExistsError(po)
    tmpl = _read_po(pot or locale_dir / (DOMAIN + ".pot"))
    loc = Locale.parse(code)
    cat = Catalog(locale=loc, project="PolyPDF", domain=DOMAIN, charset="utf-8")
    cat.update(tmpl)
    _write_po(cat, po)
    meta = {"code": code, "name": loc.get_display_name(loc) or code,
            "name_ko": Locale.parse("ko").languages.get(loc.language, code),
            "fallback": [] if code == "en" else ["en"], "qt": "qtbase_" + loc.language,
            "inno": "", "direction": "rtl" if loc.character_order == "right-to-left" else "ltr",
            "status": "partial"}
    (d / "pack.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return po


def compile_all(locale_dir: Path = LOCALE, include_pseudo: bool = False, quiet: bool = False):
    from babel.messages.mofile import write_mo
    n = 0
    for po in sorted(locale_dir.glob("*/LC_MESSAGES/%s.po" % DOMAIN)):
        if po.parts[-3] == PSEUDO and not include_pseudo:
            continue
        cat = _read_po(po, locale=po.parts[-3] if po.parts[-3] != PSEUDO else None)
        with open(po.with_suffix(".mo"), "wb") as f:
            write_mo(f, cat, use_fuzzy=False)
        if not quiet:
            r = _report_cat(cat)
            print("compiled %s  (%d/%d)" % (po.relative_to(locale_dir.parent.parent) if locale_dir == LOCALE
                                            else po, r["translated"], r["total"]))
        n += 1
    return n


def _placeholders(s):
    return sorted(_PH.findall(s or ""))


def _report_cat(cat):
    total = translated = fuzzy = empty = 0
    bad = []
    for m in cat:
        if not m.id:
            continue
        total += 1
        ids = m.id if isinstance(m.id, (list, tuple)) else (m.id,)
        strs = m.string if isinstance(m.string, (list, tuple)) else (m.string,)
        if m.fuzzy:
            fuzzy += 1
        elif all(strs):
            translated += 1
        else:
            empty += 1
        want = _placeholders(ids[0])
        for s in strs:
            if s and _placeholders(s) != want:
                bad.append(ids[0])
                break
    return {"total": total, "translated": translated, "fuzzy": fuzzy, "empty": empty,
            "placeholder_mismatch": bad,
            "percent": (100.0 * translated / total) if total else 100.0}


def report(locale_dir: Path = LOCALE):
    out = {}
    for d in packs(locale_dir):
        out[d.name] = _report_cat(_read_po(d / "LC_MESSAGES" / (DOMAIN + ".po"), locale=d.name))
    return out


# ── 가짜 언어 (SOT §3.7) ──────────────────────────────────────────────────
_ACC = dict(zip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
                "àƀçđéƒĝĥîĵķĺɱñöþǫŕšŧûṽŵẋýžÀßÇĐÉƑĜĤÎĴĶĹṀÑÖÞǪŔŠŦÛṼŴẊÝŽ"))


def pseudo_text(s: str) -> str:
    """알아볼 수 있게 바꾸고 약 40% 늘린다. 자리표시 `{이름}`·단축키 `&` 는 그대로."""
    parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\}|&.)", s)
    body = "".join(p if (_PH.fullmatch(p) or (p.startswith("&") and len(p) == 2))
                   else "".join(_ACC.get(ch, ch) for ch in p) for p in parts)
    pad = "~" * max(1, int(len(s) * 0.4))
    return "[!! " + body + " " + pad + " !!]"


def pseudo(locale_dir: Path = LOCALE, pot: Path = None):
    from babel.messages.catalog import Catalog
    tmpl = _read_po(pot or locale_dir / (DOMAIN + ".pot"))
    cat = Catalog(project="PolyPDF", domain=DOMAIN, charset="utf-8")
    for m in tmpl:
        if not m.id:
            continue
        if isinstance(m.id, (list, tuple)):
            cat.add(m.id, (pseudo_text(m.id[0]), pseudo_text(m.id[1])), context=m.context)
        else:
            cat.add(m.id, pseudo_text(m.id), context=m.context)
    d = locale_dir / PSEUDO
    _write_po(cat, d / "LC_MESSAGES" / (DOMAIN + ".po"))
    (d / "pack.json").write_text(json.dumps({"code": PSEUDO, "name": "Pseudo", "fallback": [],
                                             "status": "partial"}) + "\n", encoding="utf-8")
    from babel.messages.mofile import write_mo
    with open(d / "LC_MESSAGES" / (DOMAIN + ".mo"), "wb") as f:
        write_mo(f, cat)
    return d


def clean_pseudo(locale_dir: Path = LOCALE) -> None:
    p = locale_dir / PSEUDO
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
        print("removed", p)

# ── 설치 프로그램 (SOT §10.1·§10.4, Phase 6) ─────────────────────────────
INSTALLER = ROOT / "installer"
INNO_KO = ("korean", r"compiler:Languages\Korean.isl")      # 한국어 = 원문(팩이 아니다)


def _installer_table(path: Path = None):
    """installer_text.py 의 MESSAGES·APP_LANG → {이름: {키: 원문}} (AST — 실행하지 않는다)."""
    path = path or (INSTALLER / "installer_text.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name = node.targets[0].id
            table = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(v, ast.Call) and _func_name(v) == "trp" and len(v.args) == 2:
                    table[_lit(k)] = _lit(v.args[1])
            out[name] = table
    return out


def _translator(code: str, locale_dir: Path):
    """그 언어의 installer 문맥 번역(대체 사슬 → 원문). 한국어는 원문."""
    if code == "ko":
        return lambda text: text
    chain, todo = [], [code]
    while todo:
        c = todo.pop(0)
        if c in chain or c == "ko" or not (locale_dir / c / "pack.json").is_file():
            continue
        chain.append(c)
        todo += json.loads((locale_dir / c / "pack.json").read_text(encoding="utf-8")).get("fallback") or []
    cats = [_read_po(locale_dir / c / "LC_MESSAGES" / (DOMAIN + ".po"), locale=c) for c in chain]

    def t(text):
        for cat in cats:
            m = cat.get(text, context="installer")
            if m is not None and m.string and "fuzzy" not in m.flags:
                return m.string
        return text
    return t


def _inno_value(text: str) -> str:
    """[CustomMessages] 값 — 줄바꿈은 %n, 한 줄로."""
    return text.replace("\r", "").replace("\n", "%n")


def inno(locale_dir: Path = LOCALE, out: Path = None, installer_dir: Path = None) -> Path:
    """내장 팩 메타·번역으로 installer/languages.iss 를 만든다(build_ci.bat — ISCC 전에).
    새 언어를 더할 때 .iss 를 손으로 고치지 않는다(SOT §12)."""
    installer_dir = installer_dir or INSTALLER
    out = out or (installer_dir / "languages.iss")
    table = _installer_table(installer_dir / "installer_text.py")
    msgs, app = table.get("MESSAGES", {}), table.get("APP_LANG", {})
    # 앱 언어: (코드, 자기 이름, 마법사 언어 이름, 마법사 메시지 파일)
    langs = [("ko", "한국어", INNO_KO[0], INNO_KO[1])]
    for d in packs(locale_dir):
        meta = json.loads((d / "pack.json").read_text(encoding="utf-8"))
        langs.append((d.name, meta.get("name") or d.name, d.name, meta.get("inno") or ""))
    wiz = [(c, w, f) for c, _n, w, f in langs if f]            # 마법사 번역이 있는 언어만 [Languages]
    wiz_names = {c: w for c, w, _f in wiz}
    fallback_wiz = wiz_names.get("en", INNO_KO[0])

    def guide_src(code):
        for c in (code, "en", "ko"):
            if (installer_dir / ("guide_%s.txt" % c)).is_file():
                return "guide_%s.txt" % c
        return "guide_ko.txt"

    L = ["; 자동 생성 — scripts/i18n.py inno (build_ci.bat). 손으로 고치지 않는다(다국어 SOT §10).",
         "; 원본: resources/locale/*/pack.json · .po 의 msgctxt \"installer\" · installer/installer_text.py", "",
         "[Languages]"]
    for c, w, f in wiz:
        L.append('Name: "%s"; MessagesFile: "%s"; InfoAfterFile: "%s"' % (w, f, guide_src(c)))
    L += ["", "[CustomMessages]"]
    for c, w, _f in wiz:
        t = _translator(c, locale_dir)
        for k, text in msgs.items():
            L.append("%s.%s=%s" % (w, k, _inno_value(t(text))))
    L += ["", "[Files]"]
    for c, _n, _w, _f in langs:
        name = _translator(c, locale_dir)(app["GuideFile"])
        L.append('Source: "%s"; DestDir: "{app}"; DestName: "%s"; Check: IsAppLang(\'%s\'); Flags: ignoreversion'
                 % (guide_src(c), name, c))
    L += ["", "[Icons]"]
    for c, _n, _w, _f in langs:
        t = _translator(c, locale_dir)
        L.append('Name: "{group}\\%s"; Filename: "{app}\\%s"; Check: IsAppLang(\'%s\')'
                 % (t(app["GuideIcon"]), t(app["GuideFile"]), c))
    L += ["", "; [Code] 가 쓰는 앱 언어 목록(쉼표로 나눈다 — 같은 차례)",
          '#define AppLangCodes "%s"' % ",".join(c for c, *_ in langs),
          '#define AppLangNames "%s"' % ",".join(n for _c, n, *_ in langs),
          '#define AppLangWizard "%s"' % ",".join(wiz_names.get(c, fallback_wiz) for c, *_ in langs), ""]
    text = "\n".join(L)
    old = out.read_text(encoding="utf-8-sig") if out.is_file() else None
    if old != text:
        out.write_text(text, encoding="utf-8-sig")        # BOM — ISCC 가 UTF-8 로 읽는다
    return out



# ── 명령줄 ────────────────────────────────────────────────────────────────
def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "extract":
        cat, warns = extract()
        for w in warns:
            print("경고:", w)
        print("extracted %d keys → resources/locale/%s.pot" % (sum(1 for m in cat if m.id), DOMAIN))
        return 1 if warns else 0
    if cmd == "update":
        print("updated:", ", ".join(update()) or "(팩 없음)")
        return 0
    if cmd == "init" and len(argv) > 2:
        print("created", init(argv[2]))
        return 0
    if cmd == "compile":
        compile_all()
        return 0
    if cmd == "report":
        for code, r in report().items():
            print("%-6s %5.1f%%  번역 %d / %d · fuzzy %d · 빈칸 %d · 자리표시 불일치 %d"
                  % (code, r["percent"], r["translated"], r["total"], r["fuzzy"], r["empty"],
                     len(r["placeholder_mismatch"])))
        return 0
    if cmd == "pseudo":
        print("pseudo →", pseudo())
        return 0
    if cmd == "clean-pseudo":
        clean_pseudo()
        return 0
    if cmd == "inno":
        print("inno →", inno())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
