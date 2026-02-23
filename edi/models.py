"""
edi/models.py — Модели данных Docrobot EDI Gateway

Таблицы:
  EdiDocument   — входящий документ из Docrobot (любой тип)
  SendQueue     — очередь отправки в 1С с retry-логикой
  ActivityLog   — лог всех действий системы
"""
from django.db import models
from django.utils import timezone


class EdiDocument(models.Model):
    """Документ, полученный из Docrobot."""

    DOC_TYPES = [
        ('ORDER',  'Заказ'),
        ('ORDRSP', 'Подтверждение заказа'),
        ('DESADV', 'Уведомление об отгрузке'),
        ('INVOICE','Счёт-фактура'),
        ('PRICAT', 'Прайс-лист'),
    ]

    # Идентификатор в Docrobot
    docrobot_id   = models.CharField(max_length=100, unique=True, verbose_name='ID в Docrobot')
    doc_type      = models.CharField(max_length=10, choices=DOC_TYPES, verbose_name='Тип')
    number        = models.CharField(max_length=100, blank=True, verbose_name='Номер документа')
    doc_date      = models.DateField(null=True, blank=True, verbose_name='Дата документа')
    supplier_gln  = models.CharField(max_length=13, blank=True, verbose_name='GLN поставщика')
    buyer_gln     = models.CharField(max_length=13, blank=True, verbose_name='GLN покупателя')
    supplier_name = models.CharField(max_length=255, blank=True, verbose_name='Поставщик')
    buyer_name    = models.CharField(max_length=255, blank=True, verbose_name='Покупатель')
    raw_json      = models.JSONField(default=dict, verbose_name='Сырые данные JSON')
    xml_content   = models.TextField(blank=True, verbose_name='Сгенерированный XML')
    received_at   = models.DateTimeField(auto_now_add=True, verbose_name='Получен')

    class Meta:
        verbose_name = 'EDI-документ'
        verbose_name_plural = 'EDI-документы'
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.get_doc_type_display()} №{self.number} ({self.docrobot_id})'


class SendQueue(models.Model):
    """Очередь отправки документов в 1С."""

    STATUS_PENDING = 'pending'
    STATUS_SENDING = 'sending'
    STATUS_SENT    = 'sent'
    STATUS_ERROR   = 'error'
    STATUS_FAILED  = 'failed'  # превышен лимит попыток

    STATUSES = [
        (STATUS_PENDING, 'Ожидает'),
        (STATUS_SENDING, 'Отправляется'),
        (STATUS_SENT,    'Отправлен'),
        (STATUS_ERROR,   'Ошибка (повтор)'),
        (STATUS_FAILED,  'Не удалось отправить'),
    ]

    document    = models.OneToOneField(
        EdiDocument, on_delete=models.CASCADE,
        related_name='queue_entry', verbose_name='Документ'
    )
    status      = models.CharField(max_length=10, choices=STATUSES, default=STATUS_PENDING, verbose_name='Статус')
    attempts    = models.PositiveIntegerField(default=0, verbose_name='Попыток')
    last_error  = models.TextField(blank=True, verbose_name='Последняя ошибка')
    response    = models.TextField(blank=True, verbose_name='Ответ 1С')
    http_status = models.PositiveIntegerField(null=True, blank=True, verbose_name='HTTP-код')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    updated_at  = models.DateTimeField(auto_now=True, verbose_name='Обновлён')
    sent_at     = models.DateTimeField(null=True, blank=True, verbose_name='Отправлен в 1С')
    next_retry  = models.DateTimeField(null=True, blank=True, verbose_name='Следующая попытка')

    class Meta:
        verbose_name = 'Запись очереди'
        verbose_name_plural = 'Очередь отправки'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.document} → {self.get_status_display()}'

    def mark_sent(self, response_text: str, http_code: int):
        self.status     = self.STATUS_SENT
        self.response   = response_text
        self.http_status= http_code
        self.sent_at    = timezone.now()
        self.last_error = ''
        self.save()

    def mark_error(self, error: str, http_code: int | None, max_retries: int):
        from datetime import timedelta
        self.attempts   += 1
        self.last_error  = error
        self.http_status = http_code
        if self.attempts >= max_retries:
            self.status = self.STATUS_FAILED
        else:
            self.status     = self.STATUS_ERROR
            # Экспоненциальная задержка: 1м, 5м, 15м, 60м, ...
            delay_minutes = min(60, 2 ** self.attempts)
            self.next_retry = timezone.now() + timedelta(minutes=delay_minutes)
        self.save()


