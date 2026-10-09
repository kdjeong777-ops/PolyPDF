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

  작업 세션 자동 번역(SOT §12.3) — 화면 문구를 고친 세션이 번역까지 넣는다:
  python scripts/i18n.py sync           extract + update, 번역 빈칸·fuzzy 수
  python scripts/i18n.py todo [--lang en] [--json 파일]   번역할 항목(JSON — 원문·문맥·나온 파일·fuzzy 면 이전 번역)
  python scripts/i18n.py fill <파일>    todo 항목에 "str" 을 채운 JSON 을 검사(자리표시·한글·& 수)하고 넣은 뒤 compile
  python scripts/i18n.py hook-stop      Claude Code Stop 훅 — 빈칸이 남으면 턴 끝내기를 막고 할 일을 알린다

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
        cat = read_po(f, locale=locale)
    _fix_previous(cat)
    return cat


def _fix_previous(cat) -> None:
    """261009-10: Babel(2.18) read_po 는 `#| msgid "…"`(fuzzy 의 이전 원문)를 previous_id 가 아니라 **일반 주석**
    `| msgid "…"` 으로 읽는다 — 다시 쓰면 `# | msgid` 로 쌓이고(저장소에 337줄), fuzzy 항목은 이전 원문을 잃는다.
    읽은 직후 바로잡는다: fuzzy 면 previous_id 로 옮기고, 확정 항목이면 지운다(낡은 정보)."""
    from babel.messages.pofile import unescape
    for m in list(cat) + list(cat.obsolete.values()):
        prev, cur, keep = [], None, []
        for c in m.user_comments:
            s = c.strip()
            if s.startswith("| msgid ") or s.startswith("| msgid_plural ") or s.startswith("| msgctxt "):
                kind, _sp, q = s[2:].partition(" ")
                cur = kind
                if kind == "msgid":
                    prev.append(unescape(q))
            elif s.startswith('| "') and cur:
                if cur == "msgid" and prev:
                    prev[-1] += unescape(s[2:])
            else:
                cur = None
                keep.append(c)
        if len(keep) != len(m.user_comments):
            m.user_comments = keep
            if m.fuzzy and prev and not m.previous_id:
                m.previous_id = prev[:1]


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
        # 261009-10: 같은 원문이 사라졌다 되돌아오면(고쳤다가 되돌림) Babel 은 비슷한 다른 키에서 fuzzy 로 채운다 —
        #   번역 그대로인데도 '검토 필요' 가 되어 Stop 훅이 막는다. 병합 전의 확정 번역(지난 obsolete 포함)이 있으면 그것으로.
        #   fuzzy 로 옮겨진 항목은 원래 키(previous_id)의 번역을 그대로 들고 있다 — Babel 이 옛 항목을 obsolete 에
        #   남기지 않고 가져가 버리므로, 그 번역도 원래 키의 확정 번역으로 본다(확정 번역이 있으면 그쪽이 먼저).
        known, carried = {}, {}
        for m in list(cat) + list(cat.obsolete.values()):
            strs = m.string if isinstance(m.string, (list, tuple)) else (m.string,)
            if not m.id or not all(strs):
                continue
            if not m.fuzzy:
                known[(_mid(m), m.context)] = m.string
            elif m.previous_id:
                carried.setdefault((m.previous_id[0], m.context), m.string)
        for k, v in carried.items():
            known.setdefault(k, v)
        cat.update(tmpl, no_fuzzy_matching=False, update_header_comment=False)
        for m in cat:
            if m.id and m.fuzzy and (_mid(m), m.context) in known:
                m.string = known[(_mid(m), m.context)]
                m.flags.discard("fuzzy")
                m.previous_id = []
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



# ── 번역 할 일·채우기 — 작업 세션 자동 번역 (SOT §12.3, 261009-10) ─────────────
# 화면 문구를 바꾼 세션이 그 자리에서 번역까지 넣는다: `sync`(추출·병합) → `todo`(빈칸·fuzzy 목록) →
# 세션이 용어표(SOT §12.2)대로 번역 → `fill`(검사하고 넣기 + compile). Claude Code Stop 훅(`hook-stop`)이
# 빈칸이 남은 채 턴을 끝내지 못하게 한다. API·비밀값은 쓰지 않는다.

