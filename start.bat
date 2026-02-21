@echo off
echo === Docrobot EDI Gateway ===
echo.

REM Активируем виртуальное окружение если есть
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Применяем миграции
echo Применяем миграции...
python manage.py migrate --run-syncdb

REM Запускаем поллер в отдельном окне
echo Запускаем поллер Docrobot...
start "Docrobot Poller" cmd /k "python manage.py poll_docrobot"

REM Запускаем веб-сервер
echo Запускаем веб-сервер на http://localhost:8000
echo.
python manage.py runserver 0.0.0.0:8000
