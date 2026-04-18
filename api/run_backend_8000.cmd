@echo off
cd /d %~dp0
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 1>uvicorn_8000.log 2>uvicorn_8000_err.log
