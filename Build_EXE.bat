@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo  Building BCM Wishlist (one .exe, Nuitka - takes a few minutes)
echo ================================================
echo  Python is only needed to BUILD the exe. The finished exe
echo  is one file; the PC running it needs only Npcap.
echo.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^) and run this file again.
  echo.
  echo Or skip this: upload this folder to GitHub and run the "Build Windows exe" action,
  echo it builds the exe for you ^(see README.md^).
  pause
  exit /b 1
)

%PY% -m pip install --upgrade pip
if errorlevel 1 goto failed
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto failed

copy /Y BCMWishlist.pyw BCMWishlist_app.py >nul
%PY% -m nuitka --onefile --assume-yes-for-downloads --windows-console-mode=disable ^
  --enable-plugin=tk-inter --output-dir=dist --output-filename=BCMWishlist.exe ^
  --windows-icon-from-ico=bcm_icon.ico ^
  --company-name=bwu113 --product-name="BCM Wishlist" --file-description="BCM Wishlist" ^
  --file-version=1.0.0.0 --product-version=1.0.0.0 ^
  --include-data-files=aion2_items.csv=aion2_items.csv ^
  --include-data-files=bcm_icon.ico=bcm_icon.ico --include-data-files=bcm_icon.png=bcm_icon.png ^
  --include-data-files=found_chime.wav=found_chime.wav ^
  BCMWishlist_app.py
if errorlevel 1 goto failed

echo.
echo ================================================
echo  Done:  dist\BCMWishlist.exe
echo ================================================
echo  This single file is all you need to share - no Python or
echo  anything else. The PC only needs Npcap (https://npcap.com,
echo  keep "WinPcap API-compatible mode" ticked).
echo  Windows SmartScreen may warn about an unsigned program the
echo  first time: "More info" - "Run anyway".
echo.
pause
exit /b 0

:failed
echo.
echo Build failed. Review the error above.
pause
exit /b 1
