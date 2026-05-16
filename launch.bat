@echo off
REM Xenosaga III Extractor — Windows double-click launcher.
REM Starts the local GUI on a free port and opens your browser.

setlocal
cd /d "%~dp0"

REM Prefer the Windows Python launcher; fall back to plain `python` on PATH.
where py >nul 2>nul && (
    py -3 gui.py %*
    goto :done
)
where python >nul 2>nul && (
    python gui.py %*
    goto :done
)

echo Python 3 was not found on your PATH.
echo Install Python 3.8 or newer from https://www.python.org/downloads/
echo (make sure to tick "Add Python to PATH" during install),
echo then double-click this launcher again.
pause
exit /b 1

:done
REM If gui.py errored out, keep the window open so the user can see why.
if errorlevel 1 pause
