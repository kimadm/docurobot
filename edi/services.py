"""
edi/services.py — Сервисы: Docrobot API + отправка в 1С + Telegram

DocrobotClient   — клиент Docrobot REST API
OneCClient       — HTTP-клиент для 1С
TelegramNotifier — уведомления при ошибках
process_document — полный цикл: документ → XML → 1С
"""
import requests
import logging
from datetime import datetime
from django.conf import settings
from .xml_builder import build_xml

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Docrobot API
# ═══════════════════════════════════════════════════

class DocrobotClient:
    """
    REST-клиент для работы с реальным Docrobot KZ API.

    Особенности API (из анализа реального кода 1С):
    - Авторизация: POST /api/v1/auth  {login, password} → {token}
    - Токен передаётся БЕЗ Bearer: Authorization: <token>
    - Список документов: GET /api/v1/documents/folders/inbox/docGroup/EDI/docTypes/<TYPE>
    - Документ: GET /api/v1/documents/folders/inbox/docGroup/EDI/docTypes/<TYPE>/document/<id>
    - Контент документа закодирован в Base64 в поле "content"
    - Внутри Base64 → JSON со структурой {"ORDER": {"HEAD": {...}, "POSITION": [...]}}
    """

    DOC_TYPES = ['ORDER', 'ORDRSP', 'DESADV', 'INVOICE', 'PRICAT']

    # Соответствие DOCUMENTNAME → наш тип
    DOCNAME_MAP = {
        '220': 'ORDER',
        '231': 'ORDRSP',
        '351': 'DESADV',
        '380': 'INVOICE',
        '140': 'PRICAT',
    }

    def __init__(self):
        # Сначала берём настройки из БД (страница Подключений), иначе из .env
        try:
            from .models import ConnectionSettings
            cfg = ConnectionSettings.get()
            self.base_url = (cfg.docrobot_url or settings.DOCROBOT_API_URL).rstrip('/')
            self.username = cfg.docrobot_username or settings.DOCROBOT_USERNAME
            self.password = cfg.docrobot_password or settings.DOCROBOT_PASSWORD
        except Exception:
            self.base_url = settings.DOCROBOT_API_URL.rstrip('/')
            self.username = settings.DOCROBOT_USERNAME
            self.password = settings.DOCROBOT_PASSWORD
        self._token: str | None = None

    # ── Авторизация ──────────────────────────────────
    def _get_token(self) -> str:
        """POST /api/v1/auth — возвращает токен из поля 'token'."""
        if self._token:
            return self._token
        resp = requests.post(
            f'{self.base_url}/api/v1/auth',
            json={'login': self.username, 'password': self.password},
            headers={'Content-type': 'application/json'},
            timeout=15,
            verify=True,
        )
        resp.raise_for_status()
        data = resp.json()
        # Токен может быть в 'token' или 'access_token'
        self._token = data.get('token') or data.get('access_token') or data.get('accessToken')
        if not self._token:
            raise ValueError(f'Токен не найден в ответе авторизации: {data}')
        return self._token

    def _headers(self) -> dict:
        """Заголовки с токеном — БЕЗ Bearer, просто значение токена."""
        return {
            'Authorization': self._get_token(),
            'Accept': 'application/json',
        }

    def _reset_token(self):
        self._token = None

    # ── Получение списка документов ──────────────────
    def get_incoming_documents(self) -> list[dict]:
        """
        Получает входящие документы всех поддерживаемых типов.
        Возвращает список нормализованных документов.
        """
        from datetime import date, timedelta
        # Запрашиваем документы за последние 7 дней
        date_to   = date.today()
        date_from = date_to - timedelta(days=7)
        fmt = lambda d: d.strftime('%Y-%m-%d')

        all_docs = []
        for doc_type in self.DOC_TYPES:
            try:
                docs = self._fetch_type(doc_type, fmt(date_from), fmt(date_to))
                all_docs.extend(docs)
            except Exception as e:
                logger.warning(f'Ошибка получения {doc_type}: {e}')
        return all_docs

    def _fetch_type(self, doc_type: str, date_from: str, date_to: str) -> list[dict]:
        """Получает список документов одного типа с поддержкой пагинации."""
        result = []
        page = 1
        while True:
            url = (
                f'{self.base_url}/api/v1/documents/folders/inbox'
                f'/docGroup/EDI/docTypes/{doc_type}'
                f'?docDateFrom={date_from}&docDateTo={date_to}&page={page}&pageSize=100'
            )
            resp = self._get(url)
            data = resp.json()

            items = data.get('items', data.get('documents', []))
            if not items:
                break  # Страниц больше нет

            for item in items:
                doc_id = item.get('documentId') or item.get('id')
                if not doc_id:
                    continue
                try:
                    full = self._fetch_document(doc_type, doc_id)
                    normalized = self.normalize_document(full, doc_type)
                    if normalized:
                        result.append(normalized)
                except Exception as e:
                    logger.warning(f'Ошибка получения документа {doc_id}: {e}')

            # Если вернулось меньше 100 — это последняя страница
            total = data.get('total', data.get('totalCount', len(items)))
            if len(items) < 100 or len(result) >= total:
                break
            page += 1

        return result

    def _fetch_document(self, doc_type: str, doc_id: str) -> dict:
        """Получает полный документ по ID."""
        url = (
            f'{self.base_url}/api/v1/documents/folders/inbox'
            f'/docGroup/EDI/docTypes/{doc_type}/document/{doc_id}'
        )
        resp = self._get(url)
        return resp.json()

    def _get(self, url: str, retries: int = 3, retry_delay: float = 3.0):
        """
        GET-запрос с:
        - автоматическим обновлением токена при 401
        - retry при сетевых ошибках (3 попытки с паузой 3с)
        - логированием не-200 ответов
        """
        import time as _time
        last_exc = None
        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=self._headers(), timeout=30)
                if resp.status_code == 401:
                    self._reset_token()
                    resp = requests.get(url, headers=self._headers(), timeout=30)
                if not resp.ok:
                    logger.error(f'Docrobot {resp.status_code}: {resp.text[:300]}')
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_exc = e
                if attempt < retries - 1:
                    logger.warning(
                        f'Попытка {attempt+1}/{retries} неудачна ({e}). '
                        f'Повтор через {retry_delay}с...')
                    _time.sleep(retry_delay)
        raise last_exc

    def mark_received(self, doc_id: str) -> None:
        """Помечает документ как полученный (если API поддерживает)."""
        try:
            url = f'{self.base_url}/api/v1/documents/{doc_id}/receive'
            requests.post(url, headers=self._headers(), timeout=10)
        except Exception as e:
            logger.warning(f'mark_received {doc_id}: {e}')

    # ── Нормализация ─────────────────────────────────
    def normalize_document(self, raw: dict, doc_type: str = 'ORDER') -> dict | None:
        """
        Нормализует ответ Docrobot API в наш унифицированный формат.

        Контент документа закодирован в Base64 в поле 'content'.
        Внутри: {"ORDER": {"DATE":..., "NUMBER":..., "HEAD": {"POSITION": [...]}}}
        """
        import base64, json as _json

        doc_id = str(raw.get('documentId') or raw.get('id') or '')

        # Декодируем контент из Base64
        content_b64 = raw.get('content', '')
        content_data = {}
        if content_b64:
            try:
                decoded = base64.b64decode(content_b64).decode('utf-8')
                content_data = _json.loads(decoded)
            except Exception as e:
                logger.warning(f'Ошибка декодирования content для {doc_id}: {e}')

        # Извлекаем тело документа по типу
        doc_body = content_data.get(doc_type, content_data)
        head     = doc_body.get('HEAD', {}) if isinstance(doc_body, dict) else {}

        # Позиции товаров
        positions_raw = head.get('POSITION', []) if isinstance(head, dict) else []
        positions = []
        for p in (positions_raw if isinstance(positions_raw, list) else []):
            char = p.get('CHARACTERISTIC', {}) or {}
            positions.append({
                'ean':           str(p.get('PRODUCT', '')),
                'itemCode':      str(p.get('PRODUCT', '')),
                'itemName':      char.get('DESCRIPTION', '') if isinstance(char, dict) else '',
                'quantity':      p.get('ORDEREDQUANTITY', 0),
                'unitPrice':     p.get('ORDERPRICE', p.get('PRICEWITHVAT', 0)),
                'vat':           p.get('VAT', 0),
                'amount':        p.get('AMOUNT', 0),
                'amountWithVat': p.get('AMOUNTWITHVAT', 0),
                'unit':          p.get('ORDERUNIT', 'шт'),
                'positionNumber':p.get('POSITIONNUMBER', 0),
            })

        # GLN
        supplier_gln = ''
        buyer_gln    = ''
        if isinstance(head, dict):
            supplier_gln = str(head.get('SUPPLIER', ''))
            buyer_gln    = str(head.get('BUYER', ''))

        # Имена из INFO-блоков
        supplier_info = head.get('SUPPLIER_INFO', {}) or {} if isinstance(head, dict) else {}
        buyer_info    = head.get('BUYER_INFO', {}) or {}    if isinstance(head, dict) else {}
        delivery_info = head.get('DELIVERYPLACE_INFO', {}) or {} if isinstance(head, dict) else {}

        return {
            'docrobotId':    doc_id,
            'docType':       doc_type,
            'number':        str(doc_body.get('NUMBER', '') if isinstance(doc_body, dict) else ''),
            'date':          str(doc_body.get('DATE', '')   if isinstance(doc_body, dict) else ''),
            'deliveryDate':  str(doc_body.get('DELIVERYDATE', '') if isinstance(doc_body, dict) else ''),
            'shipmentDate':  str(doc_body.get('SHIPMENTDATE', '') if isinstance(doc_body, dict) else ''),
            'currency':      str(doc_body.get('CURRENCY', 'KZT') if isinstance(doc_body, dict) else 'KZT'),
            'supplierGln':   supplier_gln,
            'buyerGln':      buyer_gln,
            'supplierName':  supplier_info.get('полноеНазвание', supplier_info.get('краткоеНазвание', '')),
            'buyerName':     buyer_info.get('полноеНазвание', buyer_info.get('краткоеНазвание', '')),
            'deliveryAddress': delivery_info.get('Адрес', ''),
            'totalAmount':   doc_body.get('AMOUNT', 0)        if isinstance(doc_body, dict) else 0,
            'totalVat':      doc_body.get('VATAMOUNT', 0)     if isinstance(doc_body, dict) else 0,
            'totalWithVat':  doc_body.get('AMOUNTWITHVAT', 0) if isinstance(doc_body, dict) else 0,
            'positions':     positions,
            'raw':           raw,
        }


