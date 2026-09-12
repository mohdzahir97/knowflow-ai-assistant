@echo off
REM ============================================================================
REM  run_backend.bat
REM
REM  Sets up (on first run) and starts the backend server for this project.
REM  Safe to re-run at any time - every step below checks whether it has
REM  already been done and skips it if so, so a second run is fast.
REM
REM  What this script does, in order:
REM    1. Resolves all paths relative to this script's own location (via
REM       %~dp0), so it works no matter what folder you run it from, and
REM       correctly handles a project path that contains spaces.
REM    2. Locates the backend folder automatically (tries "backend", then
REM       falls back to the current folder if this script was copied
REM       inside an existing backend project).
REM    3. Creates a Python virtual environment (.venv) if one doesn't
REM       already exist. Existing environments are never deleted or
REM       recreated.
REM    4. Installs the runtime dependency set (requirements.txt, falling
REM       back to pyproject.toml) - but only if any dependency file changed
REM       since the last successful install. The cache key is a SHA-256
REM       fingerprint of every dependency file present (stored inside the
REM       venv), so an edit to a transitively-included file can't slip by.
REM       Dev/test extras are deliberately NOT installed by this script.
REM    5. Copies .env.example to .env on first run, if .env is missing and
REM       an example file is present.
REM    6. Applies database migrations via Alembic, if this backend uses it.
REM    7. Detects which port the server will bind to and warns (without
REM       aborting) if something is already listening on it.
REM    8. Detects the web framework (FastAPI / Flask / Django / other) and
REM       starts the server with the matching command.
REM
REM  Exit codes: 0 on success, 1 on any setup failure (see the printed
REM  [ERROR] message for the reason).
REM ============================================================================

setlocal EnableDelayedExpansion

REM Qualify system utilities with their full path. Some developer machines
REM have Git Bash / WSL / MSYS2 / Cygwin tools earlier on PATH than
REM %SystemRoot%\System32, which silently shadows commands like "findstr"
REM or "timeout" with a same-named Unix tool that takes different flags.
set "SYS32=%SystemRoot%\System32"
set "FINDSTR=%SYS32%\findstr.exe"
set "CERTUTIL=%SYS32%\certutil.exe"
set "NETSTAT=%SYS32%\netstat.exe"
set "WHERE=%SYS32%\where.exe"

REM If this script was double-clicked, Explorer runs it as `cmd /c "...bat"`
REM and the window closes the instant the script ends - which would hide any
REM error message. Detect that and pause on failure so the message stays
REM readable. Set NO_PAUSE=1 to suppress this (for CI/automation).
set "PAUSE_ON_ERROR="
echo %cmdcmdline% | %FINDSTR% /i /c:"%~nx0" >nul 2>nul
if not errorlevel 1 set "PAUSE_ON_ERROR=1"
if defined NO_PAUSE set "PAUSE_ON_ERROR="

set "PROJECT_ROOT=%~dp0"

echo.
echo ================================================================
echo  Backend Startup
echo ================================================================
echo.

REM --- Locate the backend folder ---
if exist "%PROJECT_ROOT%backend\" (
    set "BACKEND_DIR=%PROJECT_ROOT%backend"
) else (
    set "BACKEND_DIR=%PROJECT_ROOT%"
)

if not exist "%BACKEND_DIR%\" (
    echo [ERROR] Could not locate a backend folder under "%PROJECT_ROOT%".
    goto :fail
)

set "VENV_DIR=%BACKEND_DIR%\.venv"

REM --- Python must be available on PATH ---
%WHERE% python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and make sure "Add python.exe to PATH" was checked during install.
    goto :fail
)

pushd "%BACKEND_DIR%" || (
    echo [ERROR] Could not switch to backend folder "%BACKEND_DIR%".
    goto :fail
)

echo [INFO] Backend folder: %BACKEND_DIR%

