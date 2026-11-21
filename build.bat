@echo off

chcp 65001 >nul

cd /d "%~dp0"

echo Building HardwareNameChanger.exe ... please wait

where py >nul 2>nul && (set PY=py -3.11) || (set PY=python)

%PY% -m pip install --quiet --upgrade pyinstaller

if errorlevel 1 (echo pip failed. Is Python installed? & pause & exit /b 1)

%PY% -m PyInstaller --noconfirm --onefile --noconsole --uac-admin --name HardwareNameChanger hwname.py

if not exist "dist\HardwareNameChanger.exe" (echo Build failed. & pause & exit /b 1)

copy /y "dist\HardwareNameChanger.exe" "HardwareNameChanger.exe" >nul

rmdir /s /q dist >nul 2>nul

rmdir /s /q build >nul 2>nul

del /q HardwareNameChanger.spec >nul 2>nul

echo.

echo Done! HardwareNameChanger.exe is ready in this folder.

pause

