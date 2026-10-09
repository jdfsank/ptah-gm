@echo off
REM Generate HTML metrics report from a JSONL event log.
REM
REM Usage:
REM   shell\report.bat <metrics.jsonl> [output.html]
REM   shell\report.bat .godotmaker\metrics.jsonl
REM   shell\report.bat .godotmaker\metrics.jsonl report.html
REM
REM If no output path is given, writes to <input_dir>\report.html

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

if "%~1"=="" (
    echo Usage: shell\report.bat ^<metrics.jsonl^> [output.html]
    echo.
    echo Examples:
    echo   shell\report.bat .godotmaker\metrics.jsonl
    echo   shell\report.bat path\to\metrics.jsonl
    exit /b 1
)

set "INPUT=%~1"

if "%~2"=="" (
    set "OUTPUT=%~dp1report.html"
) else (
    set "OUTPUT=%~2"
)

cd /d "%REPO_ROOT%"
python -m hooks.metrics.reporter "%INPUT%" -o "%OUTPUT%"
echo Open: %OUTPUT%
