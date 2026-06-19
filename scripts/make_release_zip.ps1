# 260618-11/14: 빌드 산출물(dist\PolyPDF)을 릴리스 zip 2종으로 묶는다(수동 릴리스용).
#   1) PolyPDF-v<ver>-win64.zip        : 전체(첫 설치용 — ffmpeg·Tesseract·모델 포함)
#   2) PolyPDF-v<ver>-win64-update.zip : 업데이트용(안 바뀌는 무거운 부분 제외 → 기존 설치분 보존)
#   앱 업데이터는 'update' zip 을 우선 받으므로, 업데이트 시 ffmpeg·모델을 다시 안 받음.
#   ※ 보통은 'git push --tags' → GitHub Actions(release.yml)가 자동 생성. 이 스크립트는 수동 업로드용.
# 사용: build_ci.bat 빌드 후 -> powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # smart_pdf_viewer
$src  = Join-Path $root "dist\PolyPDF"
if (-not (Test-Path (Join-Path $src "PolyPDF.exe"))) {
    Write-Error "빌드 산출물이 없습니다: $src\PolyPDF.exe `n먼저 build_ci.bat 로 빌드하세요."
    exit 1
}
$verLine = Select-String -Path (Join-Path $root "viewer\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
$ver = if ($verLine) { $verLine.Matches[0].Groups[1].Value } else { "0.0.0" }

# 1) 전체(full)
$full = Join-Path $root "PolyPDF-v$ver-win64.zip"
if (Test-Path $full) { Remove-Item $full -Force }
Write-Host "full zip 생성 중 (v$ver) ..."
Compress-Archive -Path (Join-Path $src "*") -DestinationPath $full -CompressionLevel Optimal

# 2) 업데이트(update) — 무거운 불변 부분 제외(스테이징 복사 후 삭제)
$upd = Join-Path $root "PolyPDF-v$ver-win64-update.zip"
if (Test-Path $upd) { Remove-Item $upd -Force }
$stage = Join-Path $env:TEMP ("polypdf_upd_stage_" + $ver)
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
Write-Host "update zip 준비(스테이징 복사) ..."
Copy-Item $src $stage -Recurse
$internal = Join-Path $stage "_internal"
foreach ($p in @("ffmpeg.exe","tesseract","kiwipiepy_model","nltk_data")) {
    $t = Join-Path $internal $p
    if (Test-Path $t) { Remove-Item $t -Recurse -Force }
}
Write-Host "update zip 생성 중 ..."
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $upd -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

$mbF = [math]::Round((Get-Item $full).Length/1MB,1)
$mbU = [math]::Round((Get-Item $upd).Length/1MB,1)
Write-Host ""
Write-Host "생성 완료 (v$ver):"
Write-Host "  $full   ($mbF MB)  ← 첫 설치 배포용"
Write-Host "  $upd    ($mbU MB)  ← 자동 업데이트용(앱이 이걸 우선 받음)"
Write-Host "업로드: gh release create v$ver `"$full`" `"$upd`" --title `"PolyPDF v$ver`" --generate-notes"
