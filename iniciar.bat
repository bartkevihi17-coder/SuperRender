@echo off
setlocal
cd /d "%~dp0"
if exist "dist\SuperRender.exe" (
  start "" "dist\SuperRender.exe"
  exit /b
)
where py >nul 2>&1
if errorlevel 1 (
  echo Python nao encontrado. Instale Python 3.10+.
  pause
  exit /b 1
)
py -3 -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo Instalando componentes nativos da interface...
  py -3 -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)
start "" pyw -3 "%~dp0run.pyw"
exit /b
:fail
echo Falha ao preparar SuperRender.
pause
exit /b 1
