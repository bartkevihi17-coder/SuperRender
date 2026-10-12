@echo off
setlocal
cd /d "%~dp0"

rem Em clones Git, prefira o codigo-fonte para que um git pull tenha efeito
rem imediato. Pacotes distribuidos sem .git continuam usando o EXE compilado.
if exist ".git" goto :source

if exist "dist\SuperRender.exe" (
  start "" "dist\SuperRender.exe"
  exit /b
)

:source
where py >nul 2>&1
if errorlevel 1 (
  if exist "dist\SuperRender.exe" (
    echo Python nao encontrado. Abrindo o executavel compilado.
    start "" "dist\SuperRender.exe"
    exit /b
  )
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
