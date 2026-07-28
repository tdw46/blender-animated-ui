@echo off
setlocal enabledelayedexpansion

set "EXTENSION_DIR=%~dp0"
if "%EXTENSION_DIR:~-1%"=="\" set "EXTENSION_DIR=%EXTENSION_DIR:~0,-1%"

if not defined BLENDER_PATH (
    set "BLENDER_PATH=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
)

if not exist "%BLENDER_PATH%" (
    echo Build failed: Blender was not found at "%BLENDER_PATH%".
    echo Set BLENDER_PATH to the Blender executable and try again.
    exit /b 1
)

for /f "tokens=2 delims== " %%A in (
    'findstr /r "^id[ ]*=" "%EXTENSION_DIR%\blender_manifest.toml"'
) do set "EXTENSION_ID=%%~A"
for /f "tokens=2 delims== " %%A in (
    'findstr /r "^version[ ]*=" "%EXTENSION_DIR%\blender_manifest.toml"'
) do set "EXTENSION_VERSION=%%~A"

if not defined EXTENSION_ID (
    echo Build failed: manifest id was not found.
    exit /b 1
)
if not defined EXTENSION_VERSION (
    echo Build failed: manifest version was not found.
    exit /b 1
)

"%BLENDER_PATH%" --background --factory-startup --python-exit-code 1 ^
    --python-expr "import ast,pathlib,re,tomllib; root=pathlib.Path(r'%EXTENSION_DIR%'); manifest=tomllib.loads((root/'blender_manifest.toml').read_text(encoding='utf-8')); source=(root/'__init__.py').read_text(encoding='utf-8'); match=re.search(r'\"version\"\s*:\s*(\([^)]+\))',source); legacy='.'.join(str(v) for v in ast.literal_eval(match.group(1))) if match else ''; expected=str(manifest['version']); assert legacy==expected, f'Version mismatch: manifest={expected}, bl_info={legacy}'"
if errorlevel 1 (
    echo Build failed: manifest and legacy bl_info versions do not match.
    exit /b 1
)

if exist "%EXTENSION_DIR%\%EXTENSION_ID%-%EXTENSION_VERSION%.zip" (
    del /q "%EXTENSION_DIR%\%EXTENSION_ID%-%EXTENSION_VERSION%.zip"
)
del /q "%EXTENSION_DIR%\%EXTENSION_ID%-%EXTENSION_VERSION%-*.zip" 2>nul

"%BLENDER_PATH%" --background --factory-startup --command extension build ^
    --source-dir "%EXTENSION_DIR%" --output-dir "%EXTENSION_DIR%" ^
    --split-platforms
if errorlevel 1 (
    echo Build failed: Blender returned a nonzero exit code.
    exit /b 1
)

set "PACKAGE_COUNT=0"
for %%P in ("%EXTENSION_DIR%\%EXTENSION_ID%-%EXTENSION_VERSION%-*.zip") do (
    if exist "%%~fP" (
        set /a PACKAGE_COUNT+=1
        echo Built: %%~fP
    )
)
if "%PACKAGE_COUNT%"=="0" (
    echo Build failed: no platform packages were created.
    exit /b 1
)

exit /b 0
