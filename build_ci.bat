@echo off
setlocal
REM 260628-2: 이 파일은 UTF-8 로 저장돼 있다. 콘솔 코드페이지를 UTF-8 로 맞추지 않으면
REM   아래 한글 [ERROR]/[WARN] 메시지가 깨져 나와 빌드 실패 원인을 읽을 수 없다.
chcp 65001 >nul

REM 260616: 빌드(PyInstaller·python 워커) 우선순위 High 로 상향 — CPU 경쟁 시 분석 단계가
REM   극단적으로 느려지던 문제 완화(무관리자). ※ Windows 는 High 부모의 자식을 Normal 로 만들므로
REM   부모 우선순위 상향은 무효 → 백그라운드 루프로 '빌드 시작 후 생성된' pyinstaller/python 을
REM   주기적으로 High 로 올린다(약 3분, 종료 시 자동 소멸). 무관한 기존 python 은 StartTime 으로 제외.
start "" /B powershell -NoProfile -WindowStyle Hidden -Command "$t=(Get-Date).AddMinutes(-1); 1..90 | %%{ Get-Process pyinstaller,python -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt $t -and $_.PriorityClass -eq 'Normal' } | ForEach-Object { try{$_.PriorityClass='High'}catch{} }; Start-Sleep -Seconds 2 }" >nul 2>&1

cd /d "%~dp0"
echo.
echo ============================================================
echo   PolyPDF - Build Windows EXE
echo ============================================================
echo.
echo This script will:
echo   1) Create a Python virtual environment (.venv)
echo   2) Install PyQt6, PyMuPDF, openpyxl, Pillow, PyInstaller (~140 MB)
echo   3) Ensure resources\icon.ico exists (regenerate from icon.png if missing)
echo   4) Build a standalone Windows .exe (~3-5 min)
echo.
echo Total expected time on first run: 5 to 15 minutes.
echo.
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
rem pause (CI)
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo Detected: %%v
echo.

if not exist ".venv\" (
    echo [1/5] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo [ERROR] venv creation failed. & exit /b 1 )
) else (
    echo [1/5] Using existing .venv
)

call .venv\Scripts\activate.bat

echo.
echo [2/5] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 ( echo [ERROR] pip upgrade failed. & exit /b 1 )

echo.
echo [3/5] Installing PyQt6, PyMuPDF, openpyxl, Pillow, pdfplumber, pypdfium2,
echo       pypdf, send2trash, PyInstaller... (~180 MB)
REM v1.6.2: Pillow 가 requirements.txt 에 포함되어 있음 (PyInstaller 아이콘 변환용).
REM v1.6.16~21: pdf_bookmarker 의존성(pdfplumber/pypdfium2/pypdf) + send2trash 도 동봉.
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo [ERROR] Package install failed. & exit /b 1 )

echo.
echo [4/5] Ensuring resources\icon.ico exists...
if not exist "resources\icon.ico" (
    if exist "resources\icon.png" (
        echo Generating icon.ico from icon.png ...
        python -c "from PIL import Image; im=Image.open('resources/icon.png').convert('RGBA'); im.save('resources/icon.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
        if errorlevel 1 ( echo [ERROR] icon.ico 변환 실패. Pillow 가 설치되었는지 확인. & exit /b 1 )
    ) else (
        echo [WARN] resources\icon.png 도 없습니다. 아이콘 없이 빌드합니다.
    )
)

echo.
echo [5/5] Running PyInstaller (this takes 1-3 minutes)...

if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"
if exist "PolyPDF.spec" del "PolyPDF.spec"
if exist "Smart_PDF_Viewer.spec" del "Smart_PDF_Viewer.spec"

REM v1.6.2: __pycache__ 정리 (stale .pyc 가 번들에 섞이는 것 방지)
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"

REM v1.6.2: 빌드 전 syntax 검증 — 깨진 소스가 EXE 에 들어가 런타임 SyntaxError 나는 것 방지
echo Verifying source syntax...
python -m py_compile main.py
if errorlevel 1 ( echo [ERROR] main.py 가 컴파일되지 않습니다. & exit /b 1 )
for %%f in (viewer\app.py viewer\history.py viewer\indexer.py viewer\pdf_doc.py ^
            viewer\screenshot.py viewer\settings_store.py viewer\workers.py ^
            viewer\resources_path.py viewer\bookmarker_bridge.py ^
            viewer\_vendor\__init__.py viewer\_vendor\pdf_bookmarker\__init__.py ^
            viewer\widgets\bookmark_tree.py viewer\widgets\favorites_dialog.py ^
            viewer\widgets\help_dialog.py viewer\widgets\main_view.py ^
            viewer\widgets\search_panel.py viewer\widgets\settings_dialog.py ^
            viewer\widgets\strip.py viewer\widgets\thumbs_list.py ^
            viewer\widgets\bookmarker_dialog.py viewer\widgets\screenshot_pdf_dialog.py ^
            viewer\widgets\study_panel.py viewer\study\__init__.py ^
            viewer\study\ocr.py viewer\study\vocab.py viewer\study\study_store.py) do (
    python -m py_compile %%f
    if errorlevel 1 ( echo [ERROR] %%f 가 컴파일되지 않습니다. & exit /b 1 )
)
echo  All source files compile OK.

