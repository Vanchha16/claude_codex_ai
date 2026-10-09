@echo off
rem Project-local launcher for VC Signal (local gold signal dashboard).
rem   gold.cmd start | stop | status | restart | replay [--source mt5|csv ...] | symbols [pattern] | build-ui | test
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. See README.md "Setup" to create it.
  exit /b 1
)
set PYTHONDONTWRITEBYTECODE=1
".venv\Scripts\python.exe" -m app.launcher %*
exit /b %ERRORLEVEL%
