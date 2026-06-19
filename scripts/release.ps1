# 260618-13: 원클릭 릴리스 — 버전 bump → commit → tag → push (CI가 빌드·릴리스).
# 사용:  powershell -ExecutionPolicy Bypass -File scripts\release.ps1 2.26.0
#        (또는 프로젝트 루트에서:  .\scripts\release.ps1 2.26.0)
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # smart_pdf_viewer

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "버전 형식이 잘못됨: '$Version' (예: 2.26.0)"; exit 1
}
$tag = "v$Version"

# 이미 있는 태그면 중단
git -C $root rev-parse -q --verify "refs/tags/$tag" *> $null
if ($LASTEXITCODE -eq 0) { Write-Error "태그 $tag 이(가) 이미 있습니다."; exit 1 }

# 원격(origin) 확인
$null = git -C $root remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) { Write-Error "origin 원격이 없습니다. 먼저 git remote add origin <URL>."; exit 1 }

# __version__ 갱신 (정확히 한 곳)
$initPath = Join-Path $root "viewer\__init__.py"
$c = Get-Content -LiteralPath $initPath -Raw
$c2 = [regex]::Replace($c, '__version__\s*=\s*"[^"]+"', "__version__ = `"$Version`"")
if ($c2 -eq $c) { Write-Error "viewer\__init__.py 에서 __version__ 을 찾지 못했습니다."; exit 1 }
[System.IO.File]::WriteAllText($initPath, $c2)   # UTF-8(BOM 없음), 원본 줄바꿈 보존
Write-Host "버전 → $Version"

git -C $root add -A
git -C $root commit -m "v$Version"
git -C $root tag -a $tag -m "PolyPDF $tag"
Write-Host "push 중 ... (최초 push 시 브라우저 로그인 창이 뜰 수 있음)"
git -C $root push origin HEAD
git -C $root push origin $tag

Write-Host ""
Write-Host "완료: $tag push 됨 → GitHub Actions(release.yml)가 빌드·릴리스합니다."
Write-Host "  진행: 저장소 Actions 탭 / 결과: Releases 탭 (PolyPDF-$tag-win64.zip)"
Write-Host "  기존 사용자 앱은 '도움말 → 업데이트 확인'에서 자동 감지됩니다."
