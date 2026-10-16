@echo off
setlocal
cd /d "%~dp0"
rem Runs the program from the .py files (no exe). Needs Python 3.10+, Scapy (pip) and Npcap.
rem Right-click > Run as administrator if capture needs it.
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/ first.
  pause
  exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
start "" %PY% BCMWishlist.pyw
