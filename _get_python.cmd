@echo off
set "PYTHON_EXE="

set "PORTABLE_PY=%USERPROFILE%\Python313\python.exe"
if exist "%PORTABLE_PY%" (
  set "PYTHON_EXE=%PORTABLE_PY%"
  goto :done
)

set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
  set "PYTHON_EXE=%BUNDLED_PY%"
  goto :done
)

for /d %%U in ("C:\Users\*") do (
  if exist "%%U\Python313\python.exe" (
    set "PYTHON_EXE=%%U\Python313\python.exe"
    goto :done
  )
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
  if exist "%%D\python.exe" (
    set "PYTHON_EXE=%%D\python.exe"
    goto :done
  )
)

for /d %%P in ("C:\Python*" "%ProgramFiles%\Python*" "%ProgramFiles(x86)%\Python*") do (
  if exist "%%P\python.exe" (
    set "PYTHON_EXE=%%P\python.exe"
    goto :done
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%A in ('where python') do (
    echo %%A | findstr /i /c:"Microsoft\WindowsApps" >nul
    if errorlevel 1 (
      set "PYTHON_EXE=%%A"
      goto :done
    )
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py -3"
  goto :done
)

:done
if not defined PYTHON_EXE exit /b 1
exit /b 0
