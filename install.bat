@echo off
echo === Установка Docrobot EDI Gateway ===
echo.

REM Создаём виртуальное окружение
echo [1/4] Создаём виртуальное окружение...
python -m venv venv
call venv\Scripts\activate.bat

REM Устанавливаем зависимости
echo [2/4] Устанавливаем зависимости...
pip install -r requirements.txt

REM Копируем .env
echo [3/4] Настройте файл .env...
if not exist .env (
    copy .env.example .env
    echo Файл .env создан. Откройте его в Блокноте и заполните настройки!
    start notepad .env
    pause
)

REM Миграции и суперпользователь
echo [4/4] Создаём базу данных...
python manage.py migrate --run-syncdb
echo.
echo Создайте учётную запись администратора:
python manage.py createsuperuser

echo.
echo === Установка завершена! ===
echo Запускайте проект командой: start.bat
pause