# ═══════════════════════════════════════════════════
# 1С HTTP-сервис
# ═══════════════════════════════════════════════════

class OneCClient:
    """Отправляет XML-документы в 1С через HTTP-сервис."""

    def __init__(self):
        self.url      = settings.ONEC_URL
        self.username = settings.ONEC_USERNAME
        self.password = settings.ONEC_PASSWORD
        self.timeout  = settings.ONEC_TIMEOUT

    def send(self, xml_bytes: bytes, doc_type: str) -> tuple[int, str]:
        """
        Отправляет XML в 1С.
        Возвращает (http_status_code, response_text).
        """
        auth = (self.username, self.password) if self.username else None
        resp = requests.post(
            self.url,
            data=xml_bytes,
            headers={
                'Content-Type': 'application/xml; charset=utf-8',
                'X-Document-Type': doc_type,
            },
            auth=auth,
            timeout=self.timeout,
        )
        return resp.status_code, resp.text


# ═══════════════════════════════════════════════════
# Telegram-уведомления
# ═══════════════════════════════════════════════════

class TelegramNotifier:
    def __init__(self):
        self.token   = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID

    def send(self, text: str) -> None:
        if not self.token or not self.chat_id:
            return
        try:
            requests.post(
                f'https://api.telegram.org/bot{self.token}/sendMessage',
                json={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f'Telegram: {e}')

    def error(self, doc_type: str, doc_number: str, error: str) -> None:
        self.send(
            f'🔴 <b>Ошибка отправки в 1С</b>\n'
            f'Тип: {doc_type}\n'
            f'Номер: {doc_number}\n'
            f'Ошибка: {error}'
        )

    def failed(self, doc_type: str, doc_number: str, attempts: int) -> None:
        self.send(
            f'❌ <b>Документ не удалось отправить в 1С</b>\n'
            f'Тип: {doc_type}\n'
            f'Номер: {doc_number}\n'
            f'Попыток: {attempts} — требуется ручное вмешательство!'
        )


# ═══════════════════════════════════════════════════
# Основной процессор
# ═══════════════════════════════════════════════════

def process_document(queue_entry) -> bool:
    """
    Полный цикл обработки одной записи очереди:
      1. Берём XML из документа
      2. Отправляем в 1С
      3. Обновляем статус
      4. Пишем лог
      5. При ошибке — Telegram-уведомление

    Возвращает True при успехе.
    """
    from .models import ActivityLog
    from django.conf import settings as cfg

    doc      = queue_entry.document
    notifier = TelegramNotifier()
    onec     = OneCClient()

    # Генерируем XML если не был сгенерирован ранее
    if not doc.xml_content:
        try:
            xml_bytes = build_xml(doc.doc_type, doc.raw_json)
            doc.xml_content = xml_bytes.decode('utf-8')
            doc.save(update_fields=['xml_content'])
        except Exception as e:
            msg = f'Ошибка генерации XML: {e}'
            queue_entry.mark_error(msg, None, cfg.ONEC_MAX_RETRIES)
            ActivityLog.objects.create(level='error', action='xml_build', message=msg, document=doc)
            return False

    try:
        http_code, response = onec.send(doc.xml_content.encode('utf-8'), doc.doc_type)
    except Exception as e:
        msg = f'Сетевая ошибка: {e}'
        queue_entry.mark_error(msg, None, cfg.ONEC_MAX_RETRIES)
        ActivityLog.objects.create(level='error', action='send_to_1c', message=msg, document=doc)
        notifier.error(doc.doc_type, doc.number, msg)
        return False

    if 200 <= http_code < 300:
        queue_entry.mark_sent(response, http_code)
        ActivityLog.objects.create(
            level='info', action='sent_to_1c',
            message=f'HTTP {http_code}. Ответ: {response[:200]}',
            document=doc,
        )
        return True
    else:
        msg = f'HTTP {http_code}: {response[:300]}'
        queue_entry.mark_error(msg, http_code, cfg.ONEC_MAX_RETRIES)
        ActivityLog.objects.create(level='error', action='send_to_1c', message=msg, document=doc)

        if queue_entry.status == queue_entry.STATUS_FAILED:
            notifier.failed(doc.doc_type, doc.number, queue_entry.attempts)
        else:
            notifier.error(doc.doc_type, doc.number, msg)
        return False
