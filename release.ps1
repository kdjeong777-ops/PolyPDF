# 260618-13: 원클릭 릴리스 — 버전 변경 + 커밋 + 태그 + push (CI가 빌드·릴리스).
# 사용:  .\release.ps1 2.26.0        (또는)   powershell -ExecutionPolicy Bypass -File release.ps1 2.26.0
#   → viewer\__init__.py 의 __version__ 갱신 → git commit/tag v2.26.0 → push
#   → GitHub Actions(release.yml)가 빌드해 PolyPDF-v2.26.0-win64.zip 릴리스 생성
#   → 사용자 앱이 '업데이트 확인'에서 자동 감지
param([Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "버전 형식은 X.Y.Z 입니다 (예: 2.26.0). 입력값: '$Version'"; exit 1
}
$tag = "v$Version"

# 깨끗한 작업트리 권장(미커밋 변경이 있으면 함께 커밋됨을 알림)
$dirty = (git status --porcelain)
if ($dirty) { Write-Host "참고: 미커밋 변경이 있어 이번 커밋에 함께 포함됩니다." -ForegroundColor Yellow }

# 1) 버전 갱신(한글 docstring 보존 위해 Python 헬퍼로 UTF-8 처리)
python scripts\bump_version.py $Version
if ($LASTEXITCODE -ne 0) { Write-Error "버전 갱신 실패"; exit 1 }

# 2) 커밋·태그
git add -A
git commit -m "$tag"
if (git tag -l $tag) { Write-Error "태그 $tag 가 이미 있습니다. 다른 버전을 쓰거나 'git tag -d $tag' 후 재시도."; exit 1 }
git tag -a $tag -m "PolyPDF $tag"

# 3) push (브랜치 + 태그) — 첫 push 시 브라우저 로그인 창이 뜰 수 있음
git push
git push origin $tag

Write-Host ""
Write-Host "완료: $tag push 됨. GitHub Actions가 빌드→릴리스합니다." -ForegroundColor Green
Write-Host "  Actions:  https://github.com/kdjeong777-ops/PolyPDF/actions"
Write-Host "  Releases: https://github.com/kdjeong777-ops/PolyPDF/releases"