REM ----------------------------------------------------------------------
REM  Step 1 - virtual environment (create only if missing)
REM ----------------------------------------------------------------------
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo [OK]   Virtual environment already exists ^(.venv^).
) else (
    echo [SETUP] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        goto :fail
    )
    echo [OK]   Virtual environment created.
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate the virtual environment.
    goto :fail
)

REM ----------------------------------------------------------------------
REM  Step 2 - pick the dependency file to install from
REM ----------------------------------------------------------------------
REM  This is a *run* script, so it installs the runtime dependency set
REM  (requirements.txt), not a dev/test superset like requirements-dev.txt.
REM  Run `pip install -r requirements-dev.txt` yourself when you need the
REM  test tooling.
set "DEP_FILE="
if exist "requirements.txt" (
    set "DEP_FILE=requirements.txt"
) else if exist "pyproject.toml" (
    set "DEP_FILE=pyproject.toml"
)

if not defined DEP_FILE (
    echo [ERROR] No requirements.txt or pyproject.toml found in "%BACKEND_DIR%".
    goto :fail
)

echo [INFO] Using dependency file: %DEP_FILE%

REM ----------------------------------------------------------------------
REM  Step 3 - install dependencies only if they changed since last install
REM ----------------------------------------------------------------------
REM  The cache key fingerprints EVERY dependency file present, not just the
REM  one being installed. Requirements files commonly include each other
REM  (e.g. requirements-dev.txt starts with "-r requirements.txt"), so
REM  hashing only one file would let an edit to another slip through
REM  unnoticed and silently skip a needed install.
set "HASH_FILE=%VENV_DIR%\.deps.hash"
set "DEP_FINGERPRINT="
for %%F in (requirements.txt requirements-dev.txt pyproject.toml) do (
    if exist "%%F" (
        set "FILE_HASH="
        for /f "tokens=1" %%H in ('%CERTUTIL% -hashfile "%%F" SHA256 2^>nul ^| %FINDSTR% /v ":"') do (
            if not defined FILE_HASH set "FILE_HASH=%%H"
        )
        set "DEP_FINGERPRINT=!DEP_FINGERPRINT!!FILE_HASH!"
    )
)

set "OLD_HASH="
if exist "%HASH_FILE%" set /p OLD_HASH=<"%HASH_FILE%"

REM Only skip when we actually computed a fingerprint. If certutil is
REM unavailable or blocked, DEP_FINGERPRINT is empty - and on a fresh venv
REM OLD_HASH is empty too, so a naive comparison would match and skip the
REM install entirely, leaving nothing installed.
set "SKIP_INSTALL="
if defined DEP_FINGERPRINT if "!DEP_FINGERPRINT!"=="!OLD_HASH!" set "SKIP_INSTALL=1"

if defined SKIP_INSTALL (
    echo [OK]   Dependencies already up to date, skipping install.
) else (
    echo [SETUP] Upgrading pip...
    python -m pip install --upgrade pip --quiet
    echo [SETUP] Installing dependencies from %DEP_FILE% ^(this may take a while^)...
    if "%DEP_FILE:~-4%"==".txt" (
        pip install -r "%DEP_FILE%"
    ) else (
        pip install .
    )
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed - see the output above.
        goto :fail
    )
    if defined DEP_FINGERPRINT (
        > "%HASH_FILE%" echo !DEP_FINGERPRINT!
    )
    echo [OK]   Dependencies installed.
)

REM ----------------------------------------------------------------------
REM  Step 4 - first-run .env bootstrap
REM ----------------------------------------------------------------------
if not exist ".env" (
    if exist ".env.example" (
        echo [SETUP] No .env found - creating one from .env.example.
        echo         Edit backend\.env and fill in any required API keys.
        copy /y ".env.example" ".env" >nul
    )
)

REM ----------------------------------------------------------------------
REM  Step 5 - database migrations ^(Alembic^), if this project uses them
REM ----------------------------------------------------------------------
if exist "alembic.ini" (
    echo [SETUP] Applying database migrations...
    alembic upgrade head
    if errorlevel 1 (
        echo [ERROR] Database migration failed - see the output above.
        goto :fail
    )
)
if exist "manage.py" (
    echo [SETUP] Applying Django migrations...
    python manage.py migrate
)

