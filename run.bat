@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUNBUFFERED=1

REM Open Edge immediately
start "" msedge.exe --app=http://127.0.0.1:5001 --window-size=520,600

REM Run Python (Ctrl+C to stop)
"C:\Users\asus\AppData\Local\Programs\Python\Python310\python.exe" -u "%~dp0run.py" 2>"%~dp0error.log"

pause
