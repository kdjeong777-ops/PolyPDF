# 오래된 버전 릴리스 정리 — SOT 마스터 §14.5 U9 (260913-14)
#   버전(SemVer) 태그 릴리스를 버전 순으로 세어 최근 $Keep 개만 남기고 나머지 릴리스를 지운다.
#   - git 태그는 지우지 않는다(옛 버전 소스는 Tags 의 Source code 로 남는다).
#   - components 같은 비버전 릴리스와 draft 는 건드리지 않는다.
#   - 날짜가 아니라 버전으로 판정한다(updater.check_latest 와 같은 기준).
# 사용:
#   powershell -ExecutionPolicy Bypass -File scripts\prune_releases.ps1 -DryRun      # 미리보기
#   powershell -ExecutionPolicy Bypass -File scripts\prune_releases.ps1              # 실행(기본 10개 유지)
#   release.yml 이 릴리스 생성 직후 같은 스크립트를 부른다(GH_TOKEN 필요).
param(
    [int]$Keep = 10,
    [string]$Repo = "kdjeong777-ops/PolyPDF",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

if ($Keep -lt 3) {
    Write-Error "Keep=$Keep : U9 requires keeping at least 3 releases (rollback targets)."
    exit 2
}

$json = (gh release list --repo $Repo --limit 1000 --json tagName,isDraft) -join "`n"
if ($LASTEXITCODE -ne 0) { Write-Error "gh release list failed"; exit 1 }
# PowerShell 5.1 의 ConvertFrom-Json 은 JSON 배열을 한 덩어리로 넘긴다 - 한 번 풀어 준다(Count=1 오판 방지)
$all = @(($json | ConvertFrom-Json) | ForEach-Object { $_ })

# v1.2.3 / v1.2.3-beta.4 — 정식은 같은 core 의 프리릴리즈보다 높다.
$rx = '^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+)(?:\.(\d+))?)?$'
$ver = @()
foreach ($r in $all) {
    if ($r.isDraft) { continue }
    $m = [regex]::Match([string]$r.tagName, $rx)
    if (-not $m.Success) { continue }
    $isStable = -not $m.Groups[4].Success
    $preNum = 0
    if ($m.Groups[5].Success) { $preNum = [int]$m.Groups[5].Value }
    $ver += [pscustomobject]@{
        Tag = $r.tagName
        Major = [int]$m.Groups[1].Value; Minor = [int]$m.Groups[2].Value; Patch = [int]$m.Groups[3].Value
        Stable = [int]$isStable; PreLabel = [string]$m.Groups[4].Value; PreNum = $preNum
    }
}
$sorted = @($ver | Sort-Object -Property Major, Minor, Patch, Stable, PreLabel, PreNum -Descending)
$keepList = @($sorted | Select-Object -First $Keep)
$drop = @($sorted | Select-Object -Skip $Keep)

Write-Host ("releases: total={0} version={1} keep={2} delete={3}" -f $all.Count, $sorted.Count, $keepList.Count, $drop.Count)
Write-Host ("keep  : " + (($keepList | ForEach-Object { $_.Tag }) -join ", "))
if ($drop.Count -eq 0) { Write-Host "nothing to delete"; exit 0 }
Write-Host ("delete: " + (($drop | ForEach-Object { $_.Tag }) -join ", "))
if ($DryRun) { Write-Host "(dry run - nothing deleted)"; exit 0 }

$failed = 0
foreach ($d in $drop) {
    # --cleanup-tag 를 주지 않는다 = git 태그 유지
    gh release delete $d.Tag --repo $Repo --yes
    if ($LASTEXITCODE -ne 0) { Write-Warning ("delete failed: " + $d.Tag); $failed++ }
    else { Write-Host ("deleted: " + $d.Tag) }
}
if ($failed -gt 0) { exit 1 }
exit 0