# 번역문에 한글이 남아도 되는 경우(test_i18n_packs F 와 같은 규칙 — 여기 한 곳):
#   ① 언어를 바꾼 직후 읽히도록 일부러 두 언어로 쓴 안내(원문에 영어가 함께 있다)
#   ② 원문에 든 정규식 예시 '제1장' ③ 실제 파일 이름 접미 `_번역`(한국 전용 번역 기능의 산출물)
BILINGUAL = ("The display language will be applied", "/ Restart now", "/ Later", "/ Language")
_HANGUL = re.compile(r"[가-힣]")
_ENTITY = re.compile(r"&(?:[A-Za-z]+|#\d+);")


def hangul_leak(mid: str, s: str) -> bool:
    if any(k in mid for k in BILINGUAL):
        return False
    return bool(_HANGUL.search((s or "").replace("'제1장'", "").replace("_번역", "")))


def _accels(s: str) -> int:
    """단축키 표시 `&` 의 수 — 바로 뒤에 글자가 오는 것만(`&&`·HTML 개체 `&amp;`·영어 'A & B' 는 빼고)."""
    return len(re.findall(r"&(?=[^\s&])", _ENTITY.sub("", (s or "").replace("&&", ""))))


def check_translation(mid: str, s: str) -> list:
    """번역문 하나의 문제 목록(빈 목록이면 통과). 자리표시·한글·단축키 `&` 수."""
    if not s:
        return ["빈 번역"]
    bad = []
    if _placeholders(s) != _placeholders(mid):
        bad.append("자리표시가 원문과 다르다 %s ≠ %s" % (_placeholders(s), _placeholders(mid)))
    if hangul_leak(mid, s):
        bad.append("번역문에 한글이 남았다")
    if _accels(mid) != _accels(s):
        bad.append("단축키 & 수가 원문과 다르다(%d ≠ %d)" % (_accels(s), _accels(mid)))
    return bad


def _mid(m):
    return m.id if isinstance(m.id, str) else m.id[0]


def todo(locale_dir: Path = LOCALE, langs=None) -> list:
    """번역이 비었거나 fuzzy 인 항목 — 세션이 번역할 목록. fuzzy 는 지금 번역(suggest)과 바뀌기 전 원문(previous)을 함께."""
    out = []
    for d in packs(locale_dir):
        if langs and d.name not in langs:
            continue
        cat = _read_po(d / "LC_MESSAGES" / (DOMAIN + ".po"), locale=d.name)
        for m in cat:
            if not m.id:
                continue
            strs = m.string if isinstance(m.string, (list, tuple)) else (m.string,)
            if not m.fuzzy and all(strs):
                continue
            item = {"lang": d.name, "ctx": m.context, "id": _mid(m),
                    "files": sorted({f for f, _l in m.locations})}
            if isinstance(m.id, (list, tuple)):
                item["nplurals"] = cat.num_plurals
            if m.fuzzy:
                item["suggest"] = list(strs) if isinstance(m.id, (list, tuple)) else strs[0]
                if m.previous_id:
                    item["previous"] = m.previous_id[0]
            out.append(item)
    return out


def fill(items, locale_dir: Path = LOCALE):
    """`todo` 항목에 `str`(복수형이면 목록)을 채운 것을 .po 에 넣는다. 검사를 통과한 것만 넣고 fuzzy 를 지운다.
    반환 (넣은 수, [(lang, id, 문제), …])."""
    by_lang = {}
    for it in items:
        by_lang.setdefault(it["lang"], []).append(it)
    done, errs = 0, []
    for lang, its in by_lang.items():
        po = locale_dir / lang / "LC_MESSAGES" / (DOMAIN + ".po")
        if not po.is_file():
            errs.extend((lang, it["id"][:40], "팩 없음") for it in its)
            continue
        cat = _read_po(po, locale=lang)
        index = {(_mid(m), m.context): m for m in cat if m.id}
        for it in its:
            m = index.get((it["id"], it.get("ctx")))
            val = it.get("str")
            if m is None:
                errs.append((lang, it["id"][:40], "원문이 .po 에 없다(sync 를 먼저)"))
                continue
            plural = isinstance(m.id, (list, tuple))
            vals = list(val) if plural and isinstance(val, (list, tuple)) else [val]
            if plural and len(vals) != cat.num_plurals:
                errs.append((lang, it["id"][:40], "복수형 %d개가 필요하다" % cat.num_plurals))
                continue
            bad = [p for v in vals for p in check_translation(it["id"], v or "")]
            if bad:
                errs.append((lang, it["id"][:40], "; ".join(sorted(set(bad)))))
                continue
            m.string = tuple(vals) if plural else vals[0]
            m.flags.discard("fuzzy")
            m.previous_id = []
            done += 1
        _write_po(cat, po, ignore_obsolete=False, include_previous=True)
    return done, errs


