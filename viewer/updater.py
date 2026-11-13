"""260618-11: GitHub Releases 기반 앱 내 업데이트(확인·다운로드·자동 교체).

- check_latest(repo): 공개 저장소의 최신 릴리스(태그·자산·노트) 조회 (urllib, 토큰 불필요).
- is_newer: SemVer(major.minor.patch) 비교.
- download_asset: 진행 콜백과 함께 릴리스 zip 다운로드.
- apply_update: 실행 중인 exe 는 자기 자신을 덮어쓸 수 없으므로, 도우미 .bat 가
  '앱 종료 대기 → 압축 해제 → 설치폴더 덮어쓰기 → 재실행' 한다. 호출 후 앱을 종료해야 함.

배포(frozen) exe 에서만 실제 교체가 의미 있음(소스 실행 시엔 확인만).
릴리스 자산: 이름에 'win' 이 든 .zip 우선(없으면 첫 .zip). CI 는 PolyPDF-<tag>-win64.zip 생성.
zip 루트에 PolyPDF.exe·_internal/ … 또는 PolyPDF/ 하위 — 둘 다 처리.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import subprocess
from pathlib import Path
# urllib.request 는 쓰는 함수에서 싣는다 — 시작 때 약 0.05초(261014-26, 마스터 §5 시작 import)

from viewer.i18n import tr                      # 설치 도우미 문구(다국어 SOT §10.4)

from viewer import branding as _br

ASSET_NAME = "PolyPDF-windows.zip"
# 260618-11: 기본 업데이트 저장소(설정 update_repo 가 비어 있으면 이 값 사용 — 입력 불필요).
#   261114-8(마스터 §1.1): 이사 스위치(branding.MOVED)가 정한다 — 이사 판부터 kdjeong777-ops/PolyPinax.
#   옛 판은 옛 저장소만 본다 → 이사 판을 옛 저장소에도 옛 자산 이름으로 올린다(다리 판, 릴리스 SOT §14.5 U26).
DEFAULT_REPO = _br.UPDATE_REPO
_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_UA = "PolyPDF-Updater"
CREATE_NO_WINDOW = 0x08000000


def current_version() -> str:
    try:
        from viewer import __version__
        return __version__
    except Exception:
        return "0.0.0"


def _vtuple(s: str) -> tuple:
    """'v2.23.0' / '2.23.0-rc1' → (2,23,0). 숫자 외 토큰에서 중단. (호환용 — 거친 X.Y.Z)"""
    s = (s or "").strip().lstrip("vV")
    out: list = []
    for p in re.split(r"[.\-+_]", s):
        if p.isdigit():
            out.append(int(p))
        else:
            break
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _vkey(s: str):
    """260618-33: SemVer 정렬키 또는 None(비버전 태그).
    프리릴리즈(`-beta`/`-rc` 등)는 같은 X.Y.Z 정식보다 **작게** 정렬한다.
      'v2.41.0'        → ((2,41,0), 1, ())            # final flag 1
      'v2.41.0-beta.1' → ((2,41,0), 0, ((0,1,''), (1,0,'beta')...))  # final flag 0 < 1
    식별자 비교: 숫자(0,n,'') < 문자(1,0,str); 필드수 적은 쪽이 작음(SemVer 규칙)."""
    s = (s or "").strip().lstrip("vV").split("+", 1)[0]
    if "-" in s:
        rel, pre = s.split("-", 1)
    else:
        rel, pre = s, None
    parts = rel.split(".")
    if not parts or not parts[0].isdigit():
        return None                              # 비버전(components 등)
    nums: list = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            break
    while len(nums) < 3:
        nums.append(0)
    nums = tuple(nums[:3])
    if pre is None:
        return (nums, 1, ())                     # 정식
    ids = []
    for part in re.split(r"[.\-_]", pre):
        if not part:
            continue
        if part.isdigit():
            ids.append((0, int(part), ""))       # 숫자 식별자 우선(작음)
        else:
            ids.append((1, 0, part.lower()))
    return (nums, 0, tuple(ids))


def is_prerelease_tag(tag: str) -> bool:
    """260618-33: 태그 접미사 기준 프리릴리즈 여부(예: 'v2.41.0-beta.1')."""
    k = _vkey(tag)
    return bool(k is not None and k[1] == 0)


def is_newer(latest: str, current: str) -> bool:
    kl, kc = _vkey(latest), _vkey(current)
    return bool(kl is not None and kc is not None and kl > kc)


def valid_repo(repo: str) -> bool:
    repo = (repo or "").strip()
    return bool(repo) and "/" in repo and not repo.upper().startswith("OWNER")


def _get_json(url: str, timeout: float):
    import urllib.request
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# 260628(보안감사 A): 업데이트 자산은 GitHub 호스트에서만 받는다.
#   자산 URL 은 GitHub API 응답(browser_download_url)에서 오지만, 저장소가
#   잘못 설정/침해되면 임의 호스트를 가리킬 수 있으므로 다운로드 전에 검증한다.
_TRUSTED_ASSET_HOSTS = ("github.com", "objects.githubusercontent.com",
                        "release-assets.githubusercontent.com")


def is_trusted_asset_url(url: str) -> bool:
    """https + GitHub 계열 호스트만 허용(서브도메인은 접미사 일치)."""
    try:
        from urllib.parse import urlparse
        u = urlparse(str(url or ""))
        if u.scheme != "https" or not u.hostname:
            return False
        h = u.hostname.lower()
        return any(h == d or h.endswith("." + d) for d in _TRUSTED_ASSET_HOSTS)
    except Exception:
        return False


def sha256_file(path) -> str:
    """파일의 SHA-256 소문자 hex. 실패 시 ''."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _to_info(rel):
    """릴리스 dict → 표준 info. 자산 zip 은 'win' 포함분 우선, 없으면 첫 zip."""
    if not isinstance(rel, dict):
        return None
    tag = str(rel.get("tag_name") or "")
    assets = rel.get("assets") or []
    zips = [a for a in assets if str(a.get("name") or "").lower().endswith(".zip")]

    # 260618-14: 자동 업데이트는 경량 'update' zip 우선(없으면 win64 full, 그다음 첫 zip).
    #   update zip 은 안 바뀌는 무거운 부분(ffmpeg·tesseract·모델)을 제외 → 기존 설치분 보존.
    def _score(a):
        n = str(a.get("name") or "").lower()
        # 261009-22(마스터 §14.9): 휴대용 zip(맨 위 PolyPDF\ 폴더 + 표식)은 업데이트 자산이 아니다
        # 261114-8: 다리 판은 새·옛 이름 zip 이 함께 있다 — 이 판의 이름(ASSET_PREFIX)을 먼저
        return (0 if "portable" in n else 1, 1 if "update" in n else 0, 1 if "win" in n else 0,
                1 if n.startswith(_br.ASSET_PREFIX.lower() + "-") else 0)
    pick = max(zips, key=_score) if zips else None
    asset_url = pick.get("browser_download_url") if pick else None
    asset_name = str(pick.get("name") or "") if pick else ""
    # 260628(A): 신뢰 호스트가 아니면 자산을 버린다(업데이트 미제공 = 안전한 실패).
    if asset_url and not is_trusted_asset_url(asset_url):
        asset_url, asset_name = None, ""
    # 260628(A): 같은 릴리스의 '<자산명>.sha256' 무결성 파일(있으면).
    sha_url = ""
    # 260628-12(U8): 잔존 파일 정리용 정식 파일목록(있으면). 없으면 정리는 생략된다.
    man_url = ""
    for a in assets:
        if str(a.get("name") or "").lower().endswith(".manifest.txt"):
            man_url = a.get("browser_download_url") or ""
            break
    if man_url and not is_trusted_asset_url(man_url):
        man_url = ""
    if asset_name:
        sha_url = _sha_url_for(assets, asset_name)
    # 261108-13(U24): 설치 프로그램 `PolyPDF-Setup-v<판>.exe` 와 그 `.sha256` — 둘 다 있어야 설치본 길을 쓴다.
    #   261114-8: 접두는 새·옛 이름 모두(`branding.ALL_SETUP_PREFIXES`) — 이 판의 이름(SETUP_PREFIX)을 먼저 고른다(다리 판엔 둘 다 있다)
    setup_url, setup_name, setup_sha_url = "", "", ""
    prefixes = [_br.SETUP_PREFIX.lower()] + [p.lower() for p in _br.ALL_SETUP_PREFIXES if p != _br.SETUP_PREFIX]
    cands = [a for a in assets if str(a.get("name") or "").lower().endswith(".exe")
             and any(str(a.get("name") or "").lower().startswith(p) for p in prefixes)]
    cands.sort(key=lambda a: next(i for i, p in enumerate(prefixes) if str(a.get("name") or "").lower().startswith(p)))
    if cands:
        a = cands[0]
        n = str(a.get("name") or "")
        u = a.get("browser_download_url") or ""
        if is_trusted_asset_url(u):
            setup_url, setup_name = u, n
            setup_sha_url = _sha_url_for(assets, n)
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "notes": str(rel.get("body") or ""),
        "asset_url": asset_url,
        "asset_name": asset_name,
        "sha_url": sha_url,
        "manifest_url": man_url,        # 260628-12(U8)
        "setup_url": setup_url,         # 261108-13(U24)
        "setup_name": setup_name,
        "setup_sha_url": setup_sha_url,
        "html_url": str(rel.get("html_url") or ""),
    }


