@echo off
setlocal
cd /d "%~dp0.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found at "%PY%"
  echo Create it first, then install numpy/scipy.
  pause
  exit /b 1
)

if "%~1"=="" (
  "%PY%" "Metrics\mat_curve_metrics.py"
) else (
  "%PY%" "Metrics\mat_curve_metrics.py" "%~1"
)

echo.
echo Exit code: %ERRORLEVEL%
pause
