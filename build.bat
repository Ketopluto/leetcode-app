@echo off
echo Building LeetCode Stats Dashboard...
pyinstaller --onefile --clean --noconfirm ^
--add-data "app/templates;templates" ^
--add-data "app/static;static" ^
--hidden-import flask_caching ^
--hidden-import concurrent.futures ^
--hidden-import urllib3 ^
--hidden-import config ^
--icon "app/assets/leetcode-icon.ico" ^
--name "LeetCodeStats" ^
app/main.py

echo Build complete! Check the 'dist' folder for the executable.
pause