def _sha_url_for(assets, name: str) -> str:
    """같은 릴리스의 `<name>.sha256` 자산 주소(신뢰 호스트만). 없으면 ''."""
    want = (str(name) + ".sha256").lower()
    for a in assets or []:
        if str(a.get("name") or "").lower() == want:
            u = a.get("browser_download_url") or ""
            return u if is_trusted_asset_url(u) else ""
    return ""


def fetch_manifest(info: dict, timeout: float = 20.0) -> str:
    """260628-12(U8): 릴리스의 `*.manifest.txt`(정식 파일목록)를 임시파일로 받아 경로 반환.

    없거나 실패하면 `""` — 그러면 설치 도우미가 **정리를 통째로 건너뛴다**(안전 실패).
    목록은 반드시 **full 빌드 기준**이어야 한다. update zip 기준으로 만들면 무거운 자산
    (ffmpeg·tesseract 등)이 목록에 없어 지워진다."""
    import urllib.request
    url = str((info or {}).get("manifest_url") or "")
    if not url or not is_trusted_asset_url(url):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if not data or len(data.splitlines()) < 500:      # 잘린 목록이면 쓰지 않는다
            return ""
        path = os.path.join(tempfile.gettempdir(), "polypdf_update_manifest.txt")
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return ""


def fetch_expected_sha256(info: dict, timeout: float = 10.0) -> str:
    """릴리스의 `<자산명>.sha256` 을 읽어 기대 해시(소문자 hex) 반환. 없으면 ''.

    파일 형식은 `sha256sum` 관례(`<hex>  <파일명>`)와 hex 단독 모두 허용."""
    return fetch_sha256((info or {}).get("sha_url") or "", timeout)


def fetch_sha256(url: str, timeout: float = 10.0) -> str:
    """`.sha256` 자산 주소에서 기대 해시(소문자 hex). 없거나 형식이 틀리면 ''."""
    import urllib.request
    if not url or not is_trusted_asset_url(url):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read(4096).decode("utf-8", "replace").strip()
    except Exception:
        return ""
    tok = txt.split()[0].lower() if txt.split() else ""
    return tok if (len(tok) == 64 and all(c in "0123456789abcdef" for c in tok)) else ""


def check_latest(repo: str, timeout: float = 8.0, channel: str = "stable"):
    """최신 '버전' 릴리스 정보 dict 또는 None.

    260618-33: 업데이트 채널 — `channel="stable"` 은 **태그 접미사 프리릴리즈
    (`-beta`/`-rc` 등)를 제외**하고 정식만 고려, `"beta"` 는 전부 고려(프리릴리즈<정식
    SemVer 우선순위). GitHub `prerelease` 플래그는 보지 않음(표시용) — 채널 구분은
    오로지 **태그 접미사**로 한다.

    260618-13: `/releases` 목록에서 **유효 SemVer 태그 중 최고 버전**을 고른다
    (`components` 등 비버전 태그·draft 는 제외). 과거 `/releases/latest` 만 쓰면 `components`
    릴리스를 나중에 올렸을 때 그게 'latest' 로 반환돼(버전=0.0.0) 업데이트를 못 찾던 문제가
    있었다. 목록 조회 실패 시 `/releases/latest` 로 폴백."""
    if not valid_repo(repo):
        return None
    repo = repo.strip()
    # 260618-32: 프리릴리즈도 포함하는 `/releases` 목록을 우선 사용(최대 100개).
    #   `/releases/latest` 는 프리릴리즈를 제외하므로, 목록 조회가 실패했을 때 거기로 곧바로
    #   떨어지면 '전부 프리릴리즈'인 저장소에서 업데이트를 못 찾는다 → 목록을 1회 재시도한 뒤,
    #   그래도 실패할 때만 `/releases/latest` 로 폴백(안정판 전용 저장소 대비).
    list_url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    data = _get_json(list_url, timeout)
    if not isinstance(data, list):
        data = _get_json(list_url, timeout)          # 일시적 실패 1회 재시도
    beta = (str(channel or "stable").lower() == "beta")
    best = None
    best_k = None
    if isinstance(data, list):
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            k = _vkey(str(rel.get("tag_name") or ""))
            if k is None:                   # 비버전 태그(components 등) 제외
                continue
            if not beta and k[1] == 0:      # stable 채널: 접미사 프리릴리즈 제외
                continue
            if best_k is None or k > best_k:
                best_k = k
                best = rel
    if best is None:                        # 최후 폴백: /releases/latest(프리릴리즈 제외 — 안정판만)
        best = _get_json(_API_LATEST.format(repo=repo), timeout)
    info = _to_info(best)
    if info is not None:
        # 261008-18(마스터 §14.5 U14): 지금 버전 다음부터 새 버전까지 **모든 버전의 설명**.
        #   여러 버전을 건너뛰어도 무엇이 바뀌는지 업데이트 창에서 볼 수 있게.
        info["changes"] = collect_changes(data if isinstance(data, list) else [best],
                                          current_version(), beta, _vkey(info.get("tag", "")))
    return info


