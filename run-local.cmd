@echo off
setlocal
cd /d "%~dp0"
set "KPI_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%KPI_PY%" set "KPI_PY=python"
"%KPI_PY%" -c "import openpyxl, reportlab" >nul 2>nul
if errorlevel 1 (
    echo Install Python 3.12 and run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo KPI KGD - open http://127.0.0.1:8765 after the Local line appears.
"%KPI_PY%" -m kpi.server %*
if errorlevel 1 pause

