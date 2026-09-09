@echo off
setlocal enabledelayedexpansion
title BigQuery Routine Explorer - Community Edition
cd /d "%~dp0"

REM ============================================================
REM  BigQuery Routine Explorer (Community Edition) - launcher
REM  Double-click this file to RUN the app.
REM  Double-click it again to STOP the app.
REM ============================================================
REM  Community Edition limits:
REM    - 1 BigQuery project
REM    - Max 50 routines per load
REM    - Graph traversal depth capped at 3
REM ============================================================

REM ---------- CONFIG ----------
set "PROJECT_LIST="
set "FALLBACK_LOCATION="
set "HOST_PORT=8080"
REM DATASET_FILTER is disabled in Community Edition
REM REFRESH_ON_START is disabled in Community Edition (use manual refresh in UI)
set "REFRESH_ON_START="
REM --------------------------------------------------------

set "IMG=routine-explorer-community"
set "CONTAINER=rex-community"

REM ---------- Toggle: stop the app if it is already running ----------
docker inspect !CONTAINER! >nul 2>&1
if not errorlevel 1 (
    echo Stopping the running Community Edition app...
    docker stop !CONTAINER! >nul 2>&1
    docker rm !CONTAINER! >nul 2>&1
    echo App stopped.
    echo.
    pause
    exit /b 0
)

REM ---------- 1. Ensure the secrets folder and key exist ----------
if not exist "secrets" (
    echo Creating the "secrets" folder...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_secrets.ps1"
    echo.
    echo Put your read-only service-account JSON in the "secrets" folder
    echo under any filename, then double-click this launcher again.
    echo.
    pause
    exit /b 1
)
set "KEY_FILE="
for %%F in ("secrets\*.json") do if not defined KEY_FILE set "KEY_FILE=%%F"
if not defined KEY_FILE (
    echo No service-account key ^(*.json^) found in the "secrets" folder yet.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_secrets.ps1"
    echo.
    echo Put your read-only service-account JSON in the "secrets" folder
    echo under any filename ^(no need to rename it to key.json^), then
    echo double-click this launcher again.
    echo.
    pause
    exit /b 1
)
echo Using key file: !KEY_FILE!

REM ---------- 1b. Auto-detect the target project from the key ----------
if "!PROJECT_LIST!"=="" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try { (Get-Content -Raw '!KEY_FILE!' | ConvertFrom-Json).project_id } catch { '' }"`) do set "PROJECT_LIST=%%P"
)
if "!PROJECT_LIST!"=="" (
    echo Could not determine which BigQuery project to use from !KEY_FILE!.
    echo Set PROJECT_LIST manually near the top of this script and run it again.
    echo.
    pause
    exit /b 1
)
echo Using BigQuery project: !PROJECT_LIST!
echo.
echo NOTE: Community Edition supports 1 project only.
echo.

REM ---------- 2. Ensure the image is built ----------
docker image inspect !IMG! >nul 2>&1
if errorlevel 1 (
    echo Building the Community Edition image - first run only, this can take a minute...
    docker build -t !IMG! .
    if errorlevel 1 (
        echo.
        echo Docker build failed. Make sure Docker Desktop is running.
        echo.
        pause
        exit /b 1
    )
)

REM ---------- 3. Assemble the environment variables ----------
set "ENVS=-e BQ_PROJECTS=!PROJECT_LIST!"
if not "!FALLBACK_LOCATION!"=="" set "ENVS=!ENVS! -e BQ_LOCATION=!FALLBACK_LOCATION!"

REM ---------- 4. Pick a free host port (increments if busy) ----------
set "PORT=!HOST_PORT!"
:portloop
netstat -ano | findstr /R /C:":!PORT! .*LISTENING" >nul
if errorlevel 1 goto portfree
set /a PORT+=1
goto portloop
:portfree
echo Using host port !PORT! ^(configured !HOST_PORT!^)

REM ---------- 5. Launch the container ----------
echo Starting the Community Edition app...
docker run -d --name !CONTAINER! -p !PORT!:8080 -v "!CD!\secrets:/secrets:ro" !ENVS! !IMG! >nul 2>&1
if errorlevel 1 (
    echo.
    echo Could not start the container. Is Docker Desktop running?
    echo.
    pause
    exit /b 1
)

REM ---------- 6. Wait for the app to respond, then open the browser ----------
set "URL=http://localhost:!PORT!/"
set "HEALTHURL=!URL!healthz"
echo Waiting for the app to come up...
set /a TRIES=0
:waitloop
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri '!HEALTHURL!' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto up
set /a TRIES+=1
if !TRIES! geq 30 goto timeout
timeout /t 1 >nul
goto waitloop
:up
echo Opening !URL!
start "" "!URL!"
echo.
echo Running at !URL!
echo Keep this window open, or close it now. Double-click the launcher again to stop the app.
echo.
echo ============================================
echo  Community Edition limitations:
echo    - Max 50 routines per load
echo    - 1 BigQuery project
echo    - Graph depth capped at 3
echo  Upgrade to Full Edition: https://lemonsqueezy.com/products/bigquery-routine-explorer
echo ============================================
echo.
pause >nul
exit /b 0

:timeout
echo The app did not respond in time. Check that Docker is running.
echo Try opening !URL! manually.
echo.
pause
exit /b 1