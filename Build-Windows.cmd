@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm MIO_OriginOS_Patcher.spec
if errorlevel 1 exit /b 1
echo Built: dist\MIO_OriginOS_Patcher.exe
endlocal
