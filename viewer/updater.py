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
import urllib.request
from pathlib import Path

ASSET_NAME = "PolyPDF-windows.zip"
# 260618-11: 기본 업데이트 저장소(설정 update_repo 가 비어 있으면 이 값 사용 — 입력 불필요).
DEFAULT_REPO = "kdjeong777-ops/PolyPDF"
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
        return (1 if "update" in n else 0, 1 if "win" in n else 0)
    pick = max(zips, key=_score) if zips else None
    asset_url = pick.get("browser_download_url") if pick else None
    asset_name = str(pick.get("name") or "") if pick else ""
    # 260628(A): 신뢰 호스트가 아니면 자산을 버린다(업데이트 미제공 = 안전한 실패).
    if asset_url and not is_trusted_asset_url(asset_url):
        asset_url, asset_name = None, ""
    # 260628(A): 같은 릴리스의 '<자산명>.sha256' 무결성 파일(있으면).
    sha_url = ""
    if asset_name:
        want = (asset_name + ".sha256").lower()
        for a in assets:
            if str(a.get("name") or "").lower() == want:
                u = a.get("browser_download_url")
                if is_trusted_asset_url(u):
                    sha_url = u
                break
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "notes": str(rel.get("body") or ""),
        "asset_url": asset_url,
        "asset_name": asset_name,
        "sha_url": sha_url,
        "html_url": str(rel.get("html_url") or ""),
    }


def fetch_expected_sha256(info: dict, timeout: float = 10.0) -> str:
    """릴리스의 `<자산명>.sha256` 을 읽어 기대 해시(소문자 hex) 반환. 없으면 ''.

    파일 형식은 `sha256sum` 관례(`<hex>  <파일명>`)와 hex 단독 모두 허용."""
    url = (info or {}).get("sha_url") or ""
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
    return _to_info(best)


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
$form.Text = "PolyPDF 업데이트 설치"
$form.Size = New-Object System.Drawing.Size(460,160)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false; $form.MinimizeBox = $false; $form.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.SetBounds(18,18,420,22); $lbl.Text = "업데이트를 준비하는 중..."
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

if (-not $Elevated) {
    # 1) 기존 프로그램 종료 대기 — 요청한 창(oldPid) + **동시에 열려 있는 다른 PolyPDF 창 전부**
    #    (260628/U1: 종전에는 oldPid 하나만 기다려, 다른 창이 열려 있으면 그 창이 _internal\*.pyd
    #     등을 잠근 채 설치가 진행돼 **파일 교체 실패 → 부분 설치**(구·신 혼재)가 됐다.)
    $lbl.Text = "기존 프로그램이 종료되기를 기다리는 중..."
    [System.Windows.Forms.Application]::DoEvents()
    for ($i=0; $i -lt 120; $i++) {
        $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
    }
    Start-Sleep -Milliseconds 400

    # 1.2) 다른 창: **정상 종료 요청 먼저**(U2) — 각 창에서 저장 확인창이 정상 동작하게.
    $others = Get-PolyPdfProcs
    if ($others.Count -gt 0) {
        $lbl.Text = "다른 PolyPDF 창을 닫는 중... ($($others.Count)개)"
        [System.Windows.Forms.Application]::DoEvents()
        foreach ($p in $others) { try { $p.CloseMainWindow() | Out-Null } catch {} }
        for ($i=0; $i -lt 120; $i++) {          # 최대 60초 대기(저장 여부 응답 시간 포함)
            $others = Get-PolyPdfProcs
            if ($others.Count -eq 0) { break }
            $lbl.Text = "다른 PolyPDF 창이 닫히기를 기다리는 중... ($($others.Count)개 남음)"
            Start-Sleep -Milliseconds 500
            [System.Windows.Forms.Application]::DoEvents()
        }
    }
    # 1.3) 그래도 남으면 **강제 종료 여부를 사용자에게 질문**(U2 — 묻지 않고 Kill 금지).
    $others = Get-PolyPdfProcs
    if ($others.Count -gt 0) {
        $ans = [System.Windows.Forms.MessageBox]::Show(
            "다른 PolyPDF 창 $($others.Count)개가 아직 열려 있습니다.`n" +
            "열린 창이 파일을 잠그고 있어, 이대로 진행하면 일부 파일이 교체되지 않아" +
            " 업데이트가 실패합니다.`n`n" +
            "[예] 남은 창을 강제로 닫고 계속`n" +
            "[아니오] 업데이트 취소 (저장하지 않은 작업이 있으면 이쪽을 선택하세요)",
            "PolyPDF 업데이트", [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning)
        if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) {
            $form.Close()
            Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
            exit
        }
        $lbl.Text = "남은 창을 닫는 중..."; [System.Windows.Forms.Application]::DoEvents()
        foreach ($p in (Get-PolyPdfProcs)) { try { $p.Kill() } catch {} }
        Start-Sleep -Milliseconds 900
    }

    # 1.5) 다운로드(파일이 없을 때만) — 진행바만, 용량 숫자 표시 안 함
    if (([string]::IsNullOrEmpty($zipPath) -or -not (Test-Path $zipPath)) -and -not [string]::IsNullOrEmpty($url)) {
        $zipPath = Join-Path $env:TEMP "polypdf_update_dl.zip"
        $lbl.Text = "업데이트 다운로드 중..."
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
            [System.Windows.Forms.MessageBox]::Show("다운로드 실패: " + $_.Exception.Message, "PolyPDF 업데이트") | Out-Null
            $form.Close(); Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue; exit
        }
        $bar.Value = 0
    }

    # 1.7) 설치 폴더가 쓰기 불가(예: Program Files)면 UAC로 자체 승격해서 적용
    if (-not (Test-DirWritable $install) -and -not $isAdmin) {
        $lbl.Text = "관리자 권한으로 업데이트를 적용합니다..."; [System.Windows.Forms.Application]::DoEvents()
        try {
            Start-Process powershell.exe -Verb RunAs -ArgumentList @(
                '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
                '-File', $PSCommandPath, '-Elevated') | Out-Null
            # 승격 인스턴스가 압축 해제·재실행·정리(.ps1 삭제)를 담당. 이 인스턴스는 종료.
            $form.Close(); exit
        } catch {
            [System.Windows.Forms.MessageBox]::Show(
                "업데이트 적용에는 관리자 권한이 필요합니다. 권한 요청이 취소되어 업데이트하지 못했습니다.`n" +
                "최신 설치본(PolyPDF-Setup-*.exe)을 받아 '관리자 권한으로 실행'해 주세요.",
                "PolyPDF 업데이트") | Out-Null
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
        $lbl.Text = "다른 PolyPDF 창이 닫히기를 기다리는 중..."
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
    }
    Start-Sleep -Milliseconds 300
}

