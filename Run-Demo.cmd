@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m microtools_free.demo
goto finished
:usepython
python -m microtools_free.demo
:finished
echo.
pause
