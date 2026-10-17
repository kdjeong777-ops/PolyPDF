@echo off
REM PolyPDF virtual printer - build the port monitor (polypdfmon.dll) from the vendored MFILEMON 1.6.1 source.
REM Run inside an MSVC x64 developer environment (vcvars64.bat). CI: .github\workflows\release.yml.
REM Output: printer\bin\polypdfmon.dll  (bin\ and obj\ are not tracked)
setlocal
set "HERE=%~dp0"
set "SRC=%HERE%monitor_src\monitor"
set "OBJ=%HERE%obj"
set "BIN=%HERE%bin"
if not exist "%OBJ%" mkdir "%OBJ%"
if not exist "%BIN%" mkdir "%BIN%"
pushd "%SRC%"
rc /nologo /DMFILEMONLANG=0x409 /fo "%OBJ%\polypdfmon.res" resource.rc
if errorlevel 1 ( popd & echo [ERROR] rc failed & exit /b 1 )
cl /nologo /O2 /MT /EHsc /W3 /LD /DUNICODE /D_UNICODE /DWIN64 /D_WIN64 /DNDEBUG /D_WINDOWS /D_USRDLL /DMFILEMON_EXPORTS /DMFILEMONLANG=0x409 /DPOLYPDF_NO_RUNAS ^
  monitor.cpp port.cpp portlist.cpp pattern.cpp patsegment.cpp log.cpp stdafx.cpp ^
  ..\common\autoclean.cpp ..\common\defs.cpp ..\common\monutils.cpp ..\common\sec_api.c ^
  "%OBJ%\polypdfmon.res" /Fo"%OBJ%\\" /Fe"%BIN%\polypdfmon.dll" ^
  /link /DEF:mfilemon.def winspool.lib advapi32.lib user32.lib crypt32.lib ws2_32.lib wtsapi32.lib
if errorlevel 1 ( popd & echo [ERROR] cl failed & exit /b 1 )
popd
if not exist "%BIN%\polypdfmon.dll" ( echo [ERROR] polypdfmon.dll not produced & exit /b 1 )
echo polypdfmon.dll built
exit /b 0
