@echo off
REM Offline UI Tester - Windows baslatici. URL'i her zaman sorar.
REM Kullanim:
REM   start.bat                 -> URL sorar
REM   start.bat --no-vision     -> URL sorar + ek bayraklar gecer

cd /d "%~dp0"

set /p url="URL: "
uv run python run.py --url "%url%" %*