def collect_changes(releases, current: str, beta: bool, top_key=None) -> list:
    """261008-18: `current` 보다 높고 `top_key` 이하인 버전 릴리스의 설명 — 새 버전부터(내림차순).
    채널 규칙은 check_latest 와 같다(stable 이면 접미사 프리릴리즈 제외). 각 항목:
    {version, tag, date, notes, url, pre}."""
    ck = _vkey(current or "")
    out = []
    for rel in releases or []:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        k = _vkey(tag)
        if k is None or (not beta and k[1] == 0):
            continue
        if ck is not None and k <= ck:
            continue
        if top_key is not None and k > top_key:
            continue
        out.append((k, {
            "version": tag.lstrip("vV"), "tag": tag,
            "date": str(rel.get("published_at") or rel.get("created_at") or "")[:10],
            "notes": str(rel.get("body") or ""), "url": str(rel.get("html_url") or ""),
            "pre": k[1] == 0,
        }))
    out.sort(key=lambda t: t[0], reverse=True)
    return [d for _k, d in out]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent      # 개발 실행: 패키지 상위


def download_asset(url: str, progress=None, timeout: float = 30.0, expect_sha256: str = ""):
    """릴리스 zip 다운로드. progress(done,total)->False 면 취소. 성공 시 파일경로, 실패 None.

    260628(A): ① **신뢰 호스트(GitHub)만** 허용, ② `expect_sha256` 이 주어지면
    받은 파일의 SHA-256 을 검증하고 **불일치 시 삭제 후 None**(변조·손상 차단)."""
    import urllib.request
    if not url:
        return None
    if not is_trusted_asset_url(url):
        return None
    dest_dir = tempfile.mkdtemp(prefix="polypdf_upd_")
    dest = os.path.join(dest_dir, ASSET_NAME)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    try:
                        if progress(done, total) is False:
                            return None
                    except Exception:
                        pass
        # 260628(A): 무결성 검증 — 기대 해시가 있으면 반드시 일치해야 한다.
        if expect_sha256:
            got = sha256_file(dest)
            if got != str(expect_sha256).strip().lower():
                try:
                    os.remove(dest)
                except Exception:
                    pass
                return None
        return dest
    except Exception:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except Exception:
            pass
        return None


