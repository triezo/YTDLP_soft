@echo off
rem Запуск GUI. Ищем pythonw.exe: сначала обычные места установки, потом PATH.
setlocal
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if exist "%PYW%" goto run
for /f "delims=" %%p in ('where pythonw.exe 2^>nul') do (
    set "PYW=%%p"
    goto run
)
echo Не найден pythonw.exe. Установите Python 3 с tkinter.
pause
exit /b 1

:run
start "" "%PYW%" "%~dp0ytdlp_gui.pyw"
