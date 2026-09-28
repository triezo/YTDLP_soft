@echo off
rem Launch the GUI from source. Missing libraries (yt-dlp, tkinterdnd2) are
rem installed by the program itself on first launch.
setlocal
cd /d "%~dp0"

rem 1) the py launcher that comes with every python.org install
where pyw.exe >nul 2>nul && (
    start "" pyw.exe -3 "%~dp0ytdlp_gui.pyw"
    exit /b 0
)

rem 2) pythonw.exe on PATH (skip the Microsoft Store stub in WindowsApps)
for /f "delims=" %%p in ('where pythonw.exe 2^>nul ^| findstr /v /i "WindowsApps"') do (
    start "" "%%p" "%~dp0ytdlp_gui.pyw"
    exit /b 0
)

rem 3) the usual install folders, any Python 3 version, newest last
set "PYW="
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do (
    if exist "%%~d\pythonw.exe" set "PYW=%%~d\pythonw.exe"
)
if defined PYW (
    start "" "%PYW%" "%~dp0ytdlp_gui.pyw"
    exit /b 0
)

echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/ (keep "tcl/tk" checked),
echo or use the ready-made "YT-DLP GUI.exe" from the Releases page instead.
pause
exit /b 1