# 260621-50: 자동 업데이트가 'Program Files'(관리자 권한 필요) 설치본을 덮어쓰지 못하고
#   실패를 catch{}로 삼켜 '설치 완료'만 띄운 뒤 옛 버전 그대로이던 치명적 버그 수정.
#   ① 설치 폴더가 쓰기 불가면 UAC로 자체 승격(RunAs)해서 적용. ② 교체 실패 건수를 세어
#   하나라도 실패하면 '완료' 대신 정직하게 오류 안내(거짓 성공 금지). ③ 승격 후 재실행은
#   explorer 경유로 일반 권한 복귀(앱이 관리자로 뜨지 않게).
_PS_INSTALLER = r'''# PolyPDF 업데이트 설치 도우미 (260621-50): 진행률 바 GUI(도스창 아님). 자체 승격 지원.
param([switch]$Elevated)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 260628: 값은 base64 로 전달 → PS 문자열 스플라이싱 인젝션( " / $(...) ) 원천 차단.
function _b64([string]$s) { if ([string]::IsNullOrEmpty($s)) { return "" } return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s)) }
$oldPid  = __PID__
$zipPath = _b64 "__ZIP_B64__"
$url     = _b64 "__URL_B64__"
$install = _b64 "__INSTALL_B64__"
$exe     = _b64 "__EXE_B64__"
$expSha  = _b64 "__SHA_B64__"     # 260628(A): 기대 SHA-256(hex). 빈 값이면 검증 생략.
$manPath = _b64 "__MANIFEST_B64__"  # 260628-12(U8): 정식 파일목록 경로. 빈 값이면 정리 생략.
# 261008-27(다국어 SOT §10.4): 화면 문구는 앱이 **실행할 때의 언어로** 채워 넘긴다(JSON, base64).
#   이 스크립트 안에서는 번역하지 않는다. 자리표시는 PowerShell -f 꼴({0}·{1}).
$T = (_b64 "__TEXT_B64__") | ConvertFrom-Json

function Test-ZipHash([string]$path, [string]$want) {
    # 260628(A): 압축 해제 **직전** 해시 검증. 승격(UAC) 인스턴스에서도 다시 수행해야
    #   한다 — zip 이 사용자 쓰기 가능 경로(%TEMP%·설정폴더)에 있어, UAC 승인 대기 중
    #   다른 프로세스가 바꿔치기하면 관리자 권한으로 그 파일이 설치되기 때문(TOCTOU/권한상승).
    if ([string]::IsNullOrEmpty($want)) { return $true }        # 해시 미게시 릴리스 → 생략
    try {
        $got = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
        return ($got -eq $want.ToLower())
    } catch { return $false }
}

function Test-DirWritable([string]$p) {
    try {
        if (-not (Test-Path $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null }
        $t = Join-Path $p ("._wtest_{0}.tmp" -f $PID)
        [System.IO.File]::WriteAllText($t, "x")
        Remove-Item -LiteralPath $t -Force -ErrorAction SilentlyContinue
        return $true
    } catch { return $false }
}
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$form = New-Object System.Windows.Forms.Form
$form.Text = $T.title_install
$form.Size = New-Object System.Drawing.Size(460,160)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false; $form.MinimizeBox = $false; $form.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.SetBounds(18,18,420,22); $lbl.Text = $T.preparing
$bar = New-Object System.Windows.Forms.ProgressBar
$bar.SetBounds(18,52,420,26); $bar.Minimum=0; $bar.Maximum=100; $bar.Value=0
$form.Controls.Add($lbl); $form.Controls.Add($bar)
$form.Show(); $form.Activate(); [System.Windows.Forms.Application]::DoEvents()

function Get-PolyPdfProcs {
    # 260628(U1): 같은 설치본($exe)으로 실행 중인 PolyPDF 프로세스 전부.
    #   Path 조회는 보호된 프로세스에서 예외가 나므로 개별 try 로 감싼다.
    $out = @()
    try {
        foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
            $pp = $null
            try { $pp = $p.Path } catch { $pp = $null }
            if ($pp -and ($pp -ieq $exe)) { $out += $p }
        }
    } catch {}
    return @($out)
}

function Get-KiwiHelperIds {
    # 261009-16(응답성 SOT §4 ③): 한국어 띄어쓰기 도우미(`PolyPDF.exe --kiwi-space-server`, 창 없음).
    #   제 부모 창이 끝나면 스스로 끝난다 — **창으로 세지 않고**, 기다리기는 함께 한다(도우미도 `_internal` 을 잠근다).
    $ids = @()
    try {
        # 261114-8(마스터 §1.1): 실행 파일 이름은 이사 판부터 PolyPinax.exe — 새·옛 이름 모두
        foreach ($c in (Get-CimInstance Win32_Process -Filter "Name='PolyPinax.exe' OR Name='PolyPDF.exe'" -ErrorAction SilentlyContinue)) {
            if ([string]$c.CommandLine -like '*--kiwi-space-server*') { $ids += [int]$c.ProcessId }
        }
    } catch {}
    return @($ids)
}

function Get-PolyPdfWindows {
    # 사용자에게 보여 줄 '다른 PolyPDF 창' — 도우미를 뺀다.
    $k = Get-KiwiHelperIds
    return @(Get-PolyPdfProcs | Where-Object { $k -notcontains $_.Id })
}

if (-not $Elevated) {
    # 1) 기존 프로그램 종료 대기 — 요청한 창(oldPid) + **동시에 열려 있는 다른 PolyPDF 창 전부**
    #    (260628/U1: 종전에는 oldPid 하나만 기다려, 다른 창이 열려 있으면 그 창이 _internal\*.pyd
    #     등을 잠근 채 설치가 진행돼 **파일 교체 실패 → 부분 설치**(구·신 혼재)가 됐다.)
    $lbl.Text = $T.wait_exit
    [System.Windows.Forms.Application]::DoEvents()
    for ($i=0; $i -lt 120; $i++) {
        $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
    }
    Start-Sleep -Milliseconds 400

    # 1.5) 다운로드(파일이 없을 때만) — 진행바만, 용량 숫자 표시 안 함
    #   261008-17(마스터 §14.5 U13): 보통은 앱이 **닫기 전에** 받아 넘긴다(이 단계는 예비).
    #   예비로 받을 때도 **다른 창을 닫기 전에** 받는다 — 받기가 실패하면 다른 창은 그대로 둔다.
    if (([string]::IsNullOrEmpty($zipPath) -or -not (Test-Path $zipPath)) -and -not [string]::IsNullOrEmpty($url)) {
        $zipPath = Join-Path $env:TEMP "polypdf_update_dl.zip"
        $lbl.Text = $T.downloading
        [System.Windows.Forms.Application]::DoEvents()
        try {
            $req = [System.Net.WebRequest]::Create($url)
            $req.UserAgent = "PolyPDF-Updater"; $req.Timeout = 60000
            $resp = $req.GetResponse(); $len = $resp.ContentLength
            $ins = $resp.GetResponseStream(); $outs = [System.IO.File]::Create($zipPath)
            $buf = New-Object byte[] 262144; $done = [long]0
            while (($r = $ins.Read($buf,0,$buf.Length)) -gt 0) {
                $outs.Write($buf,0,$r); $done += $r
                if ($len -gt 0) { $bar.Value = [Math]::Min(100,[int]($done*100/$len)) }
                [System.Windows.Forms.Application]::DoEvents()
            }
            $outs.Close(); $ins.Close(); $resp.Close()
        } catch {
            [System.Windows.Forms.MessageBox]::Show(($T.dl_failed -f $_.Exception.Message), $T.title_update) | Out-Null
            $form.Close(); Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue; exit
        }
        $bar.Value = 0
    }

    # 1.2) 다른 창: **정상 종료 요청 먼저**(U2) — 각 창에서 저장 확인창이 정상 동작하게.
    #   261009-16: 기다리기는 **모든** PolyPDF 프로세스로, 보여 주는 수·닫기 요청은 창만(띄어쓰기 도우미 제외).
    $others = Get-PolyPdfProcs
    if ($others.Count -gt 0) {
        $wins = Get-PolyPdfWindows
        if ($wins.Count -gt 0) { $lbl.Text = ($T.closing_others -f $wins.Count) } else { $lbl.Text = $T.waiting_others_plain }
        [System.Windows.Forms.Application]::DoEvents()
        foreach ($p in $wins) { try { $p.CloseMainWindow() | Out-Null } catch {} }
        for ($i=0; $i -lt 120; $i++) {          # 최대 60초 대기(저장 여부 응답 시간 포함)
            $others = Get-PolyPdfProcs
            if ($others.Count -eq 0) { break }
            $n = (Get-PolyPdfWindows).Count
            if ($n -gt 0) { $lbl.Text = ($T.waiting_others -f $n) } else { $lbl.Text = $T.waiting_others_plain }
            Start-Sleep -Milliseconds 500
            [System.Windows.Forms.Application]::DoEvents()
        }
    }
    # 1.3) 그래도 남으면 **강제 종료 여부를 사용자에게 질문**(U2 — 묻지 않고 Kill 금지).
    #   261009-16: 도우미만 남았으면 묻지 않는다 — 사용자 자료가 없는 창 없는 프로세스다.
    $others = Get-PolyPdfProcs
    if ($others.Count -gt 0) {
        $wins = Get-PolyPdfWindows
        if ($wins.Count -gt 0) {
            $ans = [System.Windows.Forms.MessageBox]::Show(
                ($T.others_left -f $wins.Count),
                $T.title_update, [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning)
            if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) {
                $form.Close()
                Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
                exit
            }
        }
        $lbl.Text = $T.closing_left; [System.Windows.Forms.Application]::DoEvents()
        foreach ($p in (Get-PolyPdfProcs)) { try { $p.Kill() } catch {} }
        Start-Sleep -Milliseconds 900
    }

    # 1.7) 설치 폴더가 쓰기 불가(예: Program Files)면 UAC로 자체 승격해서 적용
    # 261011-3(§14.5 U20): 승격 PowerShell 은 Start-Process 에도 -WindowStyle Hidden — 인자로만 주면 콘솔을 만든 뒤에
    #   숨겨 파란 콘솔이 잠깐 보였다. Start-Process 쪽은 처음부터 숨긴 창으로 만든다(ShellExecute nShow).
    # 260902-2: 루트만 검사하면 놓친다 — 옛 설치본(0.43 등)은 루트는 쓸 수 있는데 `_internal`
    #   아래 일부 폴더(setuptools 등)가 관리자 소유라, 압축 해제 중 '액세스 거부'로 실패했다.
    #   → `_internal` 과 그 안의 첫 하위 폴더 몇 개까지 같이 검사한다.
    $needElevate = -not (Test-DirWritable $install)
    if (-not $needElevate) {
        $intl = Join-Path $install "_internal"
        if (Test-Path $intl) {
            if (-not (Test-DirWritable $intl)) { $needElevate = $true }
            else {
                foreach ($sd in (Get-ChildItem -LiteralPath $intl -Directory -Force -ErrorAction SilentlyContinue | Select-Object -First 40)) {
                    if (-not (Test-DirWritable $sd.FullName)) { $needElevate = $true; break }
                }
            }
        }
    }
    if ($needElevate -and -not $isAdmin) {
        $lbl.Text = $T.elevating; [System.Windows.Forms.Application]::DoEvents()
        try {
            Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @(
                '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
                '-File', $PSCommandPath, '-Elevated') | Out-Null
            # 승격 인스턴스가 압축 해제·재실행·정리(.ps1 삭제)를 담당. 이 인스턴스는 종료.
            $form.Close(); exit
        } catch {
            [System.Windows.Forms.MessageBox]::Show($T.elevate_cancel, $T.title_update) | Out-Null
            $form.Close(); Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue; exit
        }
    }
} else {
    # 승격 인스턴스: 부모가 이미 종료대기·다운로드를 마침. zip 경로 보정.
    if ([string]::IsNullOrEmpty($zipPath) -or -not (Test-Path $zipPath)) {
        $zipPath = Join-Path $env:TEMP "polypdf_update_dl.zip"
    }
    # 260628(U1): 승격 사이에 창이 다시 떴을 수 있으므로 잔여 인스턴스를 짧게 대기.
    #   (여기서 강제 종료는 하지 않는다 — 남으면 U3 실패 카운트로 정직하게 보고됨.)
    for ($i=0; $i -lt 20; $i++) {
        if ((Get-PolyPdfProcs).Count -eq 0) { break }
        $lbl.Text = $T.waiting_others_plain
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
    }
    Start-Sleep -Milliseconds 300
}

# 2) 압축 해제 = 설치(엔트리별 진행률). 압축 루트에 PolyPDF\ 접두가 있으면 제거.
# 260628(A): ★ 해제 직전 무결성 재검증(승격 인스턴스 포함) — 실패 시 설치 중단.
if (-not (Test-ZipHash $zipPath $expSha)) {
    [System.Windows.Forms.MessageBox]::Show(
        $T.bad_hash,
        $T.title_update, [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    try { Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue } catch {}
    $form.Close()
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    exit
}
$fail = 0
$denied = $false
try {
    $arc = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $total = [Math]::Max(1, $arc.Entries.Count); $n = 0
    foreach ($e in $arc.Entries) {
        $rel = $e.FullName.Replace('/', '\')
        if ($rel -like 'PolyPinax\*') { $rel = $rel.Substring(10) }      # 261114-8: 맨 위 폴더 — 새·옛 이름 모두
        elseif ($rel -like 'PolyPDF\*') { $rel = $rel.Substring(8) }
        $n++
        if (-not [string]::IsNullOrEmpty($rel)) {
            $dest = Join-Path $install $rel
            # 260628: zip-slip 방어 — 설치 폴더 밖으로 벗어나는 엔트리는 건너뜀.
            $installFull = [IO.Path]::GetFullPath($install).TrimEnd('\') + '\'
            $destFull = [IO.Path]::GetFullPath($dest)
            if (-not $destFull.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) { $fail++; continue }
            # 260902-2: 폴더 생성이 '액세스 거부'로 터지면 종전엔 바깥 catch 로 빠져 **설치가
            #   통째로 중단**됐다('setuptools' 경로에 대한 액세스가 거부되었습니다). 개별 실패로
            #   세고 계속 진행하되, 거부가 한 번이라도 있으면 $denied 를 켜 승격 재시도로 넘긴다.
            if ([string]::IsNullOrEmpty($e.Name)) {
                try { if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null } }
                catch { $fail++; if ($_.Exception -is [System.UnauthorizedAccessException] -or $_.Exception.InnerException -is [System.UnauthorizedAccessException]) { $denied = $true } }
            } else {
                $dir = Split-Path $dest -Parent
                try {
                    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
                    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
                } catch {
                    $fail++
                    if ($_.Exception -is [System.UnauthorizedAccessException] -or $_.Exception.InnerException -is [System.UnauthorizedAccessException]) { $denied = $true }
                }
            }
        }
        $bar.Value = [Math]::Min(100, [int]($n * 100 / $total))
        if (($n % 15) -eq 0) { $lbl.Text = ($T.installing -f $n, $total); [System.Windows.Forms.Application]::DoEvents() }
    }
    $arc.Dispose()
} catch {
    $fail = -1
    [System.Windows.Forms.MessageBox]::Show(($T.apply_error -f $_.Exception.Message), $T.title_update) | Out-Null
}

# ── 260628-12 (U8): 잔존 파일 정리 ────────────────────────────────────────
#   업데이트는 '덮어쓰기 전용'이라, 새 버전에서 없어진 파일이 설치 폴더에 영구히 남는다.
#   특히 _internal 의 옛 .pyd/.dll 은 새 것과 공존하다 로드 순서에 따라 '깨끗한 설치에선
#   되는데 업데이트한 기기에서만 깨지는' 증상을 만든다.
#   → 릴리스가 제공한 **정식 파일목록(manifest)** 에 없는 파일만 지운다.
#
#   ★ 안전장치 — 하나라도 어긋나면 **정리를 통째로 건너뛴다**(업데이트 자체는 성공 처리).
#     a) manifest 가 없거나 못 읽으면 생략 — 옛 릴리스로의 업데이트에서 오작동 금지
#     b) 항목이 500개 미만이면 생략 — 잘린 목록으로 대량 삭제하는 사고 방지
#     c) 삭제 대상이 전체의 40% 를 넘으면 생략 — 목록이 엉뚱할 때의 최후 방어
#     d) 실행 중인 exe 는 절대 대상에서 제외
#     e) 개별 삭제 실패는 무시(권한 등) — 업데이트를 실패로 만들지 않는다
#     f) **`_internal\` 아래만** 지운다(261008-27, 다국어 SOT §10.3) — 설치 폴더 바로 아래의
#        제거 프로그램(unins000.*)·사용 안내는 설치 프로그램 소유라 매니페스트에 없다. 종전에는 이것까지
#        지워, 다음 설치 파일이 '기존 버전 제거를 실행하지 못했습니다' 로 멈췄다.
if ($fail -eq 0 -and -not [string]::IsNullOrEmpty($manPath) -and (Test-Path $manPath)) {
    try {
        $lbl.Text = $T.cleaning; [System.Windows.Forms.Application]::DoEvents()
        $keep = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($ln in [IO.File]::ReadAllLines($manPath)) {
            $t = $ln.Trim().TrimStart('.').TrimStart('\','/')
            if ($t) { [void]$keep.Add(($t -replace '/', '\')) }
        }
        if ($keep.Count -lt 500) { throw 'manifest too small' }        # (b)
        $root = [IO.Path]::GetFullPath($install).TrimEnd('\') + '\'
        $all = @(Get-ChildItem -LiteralPath $install -Recurse -File -Force -ErrorAction SilentlyContinue)
        $stale = @()
        foreach ($f in $all) {
            $rel = $f.FullName.Substring($root.Length)
            if ($keep.Contains($rel)) { continue }
            if (-not $rel.StartsWith('_internal\', [StringComparison]::OrdinalIgnoreCase)) { continue }   # (f)
            if ($f.FullName -ieq $exe) { continue }                    # (d)
            $stale += $f.FullName
        }
        if ($all.Count -gt 0 -and ($stale.Count / $all.Count) -gt 0.40) { throw 'too many stale' }  # (c)
        $removed = 0
        foreach ($p in $stale) {
            try { Remove-Item -LiteralPath $p -Force -ErrorAction Stop; $removed++ } catch { }   # (e)
        }
        # 빈 폴더 정리(실패 무시)
        foreach ($d in (Get-ChildItem -LiteralPath $install -Recurse -Directory -Force -ErrorAction SilentlyContinue |
                        Sort-Object { $_.FullName.Length } -Descending)) {
            try {
                if (-not (Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue)) {
                    Remove-Item -LiteralPath $d.FullName -Force -ErrorAction Stop
                }
            } catch { }
        }
        [IO.File]::AppendAllText("$env:TEMP\polypdf_update_cleanup.log",
            ("{0}  manifest={1} files={2} stale={3} removed={4}`r`n" -f (Get-Date -Format s), $keep.Count, $all.Count, $stale.Count, $removed))
    } catch {
        [IO.File]::AppendAllText("$env:TEMP\polypdf_update_cleanup.log",
            ("{0}  cleanup skipped: {1}`r`n" -f (Get-Date -Format s), $_.Exception.Message))
    }
}

# 260902-2: 사전 검사를 통과했는데도 해제 중 '액세스 거부'가 났으면(깊은 폴더가 관리자
#   소유 등) 여기서 UAC 승격으로 **한 번 더** 적용한다. 같은 zip 을 덮어쓰므로 안전하고,
#   승격 인스턴스가 재실행·정리를 맡는다. 승격 후에도 실패하면 아래 정직한 오류 안내.
if ($fail -gt 0 -and $denied -and -not $Elevated -and -not $isAdmin) {
    $lbl.Text = $T.reelevate
    [System.Windows.Forms.Application]::DoEvents()
    try {
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @(
            '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
            '-File', $PSCommandPath, '-Elevated') | Out-Null
        $form.Close(); exit
    } catch {
        [System.Windows.Forms.MessageBox]::Show(($T.reelevate_cancel -f $fail), $T.title_update) | Out-Null
        $form.Close(); Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue; exit
    }
}

if ($fail -eq 0) {
    # 261010-14(마스터 §14.5): 아이콘 캐시 새로 고침 — 앱 안 업데이트로 exe 를 바꾸면 작업 표시줄·바로가기에
    #   빈 페이지 아이콘이 남았다(설치 프로그램은 끝에 같은 일을 한다, PolyPDF.iss [Run]).
    try {
        $ie = Join-Path $env:WINDIR 'System32\ie4uinit.exe'
        if (Test-Path $ie) { Start-Process -FilePath $ie -ArgumentList '-show' -WindowStyle Hidden }
    } catch {}
    # 261010-15(마스터 §14.5): 설치 정보(제어판 '프로그램 추가/제거')의 버전도 새 판으로 — 앱 안 업데이트는 파일만 바꿔
    #   설치 정보가 옛 판으로 남았다(설치 시험: 설치 정보 beta.223 · 앱 파일 beta.228). 판 번호는 **방금 깐 파일**에서 읽고,
    #   설치 위치가 같은 항목만 고친다(휴대용 판은 항목이 없어 건드리지 않는다).
    try {
        $vf = Join-Path $install '_internal\viewer\__init__.py'
        $m = [regex]::Match([IO.File]::ReadAllText($vf), '__version__\s*=\s*"([^"]+)"')
        if ($m.Success) {
            $nv = $m.Groups[1].Value
            $want = [IO.Path]::GetFullPath($install).TrimEnd('\')
            foreach ($root in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                                'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')) {
                foreach ($k in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
                    $p = Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue
                    # 261114-6(마스터 §1.1): 보이는 이름이 PolyPinax 로 — 옛 이름(PolyPDF v…)도 찾아 새 이름으로 쓴다
                    if ($p -and ($p.DisplayName -like 'PolyPinax*' -or $p.DisplayName -like 'PolyPDF*') -and $p.InstallLocation -and
                        ([IO.Path]::GetFullPath($p.InstallLocation).TrimEnd('\') -ieq $want)) {
                        Set-ItemProperty -LiteralPath $k.PSPath -Name DisplayVersion -Value $nv -ErrorAction SilentlyContinue
                        Set-ItemProperty -LiteralPath $k.PSPath -Name DisplayName -Value ('PolyPinax v' + $nv) -ErrorAction SilentlyContinue
                    }
                }
            }
        }
    } catch {}
    $bar.Value = 100; $lbl.Text = $T.done
    [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 700
} elseif ($fail -gt 0) {
    # 거짓 성공 금지: 일부 파일 교체 실패(권한 등)를 정직하게 알림.
    [System.Windows.Forms.MessageBox]::Show(($T.partial_fail -f $fail), $T.title_update) | Out-Null
}

# 3) 재실행 + 정리. 승격 상태면 explorer 경유로 일반 권한으로 복귀 실행.
try {
    if ($Elevated -or $isAdmin) { Start-Process "explorer.exe" -ArgumentList ('"' + $exe + '"') }
    else { Start-Process -FilePath $exe }
} catch {}
$form.Close()
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
'''


