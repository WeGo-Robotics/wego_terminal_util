@echo off
setlocal EnableExtensions
chcp 437 >nul

set "TARGET_HOST=%~1"

if /i "%TARGET_HOST%"=="?"      goto :SHOW_HELP
if /i "%TARGET_HOST%"=="h"      goto :SHOW_HELP
if /i "%TARGET_HOST%"=="-h"     goto :SHOW_HELP
if /i "%TARGET_HOST%"=="/h"     goto :SHOW_HELP
if /i "%TARGET_HOST%"=="/?"     goto :SHOW_HELP
if /i "%TARGET_HOST%"=="help"   goto :SHOW_HELP
if /i "%TARGET_HOST%"=="--help" goto :SHOW_HELP
goto :MAIN

:SHOW_HELP
echo.
echo Usage: remove_tunnel ^<device_ip^>
echo.
echo   device_ip : Target device IP or hostname to remove
echo.
echo Example:
echo   remove_tunnel 192.168.0.10
echo.
echo This removes matching key files from ~/.ssh and entries from ~/.ssh/config.
echo.
endlocal
exit /b 0

:MAIN
if "%TARGET_HOST%"=="" (
    set /p "TARGET_HOST=Enter Target IP/Hostname to remove: "
)

if "%TARGET_HOST%"=="" (
    echo [Error] No input provided. Exiting.
    pause
    exit /b 1
)

set "SSH_DIR=%USERPROFILE%\.ssh"
set "CONFIG_FILE=%SSH_DIR%\config"
set "HOST_SAFE=%TARGET_HOST:.=_%"

echo.
echo [Status] Removing ALL entries related to: %TARGET_HOST%
echo --------------------------------------------------

REM ===== 1. Delete Key Files =====
echo [Process] Deleting matching key files...
if exist "%SSH_DIR%\id_rsa_%HOST_SAFE%*" (
    del /q /f "%SSH_DIR%\id_rsa_%HOST_SAFE%*" >nul 2>&1
    echo - Deleted key files matching: id_rsa_%HOST_SAFE%*
) else (
    echo - No matching key files found.
)

REM ===== 2. Remove Sections (UTF-8 without BOM) =====
if exist "%CONFIG_FILE%" (
    echo [Process] Updating config (UTF-8 without BOM)...
    
    powershell -NoProfile -Command ^
        "$target = [regex]::Escape('%TARGET_HOST%');" ^
        "$lines = Get-Content '%CONFIG_FILE%';" ^
        "$newLines = New-Object System.Collections.Generic.List[string];" ^
        "$skip = $false;" ^
        "foreach($line in $lines) {" ^
        "    if($line -match '^\s*(Host|HostName)\s+' + $target) { $skip = $true; continue; }" ^
        "    if($skip -and $line -match '^\s*Host\s+') { $skip = $false; }" ^
        "    if(-not $skip) { $newLines.Add($line) }" ^
        "};" ^
        "[System.IO.File]::WriteAllLines('%CONFIG_FILE%', $newLines, (New-Object System.Text.UTF8Encoding($false)))"
    
    echo - Config file updated successfully.
)

echo --------------------------------------------------
echo [Finish] Cleanup complete.
echo.
pause
endlocal