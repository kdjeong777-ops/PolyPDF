"""다국어 SOT §10 — 설치 프로그램·업데이트 도우미 (Phase 6, 261008-27)

A. `scripts/i18n.py inno` 가 내장 팩으로 installer/languages.iss 를 만든다 — 마법사 언어([Languages]·마침 안내),
   언어마다 [CustomMessages] 전부, PolyPDF 언어마다 사용 안내 [Files]·[Icons], [Code] 가 쓰는 목록(#define 셋, 같은 길이)
B. 영어 마법사 문구·영어 안내 파일·영어 시작 메뉴 이름에 한글이 없다 · 생성은 멱등(내용이 같으면 쓰지 않는다)
C. PolyPDF.iss 는 문구를 직접 쓰지 않는다(주석 밖 한글 없음) · 쓰는 {cm:…}/CustomMessage('…') 가 모두 있고 남는 키가 없다 ·
   언어 페이지·업그레이드 언어(§10.2 순서)·/APPLANG·InstallLanguage 레지스트리·제거 프로그램 없음(§10.3) 처리가 있다
D. ISCC 가 있으면 작은 가짜 dist 로 **실제 컴파일**(문법·[Code] 검증) — 없으면 건너뛴다
E. 업데이트 설치 도우미: 화면 문구는 실행 때의 언어로 채운 표($T)만 쓰고(스크립트 안 한글은 주석뿐),
   표의 키와 스크립트가 쓰는 키가 같다 · 잔존 파일 정리는 _internal\\ 아래만(§10.3 ①) · PowerShell 문법 오류 없음
"""
import os, sys, re, json, shutil, subprocess, tempfile, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path

fails = []
H = re.compile(r"[가-힣]")


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


