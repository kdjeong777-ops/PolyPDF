# -*- coding: utf-8 -*-
"""261114-8(마스터 §1.1, 사용자 결정 B안·'다음 판에 한 번에'): 이사 판 — 스위치 `branding.MOVED` 하나로 밖에 보이는 제품 단위
내부 ID 를 PolyPinax/PolyPix 로 옮긴다. 스위치가 꺼져 있으면(beta.13) 지금과 같아야 한다.

A. 스위치 꺼짐 = 지금 값(설정 폴더·exe·작업 표시줄 ID·설치·자산 이름·업데이트 저장소·휴대용 표식·사진 ProgID 모두 PolyPDF)
B. 스위치 켜짐 값(`ids(True)`) = PolyPinax/PolyPix, 업데이트 저장소 kdjeong777-ops/PolyPinax
C. 설정 폴더 이사 `main.move_profile(옛, 새)` — 옛 폴더만 있으면 새 이름으로(이름 바꾸기 — 큰 색인도 즉시), 새 폴더에 설정이
   있으면 손대지 않음, 옮기지 못하면 옛 폴더를 그대로 쓰라고 알림
D. 창 위치 등 QSettings(레지스트리) 옛 키 → 새 키 복사 `main.copy_reg_tree`(실제 HKCU 아래 시험 전용 키에서)
E. 휴대용 표식 — 새·옛 이름 모두 알아본다
F. 업데이트 — 설치 파일은 새·옛 접두 모두, 저장소는 UPDATE_REPO, 업데이트 도우미는 새·옛 실행 파일 이름 모두
G. 옛 HKCU 등록(ProgID 명령)이 없는 실행 파일을 가리키면 지금 실행 파일로 고친다 `pdf_default.repair_user_progids`(가짜 레지스트리)
H. 설치 언어 레지스트리 — 새 키 → 옛 키 순서로 읽는다
I. 설치 프로그램 — `/DMOVED` 하나로 이름이 갈린다(#ifdef), 옛 실행 파일도 닫는다, 이사 때 설치 폴더를 이어 쓰지 않는다
J. 빌드·릴리스 — exe·dist 이름을 branding 에서 읽는다(build_ci.bat·build_exe.py·release.yml), 이사 판은 옛 자산 이름 사본도 올린다(다리 판)
N. (261114-23) 개발 실행(.venv main.py)은 스위치가 켜져도 실제 설정 폴더를 옮기지 않고, 새 폴더에 설정이 없으면 옛 폴더를 함께 쓴다
"""
import os, re, sys, tempfile, shutil, importlib
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("POLYPDF_PROFILE", None)
os.environ["QT_QPA_PLATFORM"] = "offscreen"             # 검사 작성 SOT §14.7 — N 이 QStandardPaths 를 쓴다

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8-sig") as f:
        return f.read()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_move_"))
