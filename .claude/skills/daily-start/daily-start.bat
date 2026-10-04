@echo off
rem Startup entry. Calls the daily-start skill via claude (real work: daily_start.py).
rem The window stays open (pause) so that the result and any warnings remain visible.
cd /d "%~dp0..\..\.."
claude -p "Run the daily-start skill."
echo.
pause