# 2) 압축 해제 = 설치(엔트리별 진행률). 압축 루트에 PolyPDF\ 접두가 있으면 제거.
# 260628(A): ★ 해제 직전 무결성 재검증(승격 인스턴스 포함) — 실패 시 설치 중단.
if (-not (Test-ZipHash $zipPath $expSha)) {
    [System.Windows.Forms.MessageBox]::Show(
        "업데이트 파일이 손상되었거나 변조되었습니다(무결성 검증 실패).`n" +
        "안전을 위해 설치를 중단했습니다.`n`n" +
        "잠시 후 다시 시도하거나, 공식 릴리스에서 설치본을 내려받아 주세요.",
        "PolyPDF 업데이트", [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    try { Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue } catch {}
    $form.Close()
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    exit
}
$fail = 0
try {
    $arc = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $total = [Math]::Max(1, $arc.Entries.Count); $n = 0
    foreach ($e in $arc.Entries) {
        $rel = $e.FullName.Replace('/', '\')
        if ($rel -like 'PolyPDF\*') { $rel = $rel.Substring(8) }
        $n++
        if (-not [string]::IsNullOrEmpty($rel)) {
            $dest = Join-Path $install $rel
            # 260628: zip-slip 방어 — 설치 폴더 밖으로 벗어나는 엔트리는 건너뜀.
            $installFull = [IO.Path]::GetFullPath($install).TrimEnd('\') + '\'
            $destFull = [IO.Path]::GetFullPath($dest)
            if (-not $destFull.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) { $fail++; continue }
            if ([string]::IsNullOrEmpty($e.Name)) {
                if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }
            } else {
                $dir = Split-Path $dest -Parent
                if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
                try { [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true) }
                catch { $fail++ }
            }
        }
        $bar.Value = [Math]::Min(100, [int]($n * 100 / $total))
        if (($n % 15) -eq 0) { $lbl.Text = "설치 중... ($n / $total)"; [System.Windows.Forms.Application]::DoEvents() }
    }
    $arc.Dispose()
} catch {
    $fail = -1
    [System.Windows.Forms.MessageBox]::Show("업데이트 적용 중 오류가 발생했습니다.`n" + $_.Exception.Message,
        "PolyPDF 업데이트") | Out-Null
}

if ($fail -eq 0) {
    $bar.Value = 100; $lbl.Text = "설치 완료 — 프로그램을 다시 시작합니다."
    [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 700
} elseif ($fail -gt 0) {
    # 거짓 성공 금지: 일부 파일 교체 실패(권한 등)를 정직하게 알림.
    [System.Windows.Forms.MessageBox]::Show(
        "업데이트를 완료하지 못했습니다. $fail 개 파일을 교체하지 못했습니다(권한 문제일 수 있음).`n" +
        "최신 설치본(PolyPDF-Setup-*.exe)을 '관리자 권한으로 실행'해 주세요.",
        "PolyPDF 업데이트") | Out-Null
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


def apply_update(zip_path: str = None, url: str = "", sha256: str = "") -> bool:
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
    exe = sys.executable if is_frozen() else os.path.join(inst, "PolyPDF.exe")
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
              .replace("__SHA_B64__", _b64(str(sha256 or "").strip().lower())))
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
