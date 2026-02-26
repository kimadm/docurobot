import base64
import json as _json
import logging
import re
import time as _time
from datetime import date, timedelta

import requests
from django.conf import settings
from .xml_builder import build_xml

logger = logging.getLogger(__name__)


def _parse_date(val) -> str | None:
    """Парсит дату в формат YYYY-MM-DD или возвращает None."""
    if not val or str(val).strip() in ('', 'None', 'null'):
        return None
    val = str(val).strip()
    if re.match(r'\d{4}-\d{2}-\d{2}', val):
        return val[:10]
    m = re.match(r'(\d{2})-(\d{2})-(\d{4})', val)
    if m:
        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', val)
    if m:
        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    return None


class DocrobotClient:
    """
    Клиент Docrobot API.
    
    Список документов: GET https://edi-api.docrobot.kz/api/v1/documents/...
    Токен для списка:  POST https://edi-api.docrobot.kz/api/v1/auth
    
    Содержимое документа: POST https://edi.docrobot.kz/api/v2/edi/document/get
    Токен для содержимого: Keycloak https://auth.docrobot.kz/realms/docrobot/...
    """

    API_URL  = 'https://edi-api.docrobot.kz'
    EDI_URL  = 'https://edi.docrobot.kz'
    KC_URL   = 'https://auth.docrobot.kz/realms/docrobot/protocol/openid-connect/token'
    DOC_TYPES = ['ORDER', 'ORDRSP', 'DESADV', 'INVOICE', 'PRICAT']

    def __init__(self):
        # Настройки из БД или .env
        try:
            from .models import ConnectionSettings
            cfg = ConnectionSettings.get()
            self.username = cfg.docrobot_username or settings.DOCROBOT_USERNAME
            self.password = cfg.docrobot_password or settings.DOCROBOT_PASSWORD
            self.gln = cfg.docrobot_gln or settings.DOCROBOT_GLN
        except Exception:
            self.username = settings.DOCROBOT_USERNAME
            self.password = settings.DOCROBOT_PASSWORD
            self.gln = settings.DOCROBOT_GLN

        self._api_token = None   # Для edi-api (список)
        self._edi_token = None   # Для edi.docrobot.kz (содержимое, Keycloak)

    # ── Авторизация ──────────────────────────────────────
    def _get_api_token(self) -> str:
        """POST /api/v1/auth → 'Bearer eyJ...' для списка документов."""
        if self._api_token:
            return self._api_token
        resp = requests.post(
            f'{self.API_URL}/api/v1/auth',
            json={'login': self.username, 'password': self.password},
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get('token')
        if not token:
            raise ValueError(f'Токен не получен: {data}')
        if data.get('checkStatus', -1) != 0:
            raise ValueError(f'checkStatus={data.get("checkStatus")}: доступ не активирован')
        self._api_token = token
        logger.info(f'Авторизация Docrobot успешна: {self.username}',
                    extra={'action': 'docrobot_auth_ok'})
        return self._api_token

    def _get_edi_token(self) -> str:
        """Keycloak OAuth2 → Bearer токен для edi.docrobot.kz."""
        if self._edi_token:
            return self._edi_token
        resp = requests.post(
            self.KC_URL,
            data={
                'grant_type': 'password',
                'username': self.username,
                'password': self.password,
                'client_id': 'docrobot-app',
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        access_token = data.get('access_token')
        if not access_token:
            raise ValueError(f'Keycloak: access_token не получен')
        self._edi_token = f'Bearer {access_token}'
        return self._edi_token

    def _api_headers(self) -> dict:
        return {
            'Authorization': self._get_api_token(),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'gln': str(self.gln),
        }

    def _edi_headers(self) -> dict:
        return {
            'x-ecom-auth-token': self._get_edi_token(),
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': '*/*',
        }

    # ── Получение документов ─────────────────────────────
    def get_incoming_documents(self) -> list[dict]:
        date_to   = date.today()
        date_from = date_to - timedelta(days=30)
        fmt = lambda d: d.strftime('%d-%m-%Y')

        logger.info(f'[Docrobot] Поиск за период: {fmt(date_from)} — {fmt(date_to)}')

        all_docs = []
        for doc_type in self.DOC_TYPES:
            try:
                docs = self._fetch_type(doc_type, fmt(date_from), fmt(date_to))
                if docs:
                    all_docs.extend(docs)
                    logger.info(f'{doc_type}: найдено {len(docs)} шт.')
                else:
                    logger.debug(f'{doc_type}: ничего не найдено')
            except Exception as e:
                logger.error(f'{doc_type}: ошибка получения — {e}', exc_info=True)
        return all_docs

    def _fetch_type(self, doc_type: str, d_from: str, d_to: str) -> list[dict]:
        url = f'{self.API_URL}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/{doc_type}'
        params = {
            'gln': self.gln,
            'docDateFrom': d_from,
            'docDateTo': d_to,
            'page': 0,
            'pageSize': 50,
        }
        resp = requests.get(url, params=params, headers=self._api_headers(), timeout=30)
        resp.raise_for_status()

        items = resp.json().get('items') or []
        result = []
        for item in items:
            doc_id  = item.get('documentId')
            flow_id = item.get('docflowId')
            # Пробуем получить полный контент
            content = self._fetch_content(doc_type, doc_id, flow_id)
            if content:
                normalized = self.normalize_document(content, doc_type)
            else:
                # Fallback — нормализуем из данных списка
                normalized = self.normalize_document(item, doc_type)
            if normalized:
                result.append(normalized)
        return result

    def _fetch_content(self, doc_type: str, doc_id: str, flow_id: str) -> dict | None:
        """Получает полный документ через edi-api по documentId."""
        if not doc_id:
            return None
        try:
            url = (
                f'{self.API_URL}/api/v1/documents/folders/inbox'
                f'/docGroup/EDI/docTypes/{doc_type}/document/{doc_id}'
            )
            headers = self._api_headers()
            headers['gln'] = str(self.gln)
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 401:
                self._api_token = None
                headers = self._api_headers()
                headers['gln'] = str(self.gln)
                resp = requests.get(url, headers=headers, timeout=15)
            if resp.ok:
                data = resp.json()
                if data.get('content'):
                    logger.debug(f'_fetch_content OK: {doc_id}, content_len={len(data["content"])}')
                    return data
                else:
                    logger.debug(f'_fetch_content: нет content для {doc_id}')
            else:
                logger.debug(f'_fetch_content HTTP {resp.status_code} для {doc_id}: {resp.text[:150]}')
        except Exception as e:
            logger.debug(f'_fetch_content ошибка для {doc_id}: {e}')
        return None


    def normalize_document(self, raw: dict, doc_type: str) -> dict | None:
        """Нормализует ответ API в унифицированный формат."""
        try:
            # Декодируем Base64 контент если есть
            content_raw = raw.get('content', '')
            content_json = {}
            if isinstance(content_raw, str) and content_raw:
                try:
                    decoded = base64.b64decode(content_raw).decode('utf-8')
                    content_json = _json.loads(decoded)
                except Exception:
                    pass

            # Извлекаем данные по типу документа
            inner = content_json.get(doc_type, content_json) if content_json else {}
            head  = inner.get('HEAD', {}) if isinstance(inner, dict) else {}

            # Позиции товаров
            positions = []
            for p in (head.get('POSITION', []) if isinstance(head, dict) else []):
                char = p.get('CHARACTERISTIC', {}) or {}
                positions.append({
                    'ean':      str(p.get('PRODUCT', '')),
                    'name':     char.get('DESCRIPTION', '') if isinstance(char, dict) else '',
                    'qty':      float(p.get('ORDEREDQUANTITY', p.get('DELIVEREDQUANTITY', 0)) or 0),
                    'price':    float(p.get('ORDERPRICE', p.get('PRICEWITHVAT', 0)) or 0),
                    'unit':     p.get('ORDERUNIT', 'PCE'),
                    'vat_rate': p.get('VAT', 0),
                    'amount':   float(p.get('AMOUNTWITHVAT', p.get('AMOUNT', 0)) or 0),
                })

            doc_id = str(raw.get('documentId') or raw.get('docflowId') or raw.get('id') or '')
            number = str(
                inner.get('NUMBER') or
                raw.get('docNumber') or
                'Б/Н'
            )
            raw_date = (
                inner.get('DATE') or
                raw.get('docDate') or ''
            )

            dp_info = head.get('DELIVERYPLACE_INFO', {}) or {}
            return {
                'docrobotId':    doc_id,
                'docType':       doc_type,
                'number':        number,
                'date':          _parse_date(raw_date),
                'delivery_date': _parse_date(inner.get('DELIVERYDATE') or raw.get('docDeliveryDate') or ''),
                'supplierGln':   str(head.get('SUPPLIER') or raw.get('senderGLNid') or ''),
                'buyerGln':      str(head.get('BUYER') or raw.get('receiverGLNid') or ''),
                'supplierName':  'Фуд Завод ТОО',
                'buyerName':     '',
                'totalAmount':   float(inner.get('AMOUNTWITHVAT', inner.get('AMOUNT', 0)) or 0),
                'positions':     positions,
                'raw':           raw,
                'delivery_place_name': dp_info.get('названиеТочки') or dp_info.get('полноеНазвание') or '',
                'delivery_place_addr': dp_info.get('Адрес') or '',
            }
        except Exception as e:
            logger.error(f'Ошибка нормализации документа: {e}')
            return None


# ═══════════════════════════════════════════════════════
# 1С HTTP-сервис
# ═══════════════════════════════════════════════════════

class OneCClient:
    def __init__(self):
        self.url      = settings.ONEC_URL
        self.username = settings.ONEC_USERNAME
        self.password = settings.ONEC_PASSWORD
        self.timeout  = getattr(settings, 'ONEC_TIMEOUT', 30)

    def send(self, xml_bytes: bytes, doc_type: str):
        auth = (self.username, self.password) if self.username else None
        return requests.post(
            self.url,
            data=xml_bytes,
            headers={
                'Content-Type': 'application/xml; charset=utf-8',
                'X-Document-Type': doc_type,
            },
            auth=auth,
            timeout=self.timeout,
        )


def process_document(queue_entry) -> bool:
    doc = queue_entry.document
    onec = OneCClient()
    max_retries = getattr(settings, 'ONEC_MAX_RETRIES', 5)

    if not doc.xml_content:
        try:
            xml_bytes = build_xml(doc.doc_type, doc.raw_json)
            doc.xml_content = xml_bytes.decode('utf-8')
            doc.save(update_fields=['xml_content'])
            logger.debug(f'XML сгенерирован для {doc.doc_type} №{doc.number}')
        except Exception as e:
            logger.error(f'Ошибка генерации XML для {doc}: {e}', exc_info=True)
            queue_entry.mark_error(f'Ошибка XML: {e}', None, max_retries)
            return False

    try:
        resp = onec.send(doc.xml_content.encode('utf-8'), doc.doc_type)
        if 200 <= resp.status_code < 300:
            logger.info(f'Отправлен в 1С: {doc.doc_type} №{doc.number} → HTTP {resp.status_code}')
            queue_entry.mark_sent(resp.text, resp.status_code)
            return True
        else:
            msg = f'HTTP {resp.status_code}: {resp.text[:300]}'
            logger.warning(f'Ошибка отправки {doc.doc_type} №{doc.number}: {msg}')
            queue_entry.mark_error(msg, resp.status_code, max_retries)
            return False
    except Exception as e:
        logger.error(f'Исключение при отправке {doc}: {e}', exc_info=True)
        queue_entry.mark_error(str(e), None, max_retries)
        return False
