@echo off
setlocal
cd /d "%~dp0"

python -c "import PyInstaller, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Build dependencies are missing. Install them with:
    echo   python -m pip install -r requirements-build.txt
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name TallyCraft --distpath dist --workpath build\pyinstaller --specpath build desktop_launcher.py
if errorlevel 1 exit /b %errorlevel%
if not exist "dist\TallyCraft.exe" (
    echo Build did not produce dist\TallyCraft.exe
    exit /b 1
)

echo TallyCraft executable created at "%CD%\dist\TallyCraft.exe"
