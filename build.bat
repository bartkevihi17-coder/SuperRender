@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not %errorlevel%==0 (
  echo Instale Python 3.10 ou superior antes de compilar.
  pause
  exit /b 1
)
py -3 -m pip install "pyinstaller>=6.9,<8"
if errorlevel 1 goto :fail
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --icon "assets\SuperRender.ico" --add-data "assets\SuperRender.ico;assets" --name SuperRender --distpath dist run.pyw
if errorlevel 1 goto :fail
echo.
echo Pronto! Distribua o arquivo dist\SuperRender.exe.
pause
exit /b 0
:fail
echo Erro ao empacotar. Verifique o log acima.
pause
exit /b 1
