@echo off
setlocal EnableExtensions
chcp 65001 >nul

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
    echo [PROC] Appending to config in UTF-8...
    
    REM Define the block to add
    set "NL=^"
    set "NEW_ENTRY=Host %CONFIG_ALIAS%`n    HostName %TARGET_HOST%`n    User %TARGET_USER%`n    Port %TARGET_PORT%`n    IdentityFile %KEY_PATH%"

    REM Use PowerShell to append in UTF-8 without BOM
    powershell -NoProfile -Command ^
        "$content = '%NEW_ENTRY%'.Replace('`n', [System.Environment]::NewLine);" ^
        "if (Test-Path '%CONFIG_PATH%') { $existing = Get-Content '%CONFIG_PATH%' -Raw; $content = \"$existing`n$content\" };" ^
        "[System.IO.File]::WriteAllLines('%CONFIG_PATH%', $content, (New-Object System.Text.UTF8Encoding($false)))"

    echo [DONE] Config registered successfully!
)

:SKIP_CONFIG
echo.
echo Connection Command: ssh %CONFIG_ALIAS%
pause
endlocal