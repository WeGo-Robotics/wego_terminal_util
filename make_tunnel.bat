@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM ===== 0. Help =====
set "ARG1=%~1"
if /i "%ARG1%"=="?"      goto :SHOW_HELP
if /i "%ARG1%"=="h"      goto :SHOW_HELP
if /i "%ARG1%"=="-h"     goto :SHOW_HELP
if /i "%ARG1%"=="/h"     goto :SHOW_HELP
if /i "%ARG1%"=="/?"     goto :SHOW_HELP
if /i "%ARG1%"=="help"   goto :SHOW_HELP
if /i "%ARG1%"=="--help" goto :SHOW_HELP
goto :MAIN

:SHOW_HELP
echo.
echo Usage: make_tunnel ^<username^> ^<device_ip^> ^<port^> [hostname]
echo.
echo   username   : SSH username for the target device
echo   device_ip  : Target device IP or hostname (e.g. 192.168.1.100)
echo   port       : SSH port (default: 22)
echo   hostname   : Alias to identify the device (optional, multiple aliases per IP allowed)
echo.
echo Example:
echo   make_tunnel wego 192.168.0.10 22 GO2X_001
echo.
echo This generates an SSH key, registers it on the target, and adds an entry to ~/.ssh/config.
echo.
endlocal
exit /b 0

:MAIN
REM ===== 1. Process User Input =====
set "TARGET_USER=%~1"
set "TARGET_HOST=%~2"
set "TARGET_PORT=%~3"
set "CONFIG_ALIAS=%~4"

if "%TARGET_USER%"=="" set /p TARGET_USER=Enter target username: 
if "%TARGET_HOST%"=="" set /p TARGET_HOST=Enter target IP/Hostname: 
if "%TARGET_PORT%"=="" set /p TARGET_PORT=Enter SSH Port (Default 22): 
if "%TARGET_PORT%"=="" set "TARGET_PORT=22"

if "%CONFIG_ALIAS%"=="" (
    set "CONFIG_ALIAS=%TARGET_HOST%"
    set "KEY_NAME_PREFIX=%TARGET_HOST:.=_%"
) else (
    set "KEY_NAME_PREFIX=%CONFIG_ALIAS%"
)

REM ===== 2. Fix Host Identification Changed =====
echo [PROC] Clearing old host keys...
ssh-keygen -R %TARGET_HOST% >nul 2>&1
if not "%TARGET_PORT%"=="22" (
    ssh-keygen -R [%TARGET_HOST%]:%TARGET_PORT% >nul 2>&1
)

REM ===== 3. Set Paths =====
set "SSH_DIR=%USERPROFILE%\.ssh"
set "CONFIG_PATH=%SSH_DIR%\config"
set "KEY_PATH=%SSH_DIR%\id_rsa_%KEY_NAME_PREFIX%"
set "PUB_PATH=%KEY_PATH%.pub"

REM ===== 4. Check for Duplicate =====
if exist "%CONFIG_PATH%" (
    findstr /i /c:"Host %CONFIG_ALIAS%" "%CONFIG_PATH%" >nul
    if not errorlevel 1 (
        echo [INFO] Config for '%CONFIG_ALIAS%' already exists.
        goto :SKIP_CONFIG
    )
)

REM ===== 5. Key Generation & Transfer =====
if not exist "%SSH_DIR%" mkdir "%SSH_DIR%"
if not exist "%KEY_PATH%" (
    ssh-keygen -t rsa -b 4096 -f "%KEY_PATH%" -N "" -C "%USERNAME%@%COMPUTERNAME%"
)

echo [PROC] Registering public key...
type "%PUB_PATH%" | ssh -o StrictHostKeyChecking=no -p %TARGET_PORT% %TARGET_USER%@%TARGET_HOST% "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

if errorlevel 1 (
    echo [ERROR] Transfer failed.
    pause
    exit /b 1
)

REM ===== 7. Register Config File =====
echo.
set /p ADD_CONF=Add to SSH config? (Y/N): 
if /i "%ADD_CONF%"=="Y" (
    echo [PROC] Appending to config...

    REM 파일 끝에 줄바꿈을 추가하여 기존 내용과 섞이지 않게 함
    echo. >> "%CONFIG_PATH%"
    echo Host %CONFIG_ALIAS% >> "%CONFIG_PATH%"
    echo     HostName %TARGET_HOST% >> "%CONFIG_PATH%"
    echo     User %TARGET_USER% >> "%CONFIG_PATH%"
    echo     Port %TARGET_PORT% >> "%CONFIG_PATH%"
    echo     IdentityFile %KEY_PATH% >> "%CONFIG_PATH%"

    echo [DONE] Config registered successfully!
)

:SKIP_CONFIG
echo.
echo Connection Command: ssh %CONFIG_ALIAS%
pause
endlocal