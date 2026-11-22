@echo off
rem Builds VToyEditor.exe WITHOUT the console window (messages and errors go to vtoy_editor.log next to the .exe)
call "%~dp0build_exe.bat" noconsole
