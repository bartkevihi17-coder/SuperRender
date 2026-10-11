@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>&1
if not %errorlevel%==0 (
  echo Git nao encontrado. Reabra o terminal ou instale Git for Windows.
  pause
  exit /b 1
)
git pull --ff-only
if errorlevel 1 (
  echo Nao foi possivel atualizar. Verifique suas alteracoes locais.
)
pause
