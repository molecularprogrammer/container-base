@echo off
setlocal

:: Check for Administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
echo [ERROR] Please right-click this script and select "Run as administrator".
pause
exit /b 1
)

echo [INFO] Enabling Windows Subsystem for Linux (WSL 2)...
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart

echo [INFO] Enabling Virtual Machine Platform...
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

echo [INFO] Downloading Docker Desktop Installer...
powershell -Command "Invoke-WebRequest -Uri 'https://desktop.docker.com/win/main/amd64/Docker%%20Desktop%%20Installer.exe' -OutFile '%TEMP%\DockerDesktopInstaller.exe'"

if not exist "%TEMP%\DockerDesktopInstaller.exe" (
echo [ERROR] Failed to download Docker Desktop installer.
pause
exit /b 1
)

echo [INFO] Installing Docker Desktop (using WSL 2 backend)...
:: --quiet or silent install flags can vary, but standard installer accepts specific arguments
"%TEMP%\DockerDesktopInstaller.exe" install --accept-license --backend=wsl-2

echo [INFO] Adding current user (%USERNAME%) to the docker-users group...
net localgroup docker-users "%USERNAME%" /add >nul 2>&1
if %errorLevel% equ 0 (
echo [SUCCESS] User added to docker-users group.
) else (
echo [WARNING] Could not automatically add user to docker-users group. You may need to do this manually.
)

echo [INFO] Cleaning up installer...
del "%TEMP%\DockerDesktopInstaller.exe"

echo ========================================================
echo Docker Desktop installation sequence completed!
echo IMPORTANT: You must restart your computer for WSL 2 kernel
echo updates and virtualization changes to fully take effect.
echo ========================================================
pause