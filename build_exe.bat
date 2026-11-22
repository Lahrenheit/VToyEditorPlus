@echo off
rem Builds dist\VToyEditor\VToyEditor.exe (same options as the auto-py-to-exe recipe in docs/CHANGELOG.md, section 8)
rem The icon: put any .ico file in the "icon" folder (first one found is used for the .exe AND the window / taskbar).
setlocal
rem  build_exe.bat            -> with the console window (shows the messages; also in vtoy_editor.log)
rem  build_exe.bat noconsole  -> only the editor window (everything still goes to vtoy_editor.log)
set CONSOLE=--console
if /i "%~1"=="noconsole" set CONSOLE=--windowed
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
  echo pip failed - see the message above; the build needs numpy, Pillow, glfw, PyOpenGL, imgui-bundle, py7zr and pyinstaller
  pause
  exit /b 1
)
%PY% tools\make_version_info.py
if errorlevel 1 (echo could not write version_info.txt & pause & exit /b 1)
%PY% -m PyInstaller --noconfirm --onedir %CONSOLE% --name VToyEditor %ICONARG% --version-file version_info.txt ^
  --add-data "vtoy\app\shaders;vtoy\app\shaders" ^
  --add-data "icon;icon" ^
  --add-data "docs\Manual_VToyEditorPlus_es.pdf;docs" ^
  --add-data "docs\Manual_VToyEditorPlus_en.pdf;docs" ^
  --add-data "docs\Manual_VToyEditorPlus_pt.pdf;docs" ^
  --add-data "vtoy\language;vtoy\language" ^
  --collect-submodules vtoy.language ^
  --collect-all imgui_bundle --collect-all glfw --collect-all py7zr ^
  --hidden-import OpenGL.platform.win32 --hidden-import OpenGL.GL --hidden-import vtoy.updater ^
  run_editor.py
pause
