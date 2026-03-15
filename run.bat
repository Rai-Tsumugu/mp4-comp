@echo off
cd /d "%~dp0"
set LOGFILE=%~dp0error.log
where /q py
if %ERRORLEVEL% equ 0 (
    py gui.py 2>"%LOGFILE%"
    goto check_result
)
where /q python
if %ERRORLEVEL% equ 0 (
    python gui.py 2>"%LOGFILE%"
    goto check_result
)
echo Python not found. Please install Python and add it to PATH.
pause
exit /b 1
:check_result
if %ERRORLEVEL% neq 0 (
    echo.
    echo Error: See error.log for details:
    type "%LOGFILE%"
    pause
)
