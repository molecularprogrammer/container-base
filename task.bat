@echo off
setlocal enabledelayedexpansion

:: Get directory where script resides (without trailing backslash)
set "DIRECTORY=%~dp0"
if "%DIRECTORY:~-1%"=="\" set "DIRECTORY=%DIRECTORY:~0,-1%"

:: Set environment variables
set "HOST_PWD=%DIRECTORY%"
set "HOST_UID=1000"
set "HOST_GID=1000"

:: Check for --attach or -a flag
set "ACTION=run"
if "%~1"=="--attach" (
    set "ACTION=exec"
    shift
) else if "%~1"=="-a" (
    set "ACTION=exec"
    shift
)

:: Collect remaining arguments
set "ARGS=%1"
:loop
shift
if not "%~1"=="" (
    set "ARGS=!ARGS! %1"
    goto loop
)

:: Execute docker compose based on action
if "%ACTION%"=="run" (
    if "%ARGS%"=="" set "ARGS=default"
    docker compose --file "%DIRECTORY%\compose.yaml" --project-directory "%DIRECTORY%" run --rm --service-ports container-base task !ARGS!
) else (
    if "%ARGS%"=="" set "ARGS=bash"
    docker compose --file "%DIRECTORY%\compose.yaml" --project-directory "%DIRECTORY%" exec container-base !ARGS!
)