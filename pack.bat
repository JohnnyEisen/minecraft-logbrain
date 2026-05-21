@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

echo ============================================
echo MCA Brain System - Optimized EXE Builder
echo ============================================
echo.

:: 1. Detect Python
set "PYTHON_CMD=python"
py -0 >nul 2>&1
if %errorlevel% equ 0 (
    py -3.13 --version >nul 2>&1
    if !errorlevel! equ 0 set "PYTHON_CMD=py -3.13"
)

%PYTHON_CMD% --version
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    pause & exit /b 1
)

:: 2. Ensure PyInstaller
%PYTHON_CMD% -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    %PYTHON_CMD% -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller.
        pause & exit /b 1
    )
)

:: 3. Clean old builds (keep .spec)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: 4. Collect optional libs for Brain DLC users
echo [INFO] Checking for optional AI/ML libraries for DLC package...
if exist lib rmdir /s /q lib
%PYTHON_CMD% "scripts/setup/collect_libs.py"
if %errorlevel% neq 0 (
    echo [WARN] collect_libs.py failed (non-fatal).
)

:: 5. Build optimized EXE (no AI/ML bloat)
echo.
echo [INFO] Building core EXE (PyInstaller)...
echo [INFO] Note: AI/ML libraries (torch, transformers, etc.) are EXCLUDED.
echo [INFO] They are available as optional Brain DLC.
echo.
%PYTHON_CMD% -m PyInstaller MCA_Brain_System_v1.0.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] Build failed!
    pause & exit /b 1
)

:: 6. Collect optional libs for DLC package
if exist lib (
    echo [INFO] Copying lib to dist for DLC package...
    xcopy /E /I /Y lib dist\MCA_Brain_System_v1.2\lib >nul
    rmdir /s /q lib
)

:: 7. Final clean
if exist build_assets rmdir /s /q build_assets

echo.
echo ============================================
echo BUILD SUCCESS!
echo Output: dist\MCA_Brain_System_v1.2\
echo Expected size: ~200-400 MB (core EXE)
echo.
echo To use AI Brain features, install DLC:
echo   pip install torch transformers
echo ============================================
pause