class ActivityLog(models.Model):
    """Лог всех действий: поллинг, отправка, ошибки."""

    LEVEL_INFO  = 'info'
    LEVEL_WARN  = 'warn'
    LEVEL_ERROR = 'error'

    LEVELS = [
        (LEVEL_INFO,  'Инфо'),
        (LEVEL_WARN,  'Предупреждение'),
        (LEVEL_ERROR, 'Ошибка'),
    ]

    level      = models.CharField(max_length=5, choices=LEVELS, default=LEVEL_INFO, verbose_name='Уровень')
    action     = models.CharField(max_length=100, verbose_name='Действие')
    message    = models.TextField(verbose_name='Сообщение')
    document   = models.ForeignKey(
        EdiDocument, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs', verbose_name='Документ'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время')

    class Meta:
        verbose_name = 'Лог'
        verbose_name_plural = 'Логи'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.level.upper()}] {self.action}: {self.message[:60]}'


class XmlTemplate(models.Model):
    """
    Шаблон XML для конкретного типа EDI-документа.

    Позволяет настроить формат XML под любой 1С-сервис
    без изменения кода. Шаблон — это строка с переменными
    вида {{field_name}}, которые заменяются данными документа.

    Доступные переменные:
      {{number}}        — номер документа
      {{date}}          — дата документа
      {{delivery_date}} — дата доставки (для ORDER)
      {{supplier_gln}}  — GLN поставщика
      {{supplier_name}} — название поставщика
      {{buyer_gln}}     — GLN покупателя
      {{buyer_name}}    — название покупателя
      {{currency}}      — валюта (KZT)
      {{positions}}     — блок позиций (рендерится отдельным шаблоном)
      {{positions_json}}— позиции как JSON-строка
      {{raw_json}}      — весь документ как JSON
    """
    doc_type    = models.CharField(
        max_length=10,
        choices=[
            ('ORDER',   'Заказ (ORDER)'),
            ('ORDRSP',  'Подтверждение (ORDRSP)'),
            ('DESADV',  'Отгрузка (DESADV)'),
            ('INVOICE', 'Счёт-фактура (INVOICE)'),
            ('PRICAT',  'Прайс-лист (PRICAT)'),
        ],
        unique=True,
        verbose_name='Тип документа',
    )
    name        = models.CharField(max_length=100, verbose_name='Название шаблона')
    # Шаблон для одной позиции товара (используется внутри {{positions}})
    position_tpl= models.TextField(
        blank=True,
        verbose_name='Шаблон позиции',
        help_text='Переменные: {{line}}, {{ean}}, {{item_code}}, {{item_name}}, {{quantity}}, {{unit_price}}, {{vat}}, {{amount}}, {{amount_with_vat}}',
    )
    # Основной шаблон документа
    body_tpl    = models.TextField(
        verbose_name='Шаблон документа (XML)',
        help_text='Используйте {{переменная}} для подстановки данных.',
    )
    content_type= models.CharField(
        max_length=60,
        default='application/xml; charset=utf-8',
        verbose_name='Content-Type для 1С',
    )
    is_active   = models.BooleanField(default=True, verbose_name='Активен')
    updated_at  = models.DateTimeField(auto_now=True, verbose_name='Обновлён')

    class Meta:
        verbose_name = 'XML-шаблон'
        verbose_name_plural = 'XML-шаблоны'

    def __str__(self):
        return f'{self.doc_type} — {self.name}'

    def render(self, doc_data: dict) -> str:
        """
        Рендерит шаблон, подставляя данные документа.
        doc_data — нормализованный словарь из EdiDocument.raw_json
        """
        import json

        # Рендерим блок позиций
        positions_xml = ''
        if self.position_tpl:
            lines = []
            for i, p in enumerate(doc_data.get('positions', []), start=1):
                line = self.position_tpl
                line = line.replace('{{line}}',            str(i))
                line = line.replace('{{ean}}',             str(p.get('ean', '')))
                line = line.replace('{{item_code}}',       str(p.get('itemCode', '')))
                line = line.replace('{{item_name}}',       str(p.get('itemName', '')))
                line = line.replace('{{quantity}}',        str(p.get('quantity', 0)))
                line = line.replace('{{unit_price}}',      str(p.get('unitPrice', 0)))
                line = line.replace('{{vat}}',             str(p.get('vat', 0)))
                line = line.replace('{{amount}}',          str(p.get('amount', 0)))
                line = line.replace('{{amount_with_vat}}', str(p.get('amountWithVat', 0)))
                lines.append(line)
            positions_xml = '\n'.join(lines)

        result = self.body_tpl
        result = result.replace('{{number}}',         str(doc_data.get('number', '')))
        result = result.replace('{{date}}',           str(doc_data.get('date', '')))
        result = result.replace('{{delivery_date}}',  str(doc_data.get('deliveryDate', '')))
        result = result.replace('{{supplier_gln}}',   str(doc_data.get('supplierGln', '')))
        result = result.replace('{{supplier_name}}',  str(doc_data.get('supplierName', '')))
        result = result.replace('{{buyer_gln}}',      str(doc_data.get('buyerGln', '')))
        result = result.replace('{{buyer_name}}',     str(doc_data.get('buyerName', '')))
        result = result.replace('{{currency}}',       str(doc_data.get('currency', 'KZT')))
        result = result.replace('{{order_number}}',   str(doc_data.get('orderNumber', '')))
        result = result.replace('{{shipment_date}}',  str(doc_data.get('shipmentDate', '')))
        result = result.replace('{{total_amount}}',   str(doc_data.get('totalAmount', 0)))
        result = result.replace('{{total_vat}}',      str(doc_data.get('totalVat', 0)))
        result = result.replace('{{total_with_vat}}', str(doc_data.get('totalWithVat', 0)))
        result = result.replace('{{positions}}',      positions_xml)
        result = result.replace('{{positions_json}}', json.dumps(doc_data.get('positions', []), ensure_ascii=False))
        result = result.replace('{{raw_json}}',       json.dumps(doc_data, ensure_ascii=False))
        return result