spec = importlib.util.spec_from_file_location("i18n_tool", os.path.join(HERE, "scripts", "i18n.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
INST = Path(HERE) / "installer"
tmp = Path(tempfile.mkdtemp(prefix="polypdf_inst_test_"))
try:
    # ── A ──
    out = T.inno(out=tmp / "languages.iss")
    text = out.read_text(encoding="utf-8-sig")
    chk(out.read_bytes().startswith(b"\xef\xbb\xbf"), "A UTF-8 BOM(ISCC 가 한글을 바르게 읽게)")
    table = T._installer_table()
    msgs, app = table["MESSAGES"], table["APP_LANG"]
    chk('Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"; InfoAfterFile: "guide_ko.txt"' in text
        and 'Name: "en"; MessagesFile: "compiler:Default.isl"; InfoAfterFile: "guide_en.txt"' in text,
        "A [Languages] 한국어·영어 마법사와 마침 안내")
    for w in ("korean", "en"):
        keys = set(re.findall(r"^%s\.(\w+)=" % re.escape(w), text, re.M))
        chk(keys == set(msgs), "A %s 마법사 문구가 빠짐없이" % w, str(set(msgs) ^ keys))
    defs = dict(re.findall(r'^#define (AppLang\w+) "([^"]*)"', text, re.M))
    codes = defs.get("AppLangCodes", "").split(",")
    chk(codes[:2] == ["ko", "en"] and len(set(len(v.split(",")) for v in defs.values())) == 1 and len(defs) == 3,
        "A [Code] 목록 셋(코드·이름·마법사)이 같은 길이", str(defs))
    for c in codes:
        chk(("Check: IsAppLang('%s')" % c) in text.split("[Icons]")[0] and ("Check: IsAppLang('%s')" % c) in text.split("[Icons]")[1],
            "A PolyPDF 언어 %s 의 사용 안내 파일·시작 메뉴 항목" % c)

    # ── B ──
    en_lines = [l for l in text.splitlines() if l.startswith("en.")]
    chk(en_lines and not any(H.search(l) for l in en_lines), "B 영어 마법사 문구에 한글이 없다",
        str([l for l in en_lines if H.search(l)][:3]))
    en_files = [l for l in text.splitlines() if "IsAppLang('en')" in l]
    chk(en_files and not any(H.search(l) for l in en_files), "B 영어 안내 파일 이름·시작 메뉴 이름에 한글이 없다", str(en_files))
    guide_en = (INST / "guide_en.txt").read_text(encoding="utf-8-sig")
    chk(not H.search(guide_en), "B 영어 사용 안내 파일에 한글이 없다")
    for w in ("법령", "KCSC", "KIPO", "Vocabulary", "Translat", "API key"):
        chk(w not in guide_en, "B 영어 안내가 숨긴 한국 전용 기능을 말하지 않는다: %s" % w)
    m1 = out.stat().st_mtime_ns
    T.inno(out=out)
    chk(out.stat().st_mtime_ns == m1, "B 내용이 같으면 다시 쓰지 않는다(멱등)")

    # ── C ──
    iss = (INST / "PolyPDF.iss").read_text(encoding="utf-8-sig")
    code_at = iss.index("[Code]")
    outside = [l for l in iss[:code_at].splitlines() if not l.lstrip().startswith(";") and H.search(l)]
    chk(not outside, "C [Code] 앞의 항목에 한글 문구를 직접 쓰지 않는다", str(outside[:3]))
    code = re.sub(r"\{[^}]*\}", "", iss[code_at:])                 # 파스칼 주석 { … } 제거
    code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith(";"))
    lits = [s for s in re.findall(r"'([^']*)'", code) if H.search(s)]
    chk(not lits, "C [Code] 의 문자열에 한글이 없다(CustomMessage 로)", str(lits[:3]))
    used = set(re.findall(r"\{cm:(\w+)\}", iss)) | set(re.findall(r"CustomMessage\('(\w+)'\)", iss))
    chk(used == set(msgs), "C 쓰는 메시지와 installer_text.MESSAGES 가 같다", str(used ^ set(msgs)))
    for needle, what in (("ShowLanguageDialog=no", "표준 언어 창을 쓰지 않는다"),
                         ('#include "languages.iss"', "생성 파일을 넣는다"),
                         ("CreateInputOptionPage(wpWelcome", "첫 설치 언어 페이지"),
                         ("{param:APPLANG|}", "/APPLANG 명령줄"),
                         ("function UpgradeLanguage", "업그레이드 언어(§10.2)"),
                         ('ValueName: "InstallLanguage"; ValueData: "{code:GetAppLang}"; Flags: uninsdeletevalue',
                          "InstallLanguage 레지스트리(제거 때 지움)"),
                         ("if not FileExists(uninstExe) then", "제거 프로그램이 없으면 건너뛴다(§10.3)"),
                         ("DelTree(oldDir + '\\_internal'", "옛 _internal 만 지운다(§10.3)")):
        chk(needle in iss, "C " + what)
    up = iss[iss.index("function UpgradeLanguage"):iss.index("function VerBase")]
    order = [up.index(k) for k in ("gSettingsLang", "ReadSettingsLanguage(exists)", "'InstallLanguage'",
                                   "'Inno Setup: Language'")]
    chk(order == sorted(order), "C 업그레이드 언어 순서 — 설정 언어 → 설정만 있으면 ko → 레지스트리 → 옛 마법사 언어")
    from viewer import i18n
    chk("InstallLanguage" in open(os.path.join(HERE, "viewer", "i18n.py"), encoding="utf-8").read(),
        "C 앱이 같은 레지스트리 값을 읽는다(i18n._registry_install_language)")

    # ── D ──
    iscc = None
    for p in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
              os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe")):
        if os.path.isfile(p):
            iscc = p
            break
    if iscc:
        dist = tmp / "dist"
        dist.mkdir()
        (dist / "PolyPDF.exe").write_bytes(b"MZ")
        shutil.copy2(out, INST / "languages.iss") if not (INST / "languages.iss").is_file() else None
        r = subprocess.run([iscc, "/Q", "/DMyAppVersion=9.9.9", "/DDistDir=" + str(dist), "/O" + str(tmp),
                            str(INST / "PolyPDF.iss")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(INST))
        chk(r.returncode == 0 and (tmp / "PolyPDF-Setup-v9.9.9.exe").is_file(),
            "D ISCC 실제 컴파일(문법·[Code])", (r.stdout + r.stderr)[-600:])
    else:
        print("SKIP - D ISCC 없음(Inno Setup 6) — 컴파일 검사 생략")

    # ── E ──
    from viewer import updater
    i18n.install(None, "ko")
    ps = updater._PS_INSTALLER
    body = "\n".join(l.split("#")[0] for l in ps.splitlines())
    chk(not H.search(body), "E 설치 도우미 스크립트 안의 한글은 주석뿐", str([l for l in body.splitlines() if H.search(l)][:3]))
    keys_ps = set(re.findall(r"\$T\.(\w+)", ps))
    keys_py = set(updater.installer_texts())
    chk(keys_ps == keys_py, "E 문구 표 키 = 스크립트가 쓰는 키", str(keys_ps ^ keys_py))
    i18n.install(None, "en")
    t_en = updater.installer_texts()
    chk(not any(H.search(v) for v in t_en.values()), "E en 이면 표가 영어로 채워진다")
    chk("{0}" in t_en["installing"] and "{1}" in t_en["installing"] and "{" not in t_en["done"],
        "E 자리표시는 PowerShell -f 꼴({0}·{1})")
    i18n.install(None, "ko")
    chk("StartsWith('_internal\\'" in ps, "E 잔존 파일 정리는 _internal\\ 아래만(§10.3 ①)")
    import base64
    script = ps.replace("__TEXT_B64__", base64.b64encode(json.dumps(t_en).encode()).decode())
    p1 = tmp / "upd.ps1"
    p1.write_text(script, encoding="utf-8-sig")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e); $e.Count" % p1],
                       capture_output=True, text=True)
    chk(r.stdout.strip() == "0", "E PowerShell 문법 오류 없음", r.stdout + r.stderr)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
