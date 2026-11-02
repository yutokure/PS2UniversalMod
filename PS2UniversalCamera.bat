@echo off
rem PS2 Universal Camera Controller - double-click launcher.
rem Finds a Python that actually has PySide6 (see run_gui.py) and starts the GUI.
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\python\venv\Scripts\python.exe" set "PY=%~dp0..\python\venv\Scripts\python.exe"

if defined PY (
  "%PY%" "%~dp0run_gui.py" %*
) else (
  python "%~dp0run_gui.py" %*
)

if errorlevel 1 (
  echo.
  echo The camera controller exited with an error.  See the message above.
  pause
)
endlocal
