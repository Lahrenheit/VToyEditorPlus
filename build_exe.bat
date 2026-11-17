@echo off
rem Builds dist\VToyEditor\VToyEditor.exe (same options as the auto-py-to-exe recipe in README.md)
rem The icon: put any .ico file in the "icon" folder (first one found is used for the .exe AND the window / taskbar).
setlocal
set ICONARG=
for %%f in (icon\*.ico) do if not defined ICONARG set ICONARG=--icon "%%f"
if defined ICONARG (echo Using icon: %ICONARG%) else (echo No .ico found in icon\ - building with the default icon)
rem Pick the Python to use: the launcher "py -3.13" first, then python3, then python (whichever really is Python 3.10-3.13)
set PY=
for %%c in ("py -3.13" "py -3.12" "py -3.11" "py -3.10" "python3" "python") do if not defined PY (
  %%~c -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set PY=%%~c
)
if not defined PY (
  echo No Python 3.10-3.13 found. Install Python 3.13 ^(tick "Add python.exe to PATH"^) and run this again.
  pause
  exit /b 1
)
echo Using Python: %PY%
%PY% --version
%PY% -m pip install pyinstaller -r requirements.txt
if errorlevel 1 (echo.
  echo pip failed - see the message above; the build needs numpy, Pillow, glfw, PyOpenGL, imgui-bundle and pyinstaller
  pause
  exit /b 1
)
%PY% -m PyInstaller --noconfirm --onedir --console --name VToyEditor %ICONARG% --version-file version_info.txt ^
  --add-data "vtoy\app\shaders;vtoy\app\shaders" ^
  --add-data "icon;icon" ^
  --add-data "vtoy\language;vtoy\language" ^
  --collect-submodules vtoy.language ^
  --collect-all imgui_bundle --collect-all glfw ^
  --hidden-import OpenGL.platform.win32 --hidden-import OpenGL.GL ^
  run_editor.py
pause
