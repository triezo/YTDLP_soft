@echo off
rem Сборка YT-DLP GUI.exe. Нужен Python 3.12 с pyinstaller и yt-dlp.
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m PyInstaller --noconfirm --clean ^
  --onefile --windowed ^
  --name "YT-DLP GUI" ^
  --icon "%~dp0app.ico" ^
  --add-data "%~dp0app.ico;." ^
  --version-file "%~dp0version_info.txt" ^
  --collect-all yt_dlp ^
  --collect-all tkinterdnd2 ^
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module numpy ^
  --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" ^
  "%~dp0ytdlp_gui.pyw"

echo.
echo Готово: "%~dp0dist\YT-DLP GUI.exe"
pause