try:
    b = importlib.import_module("viewer.branding")
    ids = getattr(b, "ids", None)
    chk(callable(ids), "0 branding.ids 가 있다")
    # ── A ──
    # 스위치는 bool. 꺼짐(beta.13)이면 모듈 값 = ids(False), 켜짐(이사 판)이면 = ids(True) — 켜는 커밋이 한 줄이게 두 상태 모두 맞는 검사
    chk(isinstance(getattr(b, "MOVED", None), bool), "A 스위치 MOVED 는 참/거짓 하나")
    if callable(ids):
        cur = ids(b.MOVED)
        chk((b.APP_ID, b.EXE_STEM, b.AUMID, b.SETUP_PREFIX, b.UPDATE_REPO, b.PORTABLE_MARKER, b.PHOTO_PROG_ID)
            == (cur["APP_ID"], cur["EXE_STEM"], cur["AUMID"], cur["SETUP_PREFIX"], cur["UPDATE_REPO"], cur["PORTABLE_MARKER"], cur["PHOTO_PROG_ID"]),
            "A 모듈 값 = ids(MOVED)")
        off = ids(False)
        chk(off == {"APP_ID": "PolyPDF", "EXE_STEM": "PolyPDF", "AUMID": "LocalTools.PolyPDF", "SETUP_PREFIX": "PolyPDF-Setup-v",
                    "ASSET_PREFIX": "PolyPDF", "UPDATE_REPO": "kdjeong777-ops/PolyPDF", "PORTABLE_MARKER": "PolyPDF.portable",
                    "PHOTO_PROG_ID": "PolyPDF.photo", "PHOTO_APP": "PolyPDFPhoto"}, "A 꺼짐 = 지금 값", str(off))
        on = ids(True)
        # ── B ──
        chk(on["APP_ID"] == on["EXE_STEM"] == "PolyPinax" and on["AUMID"] == "LocalTools.PolyPinax"
            and on["SETUP_PREFIX"] == "PolyPinax-Setup-v" and on["UPDATE_REPO"] == "kdjeong777-ops/PolyPinax"
            and on["PORTABLE_MARKER"] == "PolyPinax.portable" and on["PHOTO_PROG_ID"] == "PolyPix.photo", "B 켜짐 = 새 이름", str(on))
    chk(getattr(b, "MODES", {}).get("pdf") == "PolyPDF" and b.MODES.get("photo") == "PolyPix" and b.PRODUCT == "PolyPinax",
        "B 제품·모드 이름 한 곳(PolyPinax · PolyPDF · PolyPix)")

    import main
    # ── K ── 스위치가 꺼져 있으면 이사 길이 한 번도 돌지 않는다(지휘 조건 ①)
    calls = []
    _orig = (main.move_profile, main.copy_reg_tree) if hasattr(main, "move_profile") else None
    _was = main._branding.MOVED
    main._branding.MOVED = False                           # 이사 판(켜짐)에서도 '꺼짐이면 돌지 않는다' 를 본다
    if _orig:
        main.move_profile = lambda *a, **k: calls.append(("move", a)) or "moved"
        main.copy_reg_tree = lambda *a, **k: calls.append(("reg", a)) or 0
        import viewer.pdf_default as _pdd
        _rep = _pdd.repair_user_progids
        _pdd.repair_user_progids = lambda *a, **k: calls.append(("progid", a)) or []
        _frozen = getattr(sys, "frozen", None)
        sys.frozen = True                                  # 빌드본처럼 — 그래도 스위치가 꺼져 있으면 돌지 않아야 한다
        try:
            main._move_to_new_name()
            main._repair_progids()
        finally:
            main.move_profile, main.copy_reg_tree = _orig
            _pdd.repair_user_progids = _rep
            if _frozen is None:
                del sys.frozen
            else:
                sys.frozen = _frozen
        chk(not calls, "K 스위치 꺼짐 — 설정 폴더 이사·레지스트리 복사·ProgID 고치기가 한 번도 돌지 않는다", str(calls))
    main._branding.MOVED = _was
    # ── N ── (261114-23) 개발 실행(빌드본 아님)은 스위치가 켜져도 옮기지 않는다 — 깔린 옛 판이 같은 실제 설정 폴더를 쓰고 있다
    dpd = getattr(main, "dev_profile_dirs", None)
    chk(callable(dpd), "N main.dev_profile_dirs 가 있다")
    if callable(dpd) and _orig:
        from PyQt6.QtCore import QStandardPaths
        QStandardPaths.setTestModeEnabled(True)            # 실제 설정 폴더를 보지 않게(검사 작성 SOT §14.7.2)
        import viewer.settings_store as _ss
        calls = []
        main._branding.MOVED = True
        main.move_profile = lambda *a, **k: calls.append(("move", a)) or "moved"
        main.copy_reg_tree = lambda *a, **k: calls.append(("reg", a)) or 0
        _fz = getattr(sys, "frozen", None)
        if _fz is not None:
            del sys.frozen
        _ov = (_ss._DIR_OVERRIDE, getattr(_ss, "_LOCAL_DIR_OVERRIDE", None))
        try:
            main._move_to_new_name()
        finally:
            main.move_profile, main.copy_reg_tree = _orig
            main._branding.MOVED = _was
            if _fz is not None:
                sys.frozen = _fz
            _ss._DIR_OVERRIDE, _ss._LOCAL_DIR_OVERRIDE = _ov
        chk(not calls, "N 개발 실행 + 스위치 켜짐 — 설정 폴더 이름 바꾸기·레지스트리 복사를 하지 않는다", str(calls))
        o, n_, ol, nl = tmp / "dv" / "PolyPDF", tmp / "dv" / "PolyPinax", tmp / "dl" / "PolyPDF", tmp / "dl" / "PolyPinax"
        o.mkdir(parents=True); ol.mkdir(parents=True)
        (o / "settings.json").write_text("{}", encoding="utf-8")
        r = dpd(o, n_, ol, nl)
        chk(r == {"settings": str(o), "local": str(ol)} and o.is_dir() and not n_.exists(),
            "N 새 폴더에 설정이 없으면 옛 폴더를 그대로 함께 쓴다(옮기지 않음)", str(r))
        n_.mkdir(parents=True); (n_ / "settings.json").write_text("{}", encoding="utf-8"); nl.mkdir(parents=True)
        r = dpd(o, n_, ol, nl)
        chk(r == {"settings": None, "local": None}, "N 이사 판 설치본이 옮긴 뒤(새 폴더에 설정)는 새 폴더", str(r))
        _ss._LOCAL_DIR_OVERRIDE = str(ol)
        try:
            chk(_ss.local_data_dir() == ol, "N 도구 자료 폴더도 옛 폴더를 따른다(settings_store._LOCAL_DIR_OVERRIDE)")
        finally:
            _ss._LOCAL_DIR_OVERRIDE = None
    # ── P ── (261114-23) 빌드본: 도구 자료 폴더(%LOCALAPPDATA% — 사용자 tessdata)를 못 옮기면 그 실행은 옛 폴더를 쓴다(설정 폴더와 같은 규칙)
    if _orig:
        from PyQt6.QtCore import QStandardPaths
        QStandardPaths.setTestModeEnabled(True)
        import viewer.settings_store as _ss
        la_old = str(Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / b.OLD_ID)
        main._branding.MOVED = True
        main.move_profile = lambda o, n: "fail" if str(o) == la_old else "none"
        main.copy_reg_tree = lambda *a, **k: 0
        _fz = getattr(sys, "frozen", None)
        sys.frozen = True
        _ov = (_ss._DIR_OVERRIDE, getattr(_ss, "_LOCAL_DIR_OVERRIDE", None), _ss.PORTABLE)
        _ss.PORTABLE = False
        try:
            main._move_to_new_name()
            got = getattr(_ss, "_LOCAL_DIR_OVERRIDE", None)
        finally:
            main.move_profile, main.copy_reg_tree = _orig
            main._branding.MOVED = _was
            if _fz is None:
                del sys.frozen
            else:
                sys.frozen = _fz
            _ss._DIR_OVERRIDE, _ss._LOCAL_DIR_OVERRIDE, _ss.PORTABLE = _ov
        chk(got == la_old, "P 빌드본에서 도구 자료 폴더를 못 옮기면 이번 실행은 옛 폴더(사용자 tessdata 를 잃지 않음)", str(got))
    # ── L ── 정보 창 소스코드 주소·구성요소 저장소
    ab = importlib.import_module("viewer.about")
    chk(ab.SOURCE_URL == "https://github.com/" + b.UPDATE_REPO, "L 정보 창 소스코드 주소 = 지금 저장소(이사 판부터 새 저장소)", ab.SOURCE_URL)
    comp = importlib.import_module("viewer.components")
    chk(comp.repo_or_default("") == "kdjeong777-ops/PolyPDF", "L 구성요소는 옛 저장소 그대로(보관해도 받는다)")
    nt = importlib.import_module("viewer.study.neural_tts")
    chk(nt.COMPONENTS_BASE.startswith("https://github.com/kdjeong777-ops/PolyPDF/"), "L 자연 음성 구성요소 주소도 옛 저장소")
    # ── M ── 다리 판 안내는 언어 절 **안**에 — 앱 업데이트 창(split_lang_sections)은 첫 언어 표시 앞 글을 버린다(SOT 점검 261114)
    sys.path.insert(0, os.path.join(HERE, "scripts"))
    rn = importlib.import_module("release_notes")
    amn = getattr(rn, "add_move_notice", None)
    chk(callable(amn), "M release_notes.add_move_notice 가 있다")
    if callable(amn):
        from viewer.widgets.update_dialog import split_lang_sections
        src = ("<!-- lang:ko -->\n#### 이번 판에서 달라진 점\n\n- 가\n\n"
               "<!-- lang:en -->\n#### What's new in this version\n\n- a\n")
        out = amn(src)
        secs = split_lang_sections(out)
        chk("PolyPinax" in secs.get("ko", "") and "kdjeong777-ops/PolyPinax" in secs.get("ko", "") and "- 가" in secs.get("ko", ""),
            "M 한국어 절 안에 '새 이름·새 GitHub' 안내(본문은 그대로)", repr(secs.get("ko", ""))[:120])
        chk("PolyPinax" in secs.get("en", "") and "moved" in secs.get("en", "") and "- a" in secs.get("en", ""),
            "M 영어 절 안에 영어 안내", repr(secs.get("en", ""))[:120])
        chk(out.lstrip().startswith("<!-- lang:"), "M 첫 언어 표시 앞에 글이 없다(앱 창이 버리는 자리)")
        chk(amn(out) == out, "M 두 번 불러도 한 번만 들어간다")
        plain = split_lang_sections(amn("#### 바뀐 내용\n- 가\n"))
        chk("PolyPinax" in plain.get("ko", ""), "M 언어 표시가 없는 옛 꼴도 안내가 보인다")
    ry2 = read(".github/workflows/release.yml")
    chk("$move +" not in ry2 and "APP_BRIDGE" in read("scripts/release_notes.py"),
        "M release.yml 은 노트 맨 앞에 붙이지 않고 release_notes.py 가 다리 판이면 절마다 넣는다")
    # ── O ── (261114-24) 새 저장소에서 돌아도 구성요소(ffmpeg·Tesseract·자연 음성)는 branding.COMPONENTS_REPO(옛 저장소)에서 받는다
    chk("components -R $env:GITHUB_REPOSITORY" not in ry2 and ry2.count("components -R $env:COMPONENTS_REPO") == 3
        and "from viewer.branding import COMPONENTS_REPO" in ry2,
        "O release.yml 구성요소 내려받기 세 곳이 branding.COMPONENTS_REPO 를 본다(새 저장소엔 components 릴리스가 없다)")
    chk("kdjeong777-ops/PolyPDF" not in ry2.replace("(kdjeong777-ops/PolyPDF)", ""),
        "O release.yml 에 옛 저장소 이름을 박지 않는다(다리 판 판정도 branding.OLD_REPO)")
    chk("kdjeong777-ops/PolyPDF\"" not in read("scripts/stable_check.py") and 'dist\\PolyPDF' not in read("scripts/make_release_zip.ps1")
        and 'dist\\PolyPDF' not in read("scripts/publish_release.ps1"),
        "O 수동 릴리스·안정 점검 도구도 이름·저장소를 branding 에서")
    # ── C ──
    mp = getattr(main, "move_profile", None)
    chk(callable(mp), "C main.move_profile 이 있다")
    if callable(mp):
        old, new = tmp / "LocalTools" / "PolyPDF", tmp / "LocalTools" / "PolyPinax"
        old.mkdir(parents=True)
        (old / "settings.json").write_text('{"a": 1}', encoding="utf-8")
        (old / "index.db").write_bytes(b"x" * 1000)
        r = mp(old, new)
        chk(r == "moved" and (new / "settings.json").exists() and (new / "index.db").stat().st_size == 1000 and not old.exists(),
            "C 옛 폴더만 있으면 새 이름으로 옮긴다", r)
        old.mkdir(parents=True)
        (old / "settings.json").write_text('{"old": 1}', encoding="utf-8")
        r2 = mp(old, new)
        chk(r2 == "skip" and '"a"' in (new / "settings.json").read_text(encoding="utf-8") and old.exists(),
            "C 새 폴더에 설정이 있으면 손대지 않는다(옛 폴더도 그대로)", r2)
        chk(mp(tmp / "none", tmp / "none2") == "none", "C 옛 폴더가 없으면 할 일 없음")
        # 옮기지 못함 — 열린 파일이 이름 바꾸기를 막는 Windows 상황
        o2, n2 = tmp / "o2", tmp / "n2"
        o2.mkdir()
        (o2 / "settings.json").write_text("{}", encoding="utf-8")
        fh = open(o2 / "settings.json", "rb")
        try:
            r3 = mp(o2, n2)
        finally:
            fh.close()
        chk(r3 in ("fail", "moved") and (o2 / "settings.json").exists() if r3 == "fail" else True,
            "C 옮기지 못하면 'fail' — 옛 폴더는 그대로(부르는 쪽이 옛 폴더를 쓴다)", r3)
    # ── D ──
    cr = getattr(main, "copy_reg_tree", None)
    chk(callable(cr), "D main.copy_reg_tree 가 있다")
    if callable(cr) and sys.platform == "win32":
        import winreg
        base = r"Software\polypdf_move_test_%d" % os.getpid()
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\Old\MainWindow") as k:
                winreg.SetValueEx(k, "geometry", 0, winreg.REG_BINARY, b"\x01\x02")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\Old") as k:
                winreg.SetValueEx(k, "x", 0, winreg.REG_SZ, "1")
            n = cr(base + r"\Old", base + r"\New")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\New\MainWindow") as k:
                g = winreg.QueryValueEx(k, "geometry")[0]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\New") as k:
                x = winreg.QueryValueEx(k, "x")[0]
            chk(n >= 2 and g == b"\x01\x02" and x == "1", "D 옛 레지스트리 키(창 위치 등)를 새 키로 복사", str(n))
            chk(cr(base + r"\Old", base + r"\New") == 0, "D 새 키가 이미 있으면 덮지 않는다")
        finally:
            from viewer.pdf_default import Reg
            Reg().delete_tree("HKCU", base)
    # ── E ──
    ss = importlib.import_module("viewer.settings_store")
    pdir = tmp / "port"
    pdir.mkdir()
    (pdir / "PolyPinax.portable").write_text("", encoding="utf-8")
    chk(ss.portable_dir(pdir) is not None, "E 새 표식(PolyPinax.portable)도 휴대용으로 안다")
    pdir2 = tmp / "port2"
    pdir2.mkdir()
    (pdir2 / "PolyPDF.portable").write_text("", encoding="utf-8")
    chk(ss.portable_dir(pdir2) is not None, "E 옛 표식(PolyPDF.portable)도 안다")
    # ── F ──
    up = importlib.import_module("viewer.updater")
    chk(up.DEFAULT_REPO == b.UPDATE_REPO, "F 업데이트 저장소 = branding.UPDATE_REPO")
    for name in ("PolyPinax-Setup-v9.0.0.exe", "PolyPDF-Setup-v9.0.0.exe"):
        info = up._to_info({"tag_name": "v9.0.0", "assets": [
            {"name": name, "browser_download_url": "https://github.com/x/y/releases/download/v9.0.0/" + name},
            {"name": name + ".sha256", "browser_download_url": "https://github.com/x/y/releases/download/v9.0.0/" + name + ".sha256"}]})
        chk(info.get("setup_name") == name, "F 설치 파일 접두 새·옛 모두 — " + name, str(info.get("setup_name")))
    ps = up._PS_INSTALLER
    chk("'PolyPinax.exe'" in ps and "'PolyPDF.exe'" in ps, "F 업데이트 도우미가 새·옛 실행 파일 이름 모두로 다른 창을 찾는다")
    chk("-like 'PolyPinax\\*'" in ps and "-like 'PolyPDF\\*'" in ps, "F zip 맨 위 폴더 이름 새·옛 모두 벗긴다")
    # ── G ──
    pdd = importlib.import_module("viewer.pdf_default")
    rep = getattr(pdd, "repair_user_progids", None)
    chk(callable(rep), "G pdf_default.repair_user_progids 가 있다")
    if callable(rep):
        class FakeReg:
            def __init__(self):
                self.d = {}
            def get(self, root, path, name=""):
                return self.d.get((root, path.lower(), name))
            def set(self, root, path, name, value, none_type=False):
                self.d[(root, path.lower(), name)] = value
        fr = FakeReg()
        gone = str(tmp / "old" / "PolyPDF.exe")
        exe = str(tmp / "new" / "PolyPinax.exe")
        fr.set("HKCU", r"Software\Classes\PolyPDF.photo\shell\open\command", "", '"%s" "%%1"' % gone)
        fr.set("HKCU", r"Software\Classes\PolyPDF.pdf\shell\open\command", "", '"%s" "%%1"' % gone)
        other = str(tmp / "elsewhere" / "Other.exe")
        fr.set("HKCU", r"Software\Classes\PolyPix.photo\shell\open\command", "", '"%s" "%%1"' % other)
        done = rep(fr, exe, exists=lambda p: p == other)
        chk(fr.get("HKCU", r"Software\Classes\PolyPDF.photo\shell\open\command") == '"%s" "%%1"' % exe
            and fr.get("HKCU", r"Software\Classes\PolyPDF.pdf\shell\open\command") == '"%s" "%%1"' % exe,
            "G 없는 실행 파일을 가리키는 옛 ProgID 명령을 지금 실행 파일로", str(done))
        chk(fr.get("HKCU", r"Software\Classes\PolyPix.photo\shell\open\command") == '"%s" "%%1"' % other,
            "G 있는 실행 파일을 가리키면 그대로(휴대용 다른 폴더 등)")
    # ── H ──
    i18 = read("viewer/i18n.py")
    chk("for key in (r\"Software\\\\\" + APP_ID, r\"Software\\\\\" + OLD_ID)" in i18 or "_INSTALL_KEYS" in i18,
        "H 설치 언어 — 새 키·옛 키 순서로 읽는다")
    # ── I ──
    iss = read("installer/PolyPDF.iss")
    chk("#ifdef MOVED" in iss and '#define MyAppId "PolyPinax"' in iss and '#define MyAppId "PolyPDF"' in iss,
        "I 설치 프로그램 — /DMOVED 로 내부 ID 가 갈린다")
    chk(re.search(r'^#define MyAppExe MyAppId \+ "\.exe"$', iss, re.M) is not None
        and iss.count("AppUserModelID: \"LocalTools.{#MyAppId}\"") == 2 and "OutputBaseFilename={#MyAppId}-Setup-v{#MyAppVersion}" in iss,
        "I 실행 파일·작업 표시줄 ID·설치 파일 이름은 MyAppId 에서")
    kill = [ln for ln in iss.splitlines() if "taskkill.exe" in ln and "/IM" in ln]
    chk(kill and all("/IM PolyPinax.exe" in ln and "/IM PolyPDF.exe" in ln for ln in kill), "I 옛·새 실행 파일 모두 닫는다", str(kill))
    chk(re.search(r"#ifdef MOVED[\s\S]*?UsePreviousAppDir=no", iss) is not None, "I 이사 때는 설치 폴더를 이어 쓰지 않는다(새 폴더로)")
    # ── J ──
    bat = read("build_ci.bat")
    chk('--name "%APP_EXE%"' in bat and "EXE_STEM" in bat and "dist\\PolyPDF" not in bat, "J build_ci.bat 은 branding.EXE_STEM 으로")
    be = read("build_exe.py")
    chk("EXE_STEM" in be and '"--name", "PolyPDF"' not in be, "J build_exe.py 도")
    ry = read(".github/workflows/release.yml")
    chk("EXE_STEM" in ry and "dist\\PolyPDF" not in ry and "/DMOVED" in ry, "J release.yml — 이름은 branding 에서, 이사면 /DMOVED")
    chk("bridge" in ry.lower() or "다리" in ry, "J 이사 판은 옛 자산 이름 사본도 올린다(다리 판)")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