def pending_zip_path() -> Path:
    """260618-24: 백그라운드로 미리 받아둔 업데이트 zip 경로(설정 폴더)."""
    try:
        from viewer import settings_store
        d = settings_store.settings_dir()
    except Exception:
        d = Path(tempfile.gettempdir())
    return Path(d) / "PolyPDF-update.zip"


def installer_texts() -> dict:
    """261008-27(다국어 SOT §10.4): 설치 도우미(`_PS_INSTALLER`)의 화면 문구 — **지금 화면 언어로**.
    자리표시 `{n}`·`{msg}` 등을 PowerShell `-f` 꼴(`{0}`·`{1}`)로 바꿔 넘긴다."""

    def ps(text: str, *names) -> str:
        for i, nm in enumerate(names):
            text = text.replace("{%s}" % nm, "{%d}" % i)
        return text
    setup = _br.SETUP_PREFIX + "*.exe"          # 261114-8: 설치 파일 이름(이사 스위치) — 문구에는 {setup} 자리
    return {
        "title_install": tr("PolyPinax 업데이트 설치"),
        "title_update": tr("PolyPinax 업데이트"),
        "preparing": tr("업데이트를 준비하는 중..."),
        "wait_exit": tr("기존 프로그램이 종료되기를 기다리는 중..."),
        "downloading": tr("업데이트 다운로드 중..."),
        "dl_failed": ps(tr("다운로드 실패: {msg}"), "msg"),
        "closing_others": ps(tr("다른 PolyPinax 창을 닫는 중... ({n}개)"), "n"),
        "waiting_others": ps(tr("다른 PolyPinax 창이 닫히기를 기다리는 중... ({n}개 남음)"), "n"),
        "waiting_others_plain": tr("다른 PolyPinax 창이 닫히기를 기다리는 중..."),
        "others_left": ps(tr("다른 PolyPinax 창 {n}개가 아직 열려 있습니다.\n"
                             "열린 창이 파일을 잠그고 있어, 이대로 진행하면 일부 파일이 교체되지 않아 "
                             "업데이트가 실패합니다.\n\n"
                             "[예] 남은 창을 강제로 닫고 계속\n"
                             "[아니오] 업데이트 취소 (저장하지 않은 작업이 있으면 이쪽을 선택하세요)"), "n"),
        "closing_left": tr("남은 창을 닫는 중..."),
        "elevating": tr("관리자 권한으로 업데이트를 적용합니다..."),
        "elevate_cancel": tr("업데이트 적용에는 관리자 권한이 필요합니다. 권한 요청이 취소되어 업데이트하지 못했습니다.\n"
                             "최신 설치본({setup})을 받아 '관리자 권한으로 실행'해 주세요.").replace("{setup}", setup),
        "bad_hash": tr("업데이트 파일이 손상되었거나 변조되었습니다(무결성 검증 실패).\n"
                       "안전을 위해 설치를 중단했습니다.\n\n"
                       "잠시 후 다시 시도하거나, 공식 릴리스에서 설치본을 내려받아 주세요."),
        "installing": ps(tr("설치 중... ({done} / {total})"), "done", "total"),
        "apply_error": ps(tr("업데이트 적용 중 오류가 발생했습니다.\n{msg}"), "msg"),
        "cleaning": tr("정리 중..."),
        "reelevate": tr("일부 폴더에 권한이 없어 관리자 권한으로 다시 적용합니다..."),
        "reelevate_cancel": ps(tr("일부 폴더에 쓰기 권한이 없어 업데이트를 마치지 못했습니다({n}개). "
                                  "관리자 권한 요청이 취소되었습니다.\n"
                                  "최신 설치본({setup})을 받아 '관리자 권한으로 실행'해 주세요.").replace("{setup}", setup), "n"),
        "done": tr("설치 완료 — 프로그램을 다시 시작합니다."),
        "partial_fail": ps(tr("업데이트를 완료하지 못했습니다. {n}개 파일을 교체하지 못했습니다(권한 문제일 수 있음).\n"
                              "최신 설치본({setup})을 '관리자 권한으로 실행'해 주세요.").replace("{setup}", setup), "n"),
    }