def sync(base: Path = ROOT):
    """추출 + 병합 + 할 일 목록 — 화면 문구를 고친 뒤 한 번."""
    _cat, warns = extract(base)
    update(base / "resources" / "locale")
    return warns, todo(base / "resources" / "locale")


def hook_stop(stdin_text: str, base: Path = ROOT) -> str:
    """Claude Code Stop 훅 — 번역 빈칸·추출 경고가 남았으면 턴을 끝내지 못하게(block) 이유를 돌려준다.
    이미 한 번 막힌 뒤(stop_hook_active)에는 다시 막지 않는다(무한 반복 방지 — 남은 것은 CI 가 잡는다).
    통과면 빈 문자열."""
    try:
        data = json.loads(stdin_text or "{}")
    except ValueError:
        data = {}
    if data.get("stop_hook_active"):
        return ""
    warns, items = sync(base)
    if not warns and not items:
        return ""
    lines = []
    if warns:
        lines.append("추출 경고 %d건(tr 원문이 문자열 리터럴이 아님 — 다국어 SOT §6): %s" % (len(warns), "; ".join(map(str, warns[:3]))))
    if items:
        langs = sorted({i["lang"] for i in items})
        lines.append("언어팩 번역 빈칸·fuzzy %d건(%s). public 에서 `python scripts/i18n.py todo --json <파일>` 로 목록을 받아 "
                     "각 항목에 \"str\" 을 채우고 `python scripts/i18n.py fill <파일>` 로 넣으세요. 용어는 다국어 SOT §12.2 용어표, "
                     "문구 규칙은 §6(자리표시 {이름} 그대로·단축키 & 하나·한글 남기지 않기). 처음 5개: %s"
                     % (len(items), ", ".join(langs), " | ".join(i["id"][:30].replace("\n", " ") for i in items[:5])))
    return json.dumps({"decision": "block", "reason": "\n".join(lines)}, ensure_ascii=False)


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
    if cmd == "sync":
        warns, items = sync()
        for w in warns:
            print("경고:", w)
        print("번역 빈칸·fuzzy %d건" % len(items) + (" — `todo --json <파일>` → 채우기 → `fill <파일>`" if items else ""))
        return 1 if warns else 0
    if cmd == "todo":
        langs = argv[argv.index("--lang") + 1].split(",") if "--lang" in argv else None
        items = todo(langs=langs)
        if "--json" in argv:
            Path(argv[argv.index("--json") + 1]).write_text(
                json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print("번역할 항목 %d건 → %s" % (len(items), argv[argv.index("--json") + 1]))
        else:
            print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    if cmd == "fill" and len(argv) > 2:
        items = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        done, errs = fill([i for i in items if i.get("str")])
        for lang, mid, why in errs:
            print("거부 [%s] %s — %s" % (lang, mid.replace("\n", " "), why))
        compile_all(quiet=True)
        left = len(todo())
        print("넣음 %d · 거부 %d · 남은 빈칸·fuzzy %d (compile 함)" % (done, len(errs), left))
        return 1 if errs or left else 0
    if cmd == "hook-stop":
        # 훅 입력 JSON 은 UTF-8 — Windows 기본(cp949)으로 읽으면 한글이 든 입력에서 깨진다
        out = hook_stop(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if out:
            print(out)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
