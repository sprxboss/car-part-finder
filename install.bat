@echo off
echo Installing Auto Parts Finder dependencies...
echo.
pip install flask requests beautifulsoup4 playwright
echo.
echo Downloading Chromium browser (one-time, ~150MB)...
python -m playwright install chromium
echo.
echo All done! Run start.bat to launch the app.
pause