def apply_update(zip_path: str = None, url: str = "", sha256: str = "",
                 manifest_path: str = "") -> bool:
    """260618-17/24: 실행 중 교체 — **진행률 바 GUI 설치 창**(PowerShell WinForms, 콘솔 숨김).
    앱 종료 대기 → (zip 없으면 url 에서 다운로드, 진행바만) → 압축 해제(설치) → 재실행.
    성공 시 True(설치 도우미 기동) 반환 후 호출측이 앱을 종료해야 함. zip_path/url 중 하나는 있어야 함."""
    has_zip = bool(zip_path and os.path.isfile(zip_path))
    if not has_zip and not url:
        return False
    # 260628(A): 도우미가 직접 받는 경우도 신뢰 호스트만.
    if url and not is_trusted_asset_url(url):
        return False
    inst = str(install_dir())
    exe = sys.executable if is_frozen() else os.path.join(inst, _br.EXE_NAME)
    pid = os.getpid()
    ps1 = os.path.join(tempfile.gettempdir(), f"polypdf_update_{pid}.ps1")

    def _b64(s: str) -> str:
        import base64
        return base64.b64encode((s or "").encode("utf-8")).decode("ascii")

    script = (_PS_INSTALLER
              .replace("__PID__", str(pid))
              .replace("__ZIP_B64__", _b64(zip_path if has_zip else ""))
              .replace("__URL_B64__", _b64(url or ""))
              .replace("__INSTALL_B64__", _b64(inst))
              .replace("__EXE_B64__", _b64(exe))
              .replace("__SHA_B64__", _b64(str(sha256 or "").strip().lower()))
              # 260628-12(U8): 정식 파일목록. 없으면 빈 값 → 정리 생략(안전).
              .replace("__MANIFEST_B64__", _b64(manifest_path if (manifest_path and
                                                os.path.isfile(manifest_path)) else ""))
              .replace("__TEXT_B64__", _b64(json.dumps(installer_texts(), ensure_ascii=False))))
    try:
        # PS5.1 이 한글을 정확히 읽도록 UTF-8 BOM 으로 기록
        with open(ps1, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(script)
        # 콘솔 숨김(WinForms 진행창만 표시). 시스템 powershell.exe 사용.
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", ps1],
            creationflags=CREATE_NO_WINDOW, close_fds=True)
        return True
    except Exception:
        return False


