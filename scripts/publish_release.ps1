# PolyPDF — 로컬 빌드 결과를 GitHub Release 로 게시 (권장: 바이너리(ffmpeg/tesseract)가
# 이미 갖춰진 개발 PC 에서 build_ci.bat 으로 빌드한 dist\PolyPDF 를 zip → 릴리스 업로드).
#
# 사전: gh(GitHub CLI) 설치 + `gh auth login` 완료. 저장소 루트에서 실행.
# 사용: powershell -ExecutionPolicy Bypass -File scripts\publish_release.ps1 -Tag v1.88.0
param(
  [Parameter(Mandatory=$true)][string]$Tag,
  [switch]$Build      # 지정 시 build_ci.bat 으로 새로 빌드
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # 저장소 루트

if ($Build) {
  Write-Host "[1/3] build_ci.bat ..."
  cmd /c build_ci.bat
  if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

if (-not (Test-Path "dist\PolyPDF\PolyPDF.exe")) {
  throw "dist\PolyPDF\PolyPDF.exe 없음 — 먼저 build_ci.bat 으로 빌드하거나 -Build 사용"
}

$zip = "PolyPDF-$Tag-win64.zip"
Write-Host "[2/3] zip → $zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "dist\PolyPDF\*" -DestinationPath $zip -Force

Write-Host "[3/3] gh release create $Tag"
# 태그가 없으면 현재 커밋에 생성. 이미 있으면 자산만 업로드.
$exists = (gh release view $Tag 2>$null)
if ($LASTEXITCODE -eq 0) {
  gh release upload $Tag $zip --clobber
} else {
  gh release create $Tag $zip --title "PolyPDF $Tag" --generate-notes
}
Write-Host "완료: $Tag 릴리스에 $zip 업로드됨"
