@echo off
REM Xenosaga III translation editor - Windows launcher (double-click).
REM Opens the translation editor directly (the same program as launch.bat,
REM started on the editor page instead of the extractor cards).
call "%~dp0launch.bat" --editor %*
