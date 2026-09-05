@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM Complete Build Script for RivalNxt
REM This script builds all components from scratch for new users:
REM - Installs npm dependencies
REM - Builds Rust UE Tools with PyO3 bindings
REM - Creates Python wrapper module
REM - Builds Python backend with PyInstaller
REM - Builds Tauri application (frontend + desktop app)
REM ============================================================================

echo.
echo ============================================================================
echo                    RivalNxt Complete Build Script
echo ============================================================================
echo.

REM Check if we're in the correct directory
if not exist "src-tauri" (
    echo ERROR: src-tauri directory not found!
    echo Please run this script from the project root directory.
    exit /b 1
)

REM Optional developer tool; not a build dependency. It printed "'graphify' is
REM not recognized" on every build of a machine that does not have it, two
REM lines above the output anyone actually reads.
where graphify >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Updating Graphify knowledge graph...
    graphify update .
)

REM ============================================================================
REM Pin the interpreter to the project virtualenv.
REM
REM This script used to call bare `python` and `pip`, so PyInstaller ran under
REM whatever came first on PATH. When that is a different interpreter -- a
REM system install, or the Microsoft Store stub -- the bundle comes out missing
REM whatever the venv had and PATH did not, silently: 1.0.0 shipped without
REM Pillow, and every image the app tried to downscale logged
REM "No module named 'PIL'" at runtime. Nothing failed the build.
REM ============================================================================
set "VENV_SCRIPTS=%CD%\.venv\Scripts"
set "PYTHON=%VENV_SCRIPTS%\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: virtualenv not found at %PYTHON%
    echo Create it first:
    echo     py -3 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)
REM maturin, pyinstaller and ruff live here too, and none of them are on PATH
REM unless the venv has been activated. Putting it first is what activation
REM does; doing it here means the script does not depend on how it was started.
set "PATH=%VENV_SCRIPTS%;%PATH%"
echo Using interpreter: %PYTHON%

REM Same story for Rust. rustup usually puts cargo on PATH, but it is not on
REM every machine -- it was on neither the user nor the system PATH of the one
REM 1.0.0 was built on, and maturin failed with "Do you have cargo in your
REM PATH?". Look where rustup installs it before giving up.
where cargo >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
        set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
        echo Added %USERPROFILE%\.cargo\bin to PATH
    ) else (
        echo ERROR: cargo not found. Install Rust from https://rustup.rs
        exit /b 1
    )
)

REM Get version from package.json
echo.
echo Detecting version...
for /f "delims=" %%v in ('node -p "require('./package.json').version"') do set APP_VERSION=%%v
echo Detected version: !APP_VERSION!

REM ============================================================================
echo [1/6] Installing npm dependencies...
echo ============================================================================
echo Checking for node_modules...
if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: npm install failed!
        exit /b 1
    )
    echo ✓ npm dependencies installed successfully
) else (
    echo ✓ node_modules already exists, skipping npm install
)

REM ============================================================================
echo.
echo [2/6] Building PyO3 Module with Maturin...
echo ============================================================================
cd src-tauri\src\rust-ue-tools

echo 📦 Building Python wheel with Maturin...
echo Current directory: %cd%

REM Check if required files exist
if not exist "Cargo.toml" (
    echo ❌ Cargo.toml not found in current directory!
    cd ..\..\..
    exit /b 1
)

if not exist "pyproject.toml" (
    echo ❌ pyproject.toml not found in current directory!
    cd ..\..\..
    exit /b 1
)

echo ✅ Cargo.toml and pyproject.toml found

REM Check workspace members
if exist "repak-rivals" (
    echo ✅ repak-rivals submodule found
) else (
    echo ❌ repak-rivals submodule not found! Git submodules may not be initialized.
    echo Run: git submodule update --init --recursive
    cd ..\..\..
    exit /b 1
)

REM Build using Maturin
echo Building wheel with --release --features pyo3...
maturin build --release --features pyo3
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Maturin build failed
    cd ..\..\..
    exit /b 1
)

echo Finding built wheel...
for /f "delims=" %%i in ('dir /b /s target\wheels\*.whl 2^>nul ^| findstr /r ".*"') do set WHEEL_PATH=%%i

if not defined WHEEL_PATH (
    echo ❌ No wheel file found in target\wheels!
    cd ..\..\..
    exit /b 1
)

echo ✅ Found wheel: %WHEEL_PATH%

REM ============================================================================
echo.
echo [3/6] Installing and extracting wheel for PyInstaller...
echo ============================================================================

echo Installing wheel...
"%PYTHON%" -m pip install "%WHEEL_PATH%" --force-reinstall
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Failed to install wheel
    cd ..\..\..
    exit /b 1
)

