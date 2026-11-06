@echo off
REM Drag one or more songs (or a folder) onto this file to get drum MIDI.
REM Double-click it to process everything in the "songs" folder next to it.
cd /d "%~dp0"
call env\Scripts\activate.bat
if "%~1"=="" (
    if not exist songs mkdir songs
    python song2drums.py songs
) else (
    python song2drums.py %*
)
echo.
echo MIDI files are in: %~dp0drum_midi
pause
