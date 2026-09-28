@echo off
rem Launch the GUI from source. If Python is missing it is installed for the
rem current user (no admin rights needed); the libraries (yt-dlp, tkinterdnd2)
rem are then installed by the program itself on first launch.
setlocal
cd /d "%~dp0"
set "APP=%~dp0ytdlp_gui.pyw"

call :find
if defined PYW goto run

echo Python 3 was not found. Installing it now, this takes a minute or two...
echo.
call :install
call :find
if defined PYW goto run

echo.
echo Could not install Python automatically.
echo Install it from https://www.python.org/downloads/ (keep "tcl/tk" checked)
echo and run this file again.
pause
exit /b 1

:run
start "" %PYW% "%APP%"
exit /b 0


rem ---------------------------------------------------------------- find
rem Sets PYW to a command that runs pythonw, or leaves it empty.
:find
set "PYW="
rem the usual install folders first: they work right after an install,
rem before PATH is refreshed in this window
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do (
    if exist "%%~d\pythonw.exe" set PYW="%%~d\pythonw.exe"
)
if defined PYW exit /b 0
rem the py launcher that comes with every python.org install
where pyw.exe >nul 2>nul && (
    set PYW=pyw.exe -3
    exit /b 0
)
rem pythonw.exe on PATH, skipping the Microsoft Store stub in WindowsApps
for /f "delims=" %%p in ('where pythonw.exe 2^>nul ^| findstr /v /i "WindowsApps"') do (
    set PYW="%%p"
    exit /b 0
)
exit /b 0


rem ---------------------------------------------------------------- install
:install
rem 1) winget, present on Windows 10/11 out of the box
where winget.exe >nul 2>nul && (
    winget install --id Python.Python.3.12 -e --scope user --silent ^
        --accept-package-agreements --accept-source-agreements
    call :find
    if defined PYW exit /b 0
)
rem 2) the official installer from python.org, per-user and silent
set "PYSETUP=%TEMP%\python-3.12.10-amd64.exe"
echo Downloading Python from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $env:PYSETUP"
if not exist "%PYSETUP%" exit /b 1
echo Installing Python...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1 Include_test=0
del "%PYSETUP%" >nul 2>nul
exit /b 0
