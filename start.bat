@echo off
rem Double-click this file to start the server on Windows.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title Emergency Meeting
rem Tells the server that it was started from here, so that /reboot works.
set "EM_LAUNCHER=start.bat"

set "PY="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3 is missing. Download it from https://www.python.org/downloads/windows/
    echo When you install it, tick "Add python.exe to PATH".
    goto end
)

:run
%PY% -m server
set "CODE=%ERRORLEVEL%"
rem 75 = /reboot, 76 = start again after a problem (see server/platforms.py)
if "%CODE%"=="75" (
    set "EM_AFTER_FAILED_START="
    goto run
)
if "%CODE%"=="76" (
    set "EM_AFTER_FAILED_START=1"
    goto run
)

:end
echo.
pause
