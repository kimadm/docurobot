"""
Запуск: python fix_db.py
Создаёт таблицу edi_connectionsettings и помечает миграцию как применённую.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'db.sqlite3')

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Создаём таблицу если её нет
cur.execute("""
CREATE TABLE IF NOT EXISTS edi_connectionsettings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    docrobot_url VARCHAR(255) NOT NULL DEFAULT 'https://edi-api.docrobot.kz',
    docrobot_username VARCHAR(100) NOT NULL DEFAULT '',
    docrobot_password VARCHAR(255) NOT NULL DEFAULT '',
    docrobot_poll_interval INTEGER NOT NULL DEFAULT 60,
    onec_url VARCHAR(255) NOT NULL DEFAULT 'http://localhost/hs/docrobot/orders',
    onec_username VARCHAR(100) NOT NULL DEFAULT '',
    onec_password VARCHAR(255) NOT NULL DEFAULT '',
    onec_timeout INTEGER NOT NULL DEFAULT 30,
    telegram_token VARCHAR(255) NOT NULL DEFAULT '',
    telegram_chat_id VARCHAR(100) NOT NULL DEFAULT '',
    docrobot_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
    onec_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
    docrobot_tested_at DATETIME NULL,
    onec_tested_at DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")
print("✓ Таблица edi_connectionsettings создана")

# 2. Помечаем миграцию как применённую (если записи нет)
cur.execute("""
INSERT OR IGNORE INTO django_migrations (app, name, applied)
VALUES ('edi', '0001_initial', datetime('now'))
""")
print("✓ Миграция помечена как применённая")

conn.commit()
conn.close()
print("\nГотово! Теперь откройте http://127.0.0.1:8000/connections/")
