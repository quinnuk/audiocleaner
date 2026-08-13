@echo off
echo === AudioCleaner build ===
echo.

if not exist "MediaInfo.exe" goto missing_mediainfo
if not exist "LIBCURL.DLL" goto missing_mediainfo
goto have_mediainfo

:missing_mediainfo
echo MediaInfo.exe and/or LIBCURL.DLL not found in this folder.
echo AudioCleaner.spec bundles both into the built exe, so they must be
echo present here before building (they are gitignored on purpose --
echo see .gitignore -- so a fresh clone won't have them yet).
echo.
echo Download the MediaInfo CLI (Windows, "CLI" edition) from:
echo   https://mediaarea.net/en/MediaInfo/Download/Windows
echo Unzip it and copy MediaInfo.exe + LIBCURL.DLL into this folder,
echo then run build.bat again.
pause
exit /b 1

:have_mediainfo
echo Installing PyInstaller (skips if already installed)...
pip install pyinstaller
if errorlevel 1 (
    echo Failed to install PyInstaller. Is pip on your PATH?
    pause
    exit /b 1
)

echo.
echo Clearing old PyInstaller onefile extraction caches from %TEMP%...
for /d %%D in ("%TEMP%\_MEI*") do (
    echo   removing %%D
    rmdir /s /q "%%D"
)

echo.
echo Building AudioCleaner.exe from AudioCleaner.spec...
python -m PyInstaller --noconfirm AudioCleaner.spec
if errorlevel 1 (
    echo Build failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo Done. Your exe is at: dist\AudioCleaner.exe
echo You can copy that single file anywhere and run it directly.
pause