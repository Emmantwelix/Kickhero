@echo off
REM Double-click to open Kickhero.
cd /d "%~dp0"
start "" "%~dp0env\Scripts\pythonw.exe" -m kickhero.app
