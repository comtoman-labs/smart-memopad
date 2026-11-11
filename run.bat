@echo off
setlocal
cd /d "%~dp0"

rem 1. Check virtual environments (pythonw for clean GUI without console)
set "PY="
if exist ".venv\Scripts\pythonw.exe" set "PY=.venv\Scripts\pythonw.exe"
if not defined PY if exist "venv\Scripts\pythonw.exe" set "PY=venv\Scripts\pythonw.exe"
if not defined PY if exist "D:\workspace\venv_com\Scripts\pythonw.exe" set "PY=D:\workspace\venv_com\Scripts\pythonw.exe"
if not defined PY if exist "D:\workspace\venv_pub\Scripts\pythonw.exe" set "PY=D:\workspace\venv_pub\Scripts\pythonw.exe"

rem 2. Fallback to python.exe
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY if exist "D:\workspace\venv_com\Scripts\python.exe" set "PY=D:\workspace\venv_com\Scripts\python.exe"
if not defined PY if exist "D:\workspace\venv_pub\Scripts\python.exe" set "PY=D:\workspace\venv_pub\Scripts\python.exe"
if not defined PY set "PY=python"

start "" "%PY%" main.py %*
exit /b 0
