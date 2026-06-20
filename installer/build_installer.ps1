# PolyPDF 설치 프로그램(setup.exe) 로컬 빌드 — 260618-30
#   먼저 build_ci.bat 로 dist\PolyPDF 를 만든 뒤 실행.
#   Inno Setup 6(ISCC.exe) 필요:  winget install -e --id JRSoftware.InnoSetup
#   사용:  powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # smart_pdf_viewer
$iss  = Join-Path $PSScriptRoot "PolyPDF.iss"

if (-not (Test-Path (Join-Path $root "dist\PolyPDF\PolyPDF.exe"))) {
    Write-Error "dist\PolyPDF\PolyPDF.exe 가 없습니다. 먼저 build_ci.bat 로 빌드하세요."
}

# 버전 읽기
$verLine = Select-String -Path (Join-Path $root "viewer\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
$ver = if ($verLine) { $verLine.Matches[0].Groups[1].Value } else { "0.0.0" }

# ISCC 찾기
$iscc = $null
foreach ($p in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe")) {
    if ($p -and (Test-Path $p)) { $iscc = $p; break }
}
if (-not $iscc) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if (-not $iscc) {
    Write-Error "ISCC.exe(Inno Setup 6) 를 찾을 수 없습니다.`n설치:  winget install -e --id JRSoftware.InnoSetup"
}

Write-Host "ISCC: $iscc"
Write-Host "버전: $ver"
& $iscc "/DMyAppVersion=$ver" $iss
if ($LASTEXITCODE -ne 0) { Write-Error "ISCC 컴파일 실패(code $LASTEXITCODE)" }

$out = Join-Path $root "PolyPDF-Setup-v$ver.exe"
if (Test-Path $out) {
    $mb = [math]::Round((Get-Item $out).Length/1MB,1)
    Write-Host "생성 완료:  $out  ($mb MB)"
} else {
    Write-Error "출력 파일을 찾을 수 없습니다: $out"
}
