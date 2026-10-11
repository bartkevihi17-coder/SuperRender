@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Instale Python 3.10+ antes de compilar.
  pause
  exit /b 1
)
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto :fail
py -3 -m pip install "pyinstaller>=6.9,<8"
if errorlevel 1 goto :fail
py -3 scripts\build_low_priority.py
if errorlevel 1 goto :fail
echo.
echo Pronto: dist\SuperRender.exe
pause
exit /b
:fail
echo Falha ao compilar; consulte o log acima.
pause
exit /b 1
