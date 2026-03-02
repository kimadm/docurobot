# 📄 Docrobot EDI Integration

Docrobot — система интеграции Edi-документов edi.docrobot.kz

Проект автоматизирует:
- 📥 загрузку документов из Docrobot
- 📊 отчёты и аналитика
- 🔄 синхронизацию с 1С
- 🧾 ежедневные отчёты поставщиков
- 📡 мониторинг ActivityLog

---

## 🚀 Версия

**v3.0 – stableV3**

### Изменения
- ✔ Исправлено сопоставление единиц измерения (`fix_units`)
- ✔ Улучшен poll_docrobot + ActivityLog
- ✔ Healthcheck с таймзоной Алматы
- ✔ Улучшен daily_report UI
- ✔ Исправлены шаблоны и маршруты

---

## 🛠 Установка

```bash
git clone https://github.com/kimadm/docurobot.git
cd docurobot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
