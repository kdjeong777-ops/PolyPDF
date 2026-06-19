# 260618-12: 앱 '구성요소 설치'가 받을 자산(ffmpeg.exe, tesseract.zip)을 준비한다.
#   릴리스의 고정 태그 'components' 에 1회 업로드해 두면, 모든 버전의 앱이 거기서 받는다.
#   (ffmpeg/Tesseract 는 앱 버전과 무관 → 바뀔 때만 다시 업로드)
# 사용: powershell -ExecutionPolicy Bypass -File scripts\make_components.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # smart_pdf_viewer
$ff   = Join-Path $root "ffmpeg.exe"
$tess = Join-Path $root "tesseract"
$zip  = Join-Path $root "tesseract.zip"
if (-not (Test-Path $ff))   { Write-Error "ffmpeg.exe 가 없습니다($ff). 빌드 환경의 ffmpeg.exe 를 두세요." }
if (-not (Test-Path $tess)) { Write-Error "tesseract\ 폴더가 없습니다($tess)." }
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "tesseract.zip 압축 중 ..."
# 폴더 자체를 포함 → zip 루트가 tesseract\ (components.install_tesseract 의 rooted 처리와 일치)
Compress-Archive -Path $tess -DestinationPath $zip -CompressionLevel Optimal
$mbF = [math]::Round((Get-Item $ff).Length/1MB,1)
$mbZ = [math]::Round((Get-Item $zip).Length/1MB,1)
Write-Host "준비 완료:"
Write-Host "  $ff   ($mbF MB)"
Write-Host "  $zip  ($mbZ MB)"
Write-Host ""
Write-Host "업로드(1회): gh release create components `"$ff`" `"$zip`" --title `"Components (ffmpeg/Tesseract)`" --notes `"녹화·OCR 구성요소`""
Write-Host "  (이미 있으면: gh release upload components `"$ff`" `"$zip`" --clobber)"
Write-Host "  또는 GitHub 웹 Releases 에서 태그 'components' 릴리스에 두 파일 업로드."
