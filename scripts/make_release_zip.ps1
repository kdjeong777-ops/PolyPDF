# 260618-11: 빌드 산출물(dist\PolyPDF)을 릴리스 자산 zip 으로 묶는다(수동 릴리스용).
#   이름은 CI(release.yml)와 동일한 PolyPDF-v<ver>-win64.zip 규약. zip 루트에 PolyPDF.exe·_internal\.
#   ※ 보통은 'git push --tags' 만 하면 GitHub Actions(release.yml)가 자동 빌드·릴리스함.
#      이 스크립트는 로컬 빌드를 수동 업로드할 때만 사용.
# 사용: build_ci.bat 빌드 후 -> powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # smart_pdf_viewer
$src  = Join-Path $root "dist\PolyPDF"
$exe  = Join-Path $src  "PolyPDF.exe"
if (-not (Test-Path $exe)) {
    Write-Error "빌드 산출물이 없습니다: $exe `n먼저 build_ci.bat 로 빌드하세요."
    exit 1
}
$verLine = Select-String -Path (Join-Path $root "viewer\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
$ver = if ($verLine) { $verLine.Matches[0].Groups[1].Value } else { "0.0.0" }
$out = Join-Path $root "PolyPDF-v$ver-win64.zip"
if (Test-Path $out) { Remove-Item $out -Force }
Write-Host "압축 중 (v$ver) ..."
Compress-Archive -Path (Join-Path $src "*") -DestinationPath $out -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $out).Length/1MB, 1)
Write-Host "생성 완료: $out  ($mb MB)  버전 v$ver"
Write-Host "다음: gh release create v$ver `"$out`" --title `"PolyPDF v$ver`" --generate-notes  (또는 GitHub 웹 업로드)"
