# Docrobot EDI Gateway

Промежуточный сервис для автоматического получения EDI-документов из [Docrobot KZ](https://docrobot.kz) и отправки их в 1С по HTTP.

## Схема работы

```
Docrobot API → Поллер → SQLite → XML Builder → 1С HTTP-сервис
```

## Возможности

- **Автоматический поллинг** Docrobot API каждые N секунд
- **5 типов документов**: ORDER, ORDRSP, DESADV, INVOICE, PRICAT
- **Гибкие XML-шаблоны** — редактируются прямо в браузере, без правки кода
- **Retry с exponential backoff** — 1 → 5 → 15 → 60 мин при ошибках 1С
- **Веб-интерфейс**: дашборд, очередь, логи, отчёты, настройка подключений
- **Telegram-уведомления** при критических ошибках

## Быстрый старт (Windows)

### 1. Установка

```bat
git clone https://github.com/kimadm/docurobot.git
cd docurobot
install.bat
```

Откроется `.env` — заполните параметры.

### 2. Настройка `.env`

```env
SECRET_KEY=your-secret-key-50-chars-minimum

# Docrobot
DOCROBOT_API_URL=https://edi-api.docrobot.kz
DOCROBOT_USERNAME=your_login
DOCROBOT_PASSWORD=your_password
DOCROBOT_POLL_INTERVAL=60

# 1С
ONEC_URL=http://localhost/hs/docrobot/orders
ONEC_USERNAME=
ONEC_PASSWORD=
ONEC_TIMEOUT=30
ONEC_MAX_RETRIES=5

# Telegram (опционально)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

> **Или** настройте подключения прямо в веб-интерфейсе: `http://localhost:8000/connections/`

### 3. Запуск

```bat
start.bat
```

Откроется два окна: сервер + поллер. Перейдите на `http://localhost:8000`.

## Ручной запуск (без .bat)

```bash
# Активируйте venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/Mac

# Применить миграции
python manage.py migrate

# Создать суперпользователя (опционально)
python manage.py createsuperuser

# Запустить сервер
python manage.py runserver

# В отдельном терминале — запустить поллер
python manage.py poll_docrobot
```

## Структура проекта

```
docrobot_django/
├── core/                    # Django-проект (settings, urls)
├── edi/                     # Основное приложение
│   ├── models.py            # EdiDocument, SendQueue, ActivityLog, XmlTemplate, ConnectionSettings
│   ├── services.py          # DocrobotClient — работа с API
│   ├── xml_builder.py       # Генерация XML для 1С
│   ├── views.py             # Все страницы и API
│   ├── management/commands/
│   │   └── poll_docrobot.py # Фоновый поллер
│   └── templates/edi/       # HTML-шаблоны
├── .env.example             # Пример конфигурации
├── requirements.txt
├── install.bat              # Установка (Windows)
└── start.bat                # Запуск (Windows)
```

## База данных

| Таблица | Назначение |
|---------|-----------|
| `EdiDocument` | Входящие документы из Docrobot |
| `SendQueue` | Очередь отправки в 1С с retry-логикой |
| `ActivityLog` | Журнал всех событий системы |
| `XmlTemplate` | Настраиваемые XML-шаблоны по типу документа |
| `ConnectionSettings` | Настройки подключений (Docrobot / 1С / Telegram) |

## XML-шаблоны

Каждый тип документа имеет свой шаблон в БД. Переменные вида `{{number}}`, `{{supplier_gln}}`, `{{positions}}` заменяются данными документа при отправке.

Редактор шаблонов: `http://localhost:8000/settings/`

## Стек

- Python 3.13 / Django 6.0
- SQLite (легко заменяется на PostgreSQL)
- lxml — генерация GS1 XML
- requests — HTTP-клиент
- Django REST Framework — API
- Vanilla JS + CSS — фронтенд (без фреймворков)

## Лицензия

MIT
