@echo off
rem Double-click to start VC Signal: starts the hidden background server (or reports it is already running) and opens
rem the dashboard in your browser. Start your MetaTrader 5 terminal and log in first. Stop with: gold.cmd stop
setlocal
cd /d "%~dp0"
call gold.cmd start
if errorlevel 1 (
  echo.
  echo VC Signal did not start. See .tmp\gold-signals\server.log
  pause
  exit /b 1
)
rem open the recorded dashboard URL (the port may differ from 8000); only the url field is read
for /f "usebackq delims=" %%U in (`".venv\Scripts\python.exe" -c "import json;print(json.load(open(r'.tmp\gold-signals\server.json',encoding='utf-8'))['url'])"`) do set "VC_URL=%%U"
if not defined VC_URL set "VC_URL=http://127.0.0.1:8000/"
echo Opening %VC_URL%
start "" "%VC_URL%"
echo.
echo VC Signal keeps running in the background after you close this window. Stop it with: gold.cmd stop
pause