REM ----------------------------------------------------------------------
REM  Step 6 - detect the port and warn ^(don't block^) if it's already busy
REM ----------------------------------------------------------------------
set "BACKEND_PORT=8001"
if exist ".env" (
    for /f "tokens=2 delims==" %%P in ('%FINDSTR% /b /i "PORT=" ".env" 2^>nul') do set "BACKEND_PORT=%%P"
)

%NETSTAT% -ano | %FINDSTR% /r /c:"LISTENING" | %FINDSTR% /c:":%BACKEND_PORT% " >nul
if not errorlevel 1 (
    echo [WARNING] Port %BACKEND_PORT% is already in use by another process.
    echo           The server below may fail to start, or you may already
    echo           have a backend instance running.
)

REM ----------------------------------------------------------------------
REM  Step 7 - detect the framework and start the server
REM ----------------------------------------------------------------------
set "FRAMEWORK=unknown"
if exist "manage.py" set "FRAMEWORK=django"

if "%FRAMEWORK%"=="unknown" if exist "app\main.py" (
    %FINDSTR% /c:"FastAPI(" "app\main.py" >nul 2>nul
    if not errorlevel 1 set "FRAMEWORK=fastapi-app-main"
)
if "%FRAMEWORK%"=="unknown" if exist "main.py" (
    %FINDSTR% /c:"FastAPI(" "main.py" >nul 2>nul
    if not errorlevel 1 set "FRAMEWORK=fastapi-main"
    %FINDSTR% /c:"Flask(" "main.py" >nul 2>nul
    if not errorlevel 1 set "FRAMEWORK=flask-main"
)
if "%FRAMEWORK%"=="unknown" if exist "app.py" (
    %FINDSTR% /c:"Flask(" "app.py" >nul 2>nul
    if not errorlevel 1 set "FRAMEWORK=flask-app"
    %FINDSTR% /c:"FastAPI(" "app.py" >nul 2>nul
    if not errorlevel 1 set "FRAMEWORK=fastapi-app"
)

echo.
echo [START] Detected framework: %FRAMEWORK%
echo [START] Backend will listen on http://localhost:%BACKEND_PORT%
echo.

REM --no-server-header stops uvicorn appending its own "server: uvicorn"
REM banner, which it adds after the app responds and so cannot be replaced
REM from application middleware.
if "%FRAMEWORK%"=="fastapi-app-main" (
    uvicorn app.main:app --reload --host 0.0.0.0 --port %BACKEND_PORT% --no-server-header
) else if "%FRAMEWORK%"=="fastapi-main" (
    uvicorn main:app --reload --host 0.0.0.0 --port %BACKEND_PORT% --no-server-header
) else if "%FRAMEWORK%"=="fastapi-app" (
    uvicorn app:app --reload --host 0.0.0.0 --port %BACKEND_PORT% --no-server-header
) else if "%FRAMEWORK%"=="flask-main" (
    set "FLASK_APP=main.py"
    flask run --port %BACKEND_PORT%
) else if "%FRAMEWORK%"=="flask-app" (
    set "FLASK_APP=app.py"
    flask run --port %BACKEND_PORT%
) else if "%FRAMEWORK%"=="django" (
    python manage.py runserver 0.0.0.0:%BACKEND_PORT%
) else (
    echo [ERROR] Could not automatically detect the backend framework.
    echo         Open run_backend.bat and add the correct start command
    echo         for this project near the end of the file.
    goto :fail
)

set "SERVER_EXIT_CODE=%errorlevel%"
popd
endlocal & exit /b %SERVER_EXIT_CODE%

REM ----------------------------------------------------------------------
REM  Single failure path. Every [ERROR] above jumps here so the pause (and
REM  the popd, if we already changed directory) live in exactly one place.
REM ----------------------------------------------------------------------
:fail
popd 2>nul
echo.
if defined PAUSE_ON_ERROR pause
endlocal & exit /b 1