class ConnectionSettings(models.Model):
    """
    Настройки подключений — хранятся в БД и редактируются через веб-интерфейс.
    Имеет смысл хранить только одну запись (singleton).
    Пароли шифруются через Fernet перед сохранением.
    """
    # ── Docrobot ──────────────────────────────────────────
    docrobot_url      = models.CharField(
        max_length=255, default='https://edi-api.docrobot.kz',
        verbose_name='URL Docrobot API',
    )
    docrobot_username = models.CharField(max_length=100, blank=True, verbose_name='Логин Docrobot')
    docrobot_password = models.CharField(max_length=255, blank=True, verbose_name='Пароль Docrobot')
    docrobot_poll_interval = models.IntegerField(default=60, verbose_name='Интервал опроса (сек)')

    # ── 1С ────────────────────────────────────────────────
    onec_url      = models.CharField(
        max_length=255, default='http://localhost/hs/docrobot/orders',
        verbose_name='URL 1С HTTP-сервиса',
    )
    onec_username = models.CharField(max_length=100, blank=True, verbose_name='Логин 1С')
    onec_password = models.CharField(max_length=255, blank=True, verbose_name='Пароль 1С')
    onec_timeout  = models.IntegerField(default=30, verbose_name='Таймаут 1С (сек)')

    # ── Telegram ──────────────────────────────────────────
    telegram_token   = models.CharField(max_length=255, blank=True, verbose_name='Telegram Bot Token')
    telegram_chat_id = models.CharField(max_length=100, blank=True, verbose_name='Telegram Chat ID')

    # ── Мета ──────────────────────────────────────────────
    docrobot_status   = models.CharField(max_length=20, default='unknown', verbose_name='Статус Docrobot')
    onec_status       = models.CharField(max_length=20, default='unknown', verbose_name='Статус 1С')
    docrobot_tested_at = models.DateTimeField(null=True, blank=True, verbose_name='Проверен Docrobot')
    onec_tested_at     = models.DateTimeField(null=True, blank=True, verbose_name='Проверен 1С')
    updated_at        = models.DateTimeField(auto_now=True, verbose_name='Обновлено')

    class Meta:
        verbose_name = 'Настройки подключений'
        verbose_name_plural = 'Настройки подключений'

    def __str__(self):
        return 'Настройки подключений'

    @classmethod
    def get(cls):
        """Возвращает единственную запись, создаёт если нет."""
        from django.conf import settings as django_settings
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'docrobot_url':      getattr(django_settings, 'DOCROBOT_API_URL', 'https://edi-api.docrobot.kz'),
            'docrobot_username': getattr(django_settings, 'DOCROBOT_USERNAME', ''),
            'docrobot_password': getattr(django_settings, 'DOCROBOT_PASSWORD', ''),
            'onec_url':          getattr(django_settings, 'ONEC_URL', ''),
            'onec_username':     getattr(django_settings, 'ONEC_USERNAME', ''),
            'onec_password':     getattr(django_settings, 'ONEC_PASSWORD', ''),
            'telegram_token':    getattr(django_settings, 'TELEGRAM_BOT_TOKEN', ''),
            'telegram_chat_id':  getattr(django_settings, 'TELEGRAM_CHAT_ID', ''),
        })
        return obj

    def apply_to_django_settings(self):
        """Применяет настройки из БД к django.conf.settings на лету."""
        from django.conf import settings as django_settings
        django_settings.DOCROBOT_API_URL       = self.docrobot_url
        django_settings.DOCROBOT_USERNAME      = self.docrobot_username
        django_settings.DOCROBOT_PASSWORD      = self.docrobot_password
        django_settings.DOCROBOT_POLL_INTERVAL = self.docrobot_poll_interval
        django_settings.ONEC_URL               = self.onec_url
        django_settings.ONEC_USERNAME          = self.onec_username
        django_settings.ONEC_PASSWORD          = self.onec_password
        django_settings.ONEC_TIMEOUT           = self.onec_timeout
        django_settings.TELEGRAM_BOT_TOKEN     = self.telegram_token
        django_settings.TELEGRAM_CHAT_ID       = self.telegram_chat_id
