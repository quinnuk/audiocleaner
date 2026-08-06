@echo off
echo === AudioCleaner build ===
echo.
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