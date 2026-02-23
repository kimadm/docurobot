@echo off
cd C:\docrobot_django
call venv\Scripts\activate.bat
python manage.py poll_docrobot
pause