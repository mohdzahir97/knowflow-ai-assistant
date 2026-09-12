@echo off
REM ============================================================================
REM  start_all.bat
REM
REM  Master launcher for the full-stack project. Starts the backend and
REM  frontend each in their own Command Prompt window (so you can see each
REM  server's logs separately, and stop either one independently by closing
REM  its window or pressing Ctrl+C in it).
REM
REM  This script does NOT duplicate the setup logic - run_backend.bat and
REM  run_frontend.bat each handle their own virtual environment creation,
REM  dependency installation, and framework detection. This script's only
REM  job is to launch both, in the right order, with clear status messages.
REM
REM  All paths are resolved relative to this script's own location (%~dp0),
REM  so it works regardless of the folder it's run from and correctly
REM  handles a project path that contains spaces.
REM ============================================================================

setlocal EnableDelayedExpansion

REM Qualify system utilities with their full path. Some developer machines
REM have Git Bash / WSL / MSYS2 / Cygwin tools earlier on PATH than
REM %SystemRoot%\System32, which silently shadows commands like "ping"
REM with a same-named Unix tool that takes different flags.
set "SYS32=%SystemRoot%\System32"

set "PROJECT_ROOT=%~dp0"
set "BACKEND_SCRIPT=%PROJECT_ROOT%run_backend.bat"
set "FRONTEND_SCRIPT=%PROJECT_ROOT%run_frontend.bat"

echo.
echo ================================================================
echo  AI Company Knowledge Assistant - Full Stack Launcher
echo ================================================================
echo.

if not exist "%BACKEND_SCRIPT%" (
    echo [ERROR] Could not find "%BACKEND_SCRIPT%".
    echo         Make sure run_backend.bat sits next to this script.
    pause
    exit /b 1
)
if not exist "%FRONTEND_SCRIPT%" (
    echo [ERROR] Could not find "%FRONTEND_SCRIPT%".
    echo         Make sure run_frontend.bat sits next to this script.
    pause
    exit /b 1
)

echo [1/3] Launching backend in a new window...
echo       ^(first run may take a few minutes while dependencies install^)
start "Backend Server" cmd /k call "%BACKEND_SCRIPT%"

echo [2/3] Waiting for the backend to come up before starting the frontend...
REM "timeout.exe" refuses to run whenever stdin isn't an interactive console
REM (redirected output, Task Scheduler, CI, etc.) and aborts with an error
REM in that case, so a ping-based delay is used instead - it works
REM identically in every execution context. Loopback ping is not affected
REM by firewalls since traffic never leaves the machine.
"%SYS32%\ping.exe" -n 9 127.0.0.1 >nul

echo [3/3] Launching frontend in a new window...
start "Frontend Server" cmd /k call "%FRONTEND_SCRIPT%"

echo.
echo ================================================================
echo  Both servers are starting in their own windows.
echo    - Backend window : shows API logs; close it or press Ctrl+C
echo                       there to stop the backend.
echo    - Frontend window: shows UI logs; close it or press Ctrl+C
echo                       there to stop the frontend.
echo  This launcher window can be closed safely - it does not need
echo  to stay open for the servers to keep running.
echo ================================================================
echo.

endlocal