# ── 261108-13(릴리스 SOT §14.5 U24): 설치본으로 올리기 ────────────────────────────────────────────
#   설치 프로그램으로 깐 PolyPDF 는 앱 안 업데이트도 **받은 설치본(`PolyPDF-Setup-v<판>.exe`)을 조용히 실행**한다.
#   종전 길(%TEMP% 의 .ps1 을 `powershell -ExecutionPolicy Bypass -WindowStyle Hidden` 으로 — 그 안에서 RunAs 권한 올리기·
#   다른 PolyPDF 강제 종료·Program Files 에 zip 풀기·HKLM 고치기·스스로 지우기)은 백신 휴리스틱에 가장 걸리는 모양이었다
#   (기획 '백신 오인·멈춤 줄이기' F3). 설치본은 이 일을 이미 한다 — 권한(PrivilegesRequired=admin)·옛 판 제거 뒤 설치·
#   Uninstall 키·PolyPDF 언어 유지(다국어 SOT §10.2)·아이콘 캐시. 휴대용(zip) 판과 설치본 자산·해시가 없는 릴리스는 종전 zip 길.

INNO_APP_ID = "{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F}"      # installer/PolyPDF.iss [Setup] AppId
SETUP_LOG_NAME = "polypdf_update_setup.log"


def _norm_dir(p) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")
    except Exception:
        return ""


