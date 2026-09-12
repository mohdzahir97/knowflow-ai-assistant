@echo off
REM ============================================================================
REM  run_frontend.bat
REM
REM  Sets up (on first run) and starts the React frontend in frontend\.
REM  Safe to re-run - every step checks whether it has already been done.
REM
REM  What this script does, in order:
REM    1. Resolves paths relative to this script (%~dp0), so it works from any
REM       working directory and handles a project path containing spaces.
REM    2. Checks Node.js and npm are on PATH.
REM    3. Runs "npm install" only when node_modules is missing or when
REM       package-lock.json has changed since the last install.
REM    4. Warns (does not fail) if the backend is not answering.
REM    5. Starts the Vite dev server.
REM ============================================================================

setlocal EnableDelayedExpansion

REM System tools are fully qualified: Git Bash and similar put their own
REM findstr/curl earlier on PATH, and those behave differently.
set "SYSDIR=%SystemRoot%\System32"
set "FINDSTR=%SYSDIR%\findstr.exe"
set "CERTUTIL=%SYSDIR%\certutil.exe"
set "CURL=%SYSDIR%\curl.exe"

set "PROJECT_DIR=%~dp0"
set "APP_DIR=%PROJECT_DIR%frontend"
set "FE_PORT=5173"
set "BACKEND_HEALTH=http://localhost:8001/health"

echo.
echo [SETUP] React frontend
echo [SETUP] Directory: %APP_DIR%
echo.

if not exist "%APP_DIR%\package.json" (
    echo [ERROR] No package.json found in "%APP_DIR%".
    echo         The React client is expected in frontend\.
    goto :fail
)

REM --- Node.js ---------------------------------------------------------------
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found on PATH.
    echo         Install Node.js 20 or newer from https://nodejs.org, then
    echo         open a new terminal so PATH is picked up.
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm was not found on PATH, although node was.
    echo         Reinstall Node.js, which bundles npm.
    goto :fail
)
for /f "tokens=*" %%v in ('node --version') do set "NODE_VERSION=%%v"
echo [OK]    Node.js %NODE_VERSION%

pushd "%APP_DIR%" || goto :fail

REM --- Dependencies ----------------------------------------------------------
REM Reinstall when node_modules is absent, or when package-lock.json differs
REM from the copy that was last installed. Hashing the lockfile is what makes
REM "dependencies changed" detectable; a bare existence check would skip the
REM install after an upgrade.
set "HASH_FILE=node_modules\.deps-hash"
set "LOCK_HASH="
if exist "package-lock.json" (
    REM The exe path is unquoted and the hash line is isolated with findstr.
    REM Quoting the exe inside for /f makes cmd treat the whole string as one
    REM command name, and "skip=1" would then discard the only line left.
    for /f "tokens=1" %%h in ('%CERTUTIL% -hashfile "package-lock.json" SHA256 2^>nul ^| %FINDSTR% /v ":"') do (
        if not defined LOCK_HASH set "LOCK_HASH=%%h"
    )
)

set "STORED_HASH="
if exist "%HASH_FILE%" set /p STORED_HASH=<"%HASH_FILE%"

set "NEEDS_INSTALL="
if not exist "node_modules" (
    set "NEEDS_INSTALL=1"
    echo [SETUP] node_modules is missing.
) else if not defined LOCK_HASH (
    REM No usable hash, so err on the side of installing rather than skipping.
    set "NEEDS_INSTALL=1"
    echo [SETUP] Could not hash package-lock.json; installing to be safe.
) else if not "%LOCK_HASH%"=="%STORED_HASH%" (
    set "NEEDS_INSTALL=1"
    echo [SETUP] package-lock.json changed since the last install.
)

if defined NEEDS_INSTALL (
    echo [SETUP] Installing dependencies - this can take a minute...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        goto :fail
    )
    REM Written only after a successful install, so a failure retries next time.
    if defined LOCK_HASH echo %LOCK_HASH%>"%HASH_FILE%"
    echo [OK]    Dependencies installed.
) else (
    echo [OK]    Dependencies already up to date.
)

REM --- Backend reachability --------------------------------------------------
REM A warning, not an error: the sign-in screen still renders, and the two
REM servers can be started in either order.
if exist "%CURL%" (
    "%CURL%" -s -f -m 3 -o nul "%BACKEND_HEALTH%" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [WARN]  The backend is not answering at %BACKEND_HEALTH%
        echo         Start it with run_backend.bat, or the app will show
        echo         connection errors once you sign in.
    ) else (
        echo [OK]    Backend is reachable.
    )
) else (
    echo [INFO]  curl.exe not found; skipped the backend check.
)

REM --- Start -----------------------------------------------------------------
echo.
echo [START] Vite dev server on http://localhost:%FE_PORT%
echo [START] Press Ctrl+C to stop.
echo.

call npm run dev -- --port %FE_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" goto :fail
endlocal & exit /b 0

:fail
echo.
echo [FAILED] Setup or startup did not complete.
REM Pause only when double-clicked, so the window does not vanish before the
REM error can be read. From a terminal, or with NO_PAUSE set, just exit.
echo %cmdcmdline% | %FINDSTR% /i /c:"/c" >nul
if not errorlevel 1 if not defined NO_PAUSE pause
endlocal & exit /b 1
