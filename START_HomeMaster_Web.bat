@echo off
rem ============================================================
rem  Home Master - WEB version, test launcher for Windows
rem  Works with any Python 3.10+ (including 3.14 / 3.15).
rem  Starts a local server and opens the app in your browser.
rem ============================================================
setlocal
cd /d "%~dp0"
title Home Master - web launcher

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :havepy
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
:havepy
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython

if exist ".venv\Scripts\python.exe" goto :venvready
echo [1/3] Creating Python environment...
%PY% -m venv .venv
if errorlevel 1 goto :fail
:venvready
set "VPY=%~dp0.venv\Scripts\python.exe"

if exist ".venv\.installed_web" goto :installed
echo [2/3] Installing packages - first run only, 1-3 minutes, internet required...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%VPY%" -m pip install -r requirements-web.txt
if errorlevel 1 goto :fail
echo ok> ".venv\.installed_web"
:installed

echo [3/3] Starting local server on http://127.0.0.1:8000 ...
set "DATA_DIR=%~dp0data"
set "OWNER_USERNAME=owner"
set "OWNER_PASSWORD=owner123"
set "ALLOW_REGISTRATION=1"
set "MAP_PROVIDER=osm"
start "Home Master SERVER - close this window to stop" /D "%~dp0server" "%VPY%" -m uvicorn server:app --host 127.0.0.1 --port 8000

"%VPY%" tools\wait_server.py http://127.0.0.1:8000/config
if errorlevel 1 goto :noserver

if exist "data\.seeded" goto :seeded
echo Creating demo users and orders...
"%VPY%" tools\seed_demo.py http://127.0.0.1:8000 owner123
echo ok> "data\.seeded"
:seeded

start "" http://127.0.0.1:8000/app/
echo.
echo ============================================================
echo  Home Master is running:  http://127.0.0.1:8000/app/
echo  Logins: owner/owner123 ; admin1 head1 exec1 exec2 ctr1 client1 client2 staff1 observer1 / test1234
echo  To STOP: close the black "Home Master SERVER" window.
echo ============================================================
pause
exit /b 0

:nopython
echo.
echo Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer. Then run this file again.
pause
exit /b 1

:noserver
echo.
echo The server did not start. Look at the black "Home Master SERVER" window for the error text.
echo If it says the port is busy - close the other program using port 8000 or restart the PC.
pause
exit /b 1

:fail
echo.
echo Installation failed. Check the internet connection and run this file again.
echo If it fails again, send me a screenshot of this window.
pause
exit /b 1