def setup_install_location() -> str:
    """설치 프로그램이 남긴 Uninstall 항목의 설치 폴더(HKLM 64·32 보기, HKCU). 없으면 ''."""
    if os.name != "nt":
        return ""
    import winreg
    sub = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s_is1" % INNO_APP_ID
    for root, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                       (winreg.HKEY_CURRENT_USER, 0)):
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view) as k:
                for name in ("InstallLocation", "Inno Setup: App Path"):
                    try:
                        v = str(winreg.QueryValueEx(k, name)[0] or "")
                    except OSError:
                        v = ""
                    if v:
                        return v
        except OSError:
            continue
    return ""


def installed_by_setup(inst=None) -> bool:
    """이 실행본이 설치 프로그램으로 깐 것인가 — Uninstall 항목의 설치 폴더 = 이 폴더, 휴대용 표식 없음."""
    inst = Path(inst) if inst else install_dir()
    try:
        from viewer.settings_store import has_portable_marker
        if has_portable_marker(inst):                          # 261114-8: 새·옛 표식 모두
            return False
    except Exception:
        if (inst / "PolyPDF.portable").exists():
            return False
    loc = setup_install_location()
    return bool(loc) and _norm_dir(loc) == _norm_dir(inst)


def update_kind(info: dict, inst=None) -> str:
    """'setup'(설치본 조용히 실행) 또는 'zip'(종전 설치 도우미). 설치본·그 해시가 모두 있고 설치본으로 깐 경우만 'setup'."""
    info = info or {}
    if info.get("setup_url") and info.get("setup_sha_url") and installed_by_setup(inst):
        return "setup"
    return "zip"


def pending_path(kind: str) -> Path:
    """미리 받아 둘 파일 — zip 은 종전 이름, 설치본은 `.exe` 로 끝나야 실행된다."""
    z = pending_zip_path()
    return z if kind != "setup" else z.with_name("PolyPDF-update-setup.exe")


def cleanup_pending(current: str = "") -> int:
    """지금 판보다 새롭지 않은 받아 둔 업데이트(zip·설치본과 곁 파일)를 지운다 — 설치본은 340MB 라 남기지 않는다.
    배경 스레드에서 부른다(파일 지우기 — 응답성 SOT). 지운 파일 수."""
    cur = current or current_version()
    n = 0
    for kind in ("zip", "setup"):
        p = pending_path(kind)
        verf = p.with_suffix(".ver")
        try:
            ver = verf.read_text(encoding="utf-8").strip() if verf.is_file() else ""
        except Exception:
            continue
        if not ver or is_newer(ver, cur):
            continue
        for f in (p, verf, p.with_suffix(".sha256")):
            try:
                if f.is_file():
                    f.unlink()
                    n += 1
            except Exception:
                pass
    return n


def setup_args(lang: str = "", pid: int = 0, log_path: str = "") -> list:
    """설치본 명령줄(installer/PolyPDF.iss 가 읽는 인자).
    /SILENT — 마법사 쪽은 없이 진행 창만(설치 중임이 보이고, 오류는 상자로 — 'VERYSILENT+SUPPRESSMSGBOXES' 는 실패해도 아무것도 안 보여
    앱이 닫힌 채 끝난 까닭을 알 수 없다, U3 거짓 성공 금지). /WAITPID — 이 앱이 끝날 때까지 기다린 뒤 남은 PolyPDF 를 닫는다.
    /RELAUNCH=1 — 설치가 끝나면 원래 사용자 권한으로 다시 띄운다. /APPLANG — 지금 화면 언어 유지(다국어 SOT §10.2)."""
    args = ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]
    if pid:
        args.append("/WAITPID=%d" % int(pid))
    lang = str(lang or "").strip()
    if lang and re.fullmatch(r"[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})?", lang):
        args.append("/APPLANG=" + lang)
    if log_path:
        args.append('/LOG=' + str(log_path))
    return args


def other_windows(exe: str = "") -> dict:
    """같은 실행 파일로 뜬 **다른** PolyPDF 의 주 창 {pid: [hwnd…]} — 보이는, 주인 없는 최상위 창만
    (창 없는 띄어쓰기 도우미 `--kiwi-space-server` 는 들지 않는다 — U2). U1·U2 를 설치본 길에서는 앱이 맡는다."""
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes as wt
    exe = _norm_dir(exe or sys.executable)
    me = os.getpid()
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    u32.GetWindow.restype = wt.HWND
    u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    found: dict = {}
    paths: dict = {}

    def image(pid):
        if pid not in paths:
            p = ""
            h = k32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                n = wt.DWORD(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    p = _norm_dir(buf.value)
                k32.CloseHandle(h)
            paths[pid] = p
        return paths[pid]

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        try:
            if u32.IsWindowVisible(hwnd) and not u32.GetWindow(hwnd, 4):     # GW_OWNER
                pid = wt.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and pid.value != me and image(pid.value) == exe:
                    found.setdefault(pid.value, []).append(hwnd)
        except Exception:
            pass
        return True
    u32.EnumWindows(cb, 0)
    return found


def request_close(wins: dict) -> None:
    """각 창에 정상 종료 요청(WM_CLOSE — PowerShell `CloseMainWindow` 과 같은 일). 저장 확인은 그 창이 묻는다."""
    if os.name != "nt":
        return
    import ctypes
    u32 = ctypes.WinDLL("user32")
    for hwnds in (wins or {}).values():
        for h in hwnds:
            try:
                u32.PostMessageW(h, 0x0010, 0, 0)                # WM_CLOSE
            except Exception:
                pass


def _launch_setup(path: str, args: list) -> None:
    """ShellExecute 로 띄운다 — 설치본이 관리자 권한을 요구해도(UAC) CreateProcess 처럼 740 으로 실패하지 않는다."""
    os.startfile(path, "open", subprocess.list2cmdline(args))      # noqa: S606 — 해시를 맞춘 설치본만


def apply_setup(setup_path: str, sha256: str, lang: str = "") -> bool:
    """받은 설치본을 **실행 직전에 다시 해시 확인**하고 조용히 실행한다(U7 의 ② 와 같은 자리). 성공이면 True — 호출측이 앱을 닫는다.
    해시가 없거나 다르면 실행하지 않는다(해시 없는 설치본은 관리자 권한으로 돌리지 않는다)."""
    want = str(sha256 or "").strip().lower()
    if not (setup_path and os.path.isfile(setup_path) and len(want) == 64):
        return False
    if sha256_file(setup_path) != want:
        try:
            os.remove(setup_path)
        except Exception:
            pass
        return False
    log = os.path.join(tempfile.gettempdir(), SETUP_LOG_NAME)
    try:
        _launch_setup(setup_path, setup_args(lang, os.getpid(), log))
        return True
    except Exception:
        return False
