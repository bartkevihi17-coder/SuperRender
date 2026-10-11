@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>&1
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0run.pyw"
    exit /b
)
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0run.pyw"
    exit /b
)
echo Python 3 nao encontrado. Instale Python 3.10+ ou use o executavel criado em dist.
pause
