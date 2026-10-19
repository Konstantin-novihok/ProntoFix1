@echo off
cd /d "%~dp0"
echo This deletes ALL test data: database, photos, documents, demo users.
choice /M "Continue"
if errorlevel 2 exit /b 0
rmdir /s /q data
echo Done. The next START_HomeMaster_Web.bat will create fresh demo data.
pause
