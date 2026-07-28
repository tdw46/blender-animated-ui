@echo off
setlocal
cd /d "%~dp0\.."
uv run ruff check .
if errorlevel 1 exit /b 1
uv run ruff format --check .
if errorlevel 1 exit /b 1
python -m compileall -q .
exit /b %errorlevel%
