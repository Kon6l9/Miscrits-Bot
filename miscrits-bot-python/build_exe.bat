@echo off
REM Build single-file exe with PyInstaller
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --noconsole -p src src/app.py --name miscrits_bot
echo Build complete. Check the 'dist' folder for miscrits_bot.exe
pause
