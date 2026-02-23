"""
core/settings.py — Настройки Docrobot EDI Gateway
"""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'ЗАМЕНИТЕ-ЭТО-ПЕРЕД-ПРОДОМ')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'edi',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
TIME_ZONE = 'Asia/Almaty'
LANGUAGE_CODE = 'ru-ru'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Docrobot API ───────────────────────────────────────
DOCROBOT_API_URL  = os.getenv('DOCROBOT_API_URL', 'https://edi-api.docrobot.kz')
DOCROBOT_USERNAME = os.getenv('DOCROBOT_USERNAME', '')
DOCROBOT_PASSWORD = os.getenv('DOCROBOT_PASSWORD', '')
DOCROBOT_GLN      = os.getenv('DOCROBOT_GLN', '9845000004747') # Твой реальный GLN
# Интервал поллинга Docrobot (секунды)
DOCROBOT_POLL_INTERVAL = int(os.getenv('DOCROBOT_POLL_INTERVAL', '60'))

# ─── 1С HTTP-сервис ─────────────────────────────────────
ONEC_URL      = os.getenv('ONEC_URL', 'http://localhost/hs/docrobot/orders')
ONEC_USERNAME = os.getenv('ONEC_USERNAME', '')
ONEC_PASSWORD = os.getenv('ONEC_PASSWORD', '')
ONEC_TIMEOUT  = int(os.getenv('ONEC_TIMEOUT', '30'))
# Максимальное число попыток отправки
ONEC_MAX_RETRIES = int(os.getenv('ONEC_MAX_RETRIES', '5'))

# ─── Telegram-уведомления ───────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')
