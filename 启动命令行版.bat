@echo off
chcp 65001 >nul
title SCAU Class to ICS - zeta
cd /d "%~dp0"

echo Looking for Python...
call _get_python.cmd
if errorlevel 1 goto :nopython
if not defined PYTHON_EXE goto :nopython

if not exist "scau_ics.py" (
  echo Cannot find scau_ics.py in this folder.
  echo Please run this file from the folder containing scau_ics.py.
  goto :end_error
)

echo Found Python: %PYTHON_EXE%
echo.
echo Please enter your student ID and password when asked.
echo.
%PYTHON_EXE% scau_ics.py fetch
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo Finished with an error. Please check the red message above.
) else (
  echo Done. The .ics file was saved into this folder.
)
echo.
echo Press any key to close this window.
pause
exit /b %EXIT_CODE%

:nopython
echo Python was not found.
echo Please install Python 3.9 or newer and check "Add Python to PATH".
echo.
echo Press any key to close this window.
pause
exit /b 1

:end_error
echo.
echo Press any key to close this window.
pause
exit /b 1