echo Verifying installation...
"%PYTHON%" -c "import rust_ue_tools; print('rust_ue_tools imported successfully!')"
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Failed to import rust_ue_tools module!
    cd ..\..\..
    exit /b 1
)

echo Extracting wheel for PyInstaller bundling...
cd ..\..\..
if exist extracted_wheel rmdir /s /q extracted_wheel
mkdir extracted_wheel

REM Extract wheel using PowerShell
powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%WHEEL_PATH%', 'extracted_wheel')"

REM Manually copy Oodle DLL to the extracted package
echo Copying Oodle DLL...
set DLL_PATH=src-tauri\src\rust-ue-tools\repak-rivals\oo2core_9_win64.dll
if not exist "%DLL_PATH%" (
    echo ❌ Oodle DLL not found at: %DLL_PATH%
    exit /b 1
)
copy "%DLL_PATH%" "extracted_wheel\rust_ue_tools\" >nul

echo ✅ Wheel extracted successfully to extracted_wheel\
dir extracted_wheel
dir extracted_wheel\rust_ue_tools.

REM ============================================================================
echo.
echo [4/6] Building Python backend with PyInstaller...
echo ============================================================================
echo Cleaning previous builds...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Fail here rather than shipping a bundle without them. Pillow is the one
REM that actually went missing; every import below is used at runtime and is
REM reached only from inside a function, so nothing else would notice.
echo Checking build dependencies...
"%PYTHON%" -c "import PIL, fastapi, uvicorn, requests, rust_ue_tools"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: the virtualenv is missing a runtime dependency.
    echo     "%PYTHON%" -m pip install -r requirements.txt
    exit /b 1
)

echo Building backend executable using spec file...
"%PYTHON%" -m PyInstaller --noconfirm --clean rivalnxt_backend_merged.spec
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python backend build failed!
    exit /b 1
)

if not exist dist\rivalnxt_backend.exe (
    echo ERROR: Backend executable not found in dist directory!
    exit /b 1
)

REM PyInstaller reports a missing module as a warning and exits 0, so the only
REM way to know Pillow made it in is to ask the bundle itself.
echo Verifying the bundle can import Pillow...
"%PYTHON%" scripts\verify_bundle.py dist\rivalnxt_backend.exe
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: the built backend is missing a module it needs at runtime.
    exit /b 1
)
echo ✓ Python backend built successfully

REM ============================================================================
echo.
echo [5/6] Copying backend to Tauri sidecars...
echo ============================================================================
if not exist src-tauri\sidecars mkdir src-tauri\sidecars
copy /Y dist\rivalnxt_backend.exe src-tauri\sidecars\rivalnxt_backend-x86_64-pc-windows-msvc.exe >nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to copy backend executable!
    exit /b 1
)
echo ✓ Backend copied to sidecars directory

REM ============================================================================
echo.
echo [6/6] Building Tauri application...
echo ============================================================================
echo This will build the frontend and Tauri application...
call npm run tauri:build
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Tauri build failed!
    exit /b 1
)
echo ✓ Tauri application built successfully

REM ============================================================================
echo.
echo ============================================================================
echo                         Build Complete!
echo ============================================================================
echo.
echo Generated files:
echo   - Python Backend:  dist\rivalnxt_backend.exe
echo   - Tauri App:       src-tauri\target\release\rivalnxt.exe
echo   - NSIS Installer:  src-tauri\target\release\bundle\nsis\RivalNxt_!APP_VERSION!_x64-setup.exe
echo.
echo ============================================================================

REM Display file sizes
echo.
echo File sizes:
if exist dist\rivalnxt_backend.exe (
    for %%A in (dist\rivalnxt_backend.exe) do (
        set /a size_mb=%%~zA/1048576
        echo   rivalnxt_backend.exe: !size_mb! MB
    )
)
if exist src-tauri\target\release\rivalnxt.exe (
    for %%A in (src-tauri\target\release\rivalnxt.exe) do (
        set /a size_mb=%%~zA/1048576
        echo   rivalnxt.exe: !size_mb! MB
    )
)
if exist src-tauri\target\release\bundle\nsis\RivalNxt_!APP_VERSION!_x64-setup.exe (
    for %%A in (src-tauri\target\release\bundle\nsis\RivalNxt_!APP_VERSION!_x64-setup.exe) do (
        set /a size_mb=%%~zA/1048576
        echo   RivalNxt_!APP_VERSION!_x64-setup.exe: !size_mb! MB
    )
)

echo.
echo Build completed successfully at %date% %time%
echo.
echo 📋 What was built:
echo   1. Rust UE Tools library with PyO3 bindings
echo   2. Python wrapper module for Rust library
echo   3. Python backend executable (PyInstaller)
echo   4. Tauri desktop application
echo   5. NSIS installer for Windows
echo.