REM v1.6.2: --icon 을 .ico 로 변경. Pillow 가 없어도 사전 변환된 ico 를 사용.
REM         resources 폴더는 --add-data 로 동봉되어 런타임에 icon.png 도 접근 가능.
set ICON_ARG=
if exist "resources\icon.ico" set ICON_ARG=--icon "resources/icon.ico"

REM v1.7.0 단어학습: Tesseract 트리 + NLTK WordNet 데이터 동봉 (계획서 §14.5/§8.3).
REM   개발자가 빌드 전 다음을 준비:
REM   1) tesseract\  폴더에 portable Tesseract (Library\bin\*.dll + tesseract.exe,
REM      share\tessdata\{eng,kor}.traineddata). micromamba env 의 Library/share 를 복사.
REM      예) study_spike\mamba\envs\ocr 의 Library, share 를 build 폴더 tesseract\ 로.
REM   2) nltk_data\  폴더에 WordNet (python -m nltk.downloader -d nltk_data wordnet omw-1.4).
REM   런타임은 viewer\study\ocr.py 가 sys._MEIPASS\tesseract 에서 자동 탐색, NLTK 는 nltk_data.
REM 260618-14: ffmpeg(녹화)/Tesseract(OCR) 재동봉 — 다운로드+은밀실행 패턴을 Defender 가
REM   차단하던 문제 회피(번들은 사용자가 직접 푼 앱의 일부라 차단 확률↓). 용량은 커짐.
REM   (구성요소 설치 기능은 선택적 폴백으로 유지 — 번들이 있으면 그걸 우선 사용)
set TESS_ARG=
if exist "tesseract\tesseract.exe"              set TESS_ARG=--add-data "tesseract;tesseract"
if exist "tesseract\Library\bin\tesseract.exe"  set TESS_ARG=--add-data "tesseract;tesseract"
set NLTK_ARG=
if exist "nltk_data"                    set NLTK_ARG=--add-data "nltk_data;nltk_data"
set FFMPEG_ARG=
if exist "ffmpeg.exe"                   set FFMPEG_ARG=--add-binary "ffmpeg.exe;."

REM v1.6.2 빌드 에러 수정: viewer 패키지를 표준 import 경로에 노출.
REM   - `--paths "."` 만으로는 PyInstaller modulegraph 만 인지하고,
REM     `--collect-submodules viewer` 가 호출하는 Python 표준 import 가 viewer 를 못 찾아
REM     실제 번들에서 viewer.app 등이 누락되는 현상이 있었음.
REM   - PYTHONPATH 환경변수 + 절대 경로 --paths "%cd%" 로 양쪽 모두 해결.
REM   - 추가로 viewer/ 폴더 전체를 --add-data 로 데이터 동봉 (런타임 sys.path 폴백용).
set "PYTHONPATH=%cd%;%PYTHONPATH%"

pyinstaller ^
    --name "PolyPDF" ^
    --windowed ^
    --onedir ^
    --paths "%cd%" ^
    --collect-all PyQt6 ^
    --hidden-import PyQt6.QtMultimedia ^
    --hidden-import PyQt6.QtMultimediaWidgets ^
    --collect-all fitz ^
    --collect-all pdfplumber ^
    --collect-all pypdfium2 ^
    --collect-all pypdf ^
    --collect-all wordfreq ^
    --collect-all pytesseract ^
    --collect-all kiwipiepy ^
    --collect-all kiwipiepy_model ^
    --collect-all docx ^
    --collect-all lameenc ^
    --collect-submodules viewer ^
    --add-data "resources;resources" ^
    --add-data "viewer;viewer" ^
    %FFMPEG_ARG% ^
    %TESS_ARG% ^
    %NLTK_ARG% ^
    %ICON_ARG% ^
    --hidden-import viewer ^
    --collect-all anthropic ^
    --hidden-import pytesseract ^
    --hidden-import wordfreq ^
    --hidden-import nltk ^
    --hidden-import kiwipiepy ^
    --hidden-import kiwipiepy_model ^
    --hidden-import docx ^
    --hidden-import lameenc ^
    --hidden-import win32com ^
    --hidden-import win32com.client ^
    --hidden-import pythoncom ^
    --hidden-import pywintypes ^
    --hidden-import openpyxl ^
    --hidden-import openpyxl.cell._writer ^
    --hidden-import send2trash ^
    --noconfirm ^
    main.py
if errorlevel 1 ( echo [ERROR] PyInstaller build failed. & exit /b 1 )

REM 260603: build\ 정리 — build\PolyPDF\PolyPDF.exe(불완전 부트로더, python DLL 누락) 오실행 방지.
REM   실제 실행 파일은 dist\PolyPDF\PolyPDF.exe 하나뿐이 되도록.
if exist "build" rmdir /s /q "build"

echo.
echo ============================================================
echo   BUILD SUCCESS !
echo   Output: dist\PolyPDF.exe
echo ============================================================
echo.
rem start (CI)
rem pause (CI)
endlocal
