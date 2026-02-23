import base64
import json as _json
import logging
import time as _time
from datetime import date, datetime, timedelta

import requests
from django.conf import settings
from .xml_builder import build_xml

logger = logging.getLogger(__name__)


class DocrobotClient:
    """Клиент Docrobot API v1 — Автоматическое декодирование товаров и данных."""

    def __init__(self):
        self.base_url = "https://edi-api.docrobot.kz"
        self.username = settings.DOCROBOT_USERNAME
        self.password = settings.DOCROBOT_PASSWORD
        self.gln = "9845000099712"
        self._token = None

    def _get_token(self) -> str:
        if self._token: return self._token
        resp = requests.post(
            f"{self.base_url}/api/v1/auth",
            json={'login': self.username, 'password': self.password},
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        resp.raise_for_status()
        self._token = resp.json().get('token')
        return self._token

    def _headers(self, with_gln=True) -> dict:
        headers = {
            'Authorization': self._get_token(),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if with_gln: headers['gln'] = str(self.gln)
        return headers

    def get_incoming_documents(self) -> list[dict]:
        date_to = date.today()
        date_from = date_to - timedelta(days=30)
        fmt = lambda d: d.strftime('%d-%m-%Y')

        print(f"\n[Docrobot] Поиск за период: {fmt(date_from)} - {fmt(date_to)}")

        all_docs = []
        for doc_type in ['ORDER', 'ORDRSP', 'DESADV', 'INVOICE', 'PRICAT']:
            try:
                docs = self._fetch_type(doc_type, fmt(date_from), fmt(date_to))
                if docs:
                    all_docs.extend(docs)
                    print(f"✅ {doc_type}: Найдено {len(docs)} шт.")
                else:
                    print(f"ℹ️ {doc_type}: Ничего не найдено.")
            except Exception as e:
                print(f"❌ {doc_type}: Ошибка: {e}")
        return all_docs

    def _fetch_type(self, doc_type: str, d_from: str, d_to: str) -> list[dict]:
        list_url = f"{self.base_url}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/{doc_type}"
        params = {'gln': self.gln, 'docDateFrom': d_from, 'docDateTo': d_to, 'page': 0, 'pageSize': 50}

        resp = requests.get(list_url, params=params, headers=self._headers(), timeout=30)
        resp.raise_for_status()

        items = resp.json().get('items') or []
        result = []
        for item in items:
            doc_id = item.get('documentId')
            flow_id = item.get('docflowId')
            doc_data = self._try_get_content(doc_type, doc_id, flow_id)
            if doc_data:
                normalized = self.normalize_document(doc_data, doc_type)
                if normalized: result.append(normalized)
        return result

    def _try_get_content(self, doc_type, doc_id, flow_id):
        paths = [
            f"{self.base_url}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/{doc_type}/document/{doc_id}",
            f"{self.base_url}/api/v1/document/{doc_id}"
        ]
        for path in paths:
            try:
                r = requests.get(path, headers=self._headers(with_gln=True), params={'gln': self.gln}, timeout=15)
                if r.status_code == 200: return r.json()
            except:
                continue
        return None

    def normalize_document(self, raw: dict, doc_type: str) -> dict | None:
        """Декодирует Base64 и вытаскивает все данные заказа в чистый JSON."""
        try:
            # 1. Декодируем скрытый контент (Base64 -> JSON)
            content_raw = raw.get('content', '')
            content_json = {}
            if isinstance(content_raw, str) and content_raw:
                decoded = base64.b64decode(content_raw).decode('utf-8')
                content_json = _json.loads(decoded)

            # 2. Извлекаем внутренние данные (Docrobot KZ v1 хранит всё в ключе типа документа)
            inner_data = content_json.get(doc_type, {})
            head = inner_data.get('HEAD', {})

            # 3. Парсим товары (позиции)
            items = []
            for p in head.get('POSITION', []):
                char = p.get('CHARACTERISTIC', {}) or {}
                items.append({
                    'ean': str(p.get('PRODUCT', '')),
                    'name': char.get('DESCRIPTION', 'Без названия'),
                    'qty': float(p.get('ORDEREDQUANTITY', 0)),
                    'price': float(p.get('ORDERPRICE', 0)),
                    'unit': p.get('ORDERUNIT', 'PCE'),
                    'vat_rate': p.get('VAT', 0),
                    'sum_vat': float(p.get('PRICEWITHVAT', 0)) * float(p.get('ORDEREDQUANTITY', 0))
                })

            # 4. Собираем итоговую структуру (без вложенного Base64)
            return {
                'docrobotId': str(raw.get('documentId') or raw.get('docflowId')),
                'docType': doc_type,
                'number': str(inner_data.get('NUMBER') or raw.get('docNumber') or 'Б/Н'),
                'date': str(inner_data.get('DATE') or raw.get('docDate')),
                'delivery_date': str(inner_data.get('DELIVERYDATE') or ''),
                'supplierGln': str(head.get('SUPPLIER') or raw.get('senderGLNid') or ''),
                'buyerGln': str(head.get('BUYER') or raw.get('receiverGLNid') or ''),
                'supplierName': "Фуд Завод ТОО",
                'totalAmount': float(inner_data.get('AMOUTWITHVAT', 0) or inner_data.get('AMOUNTWITHVAT', 0)),
                'positions': items,  # Все товары здесь в открытом виде
                'raw': raw  # Сохраняем оригинал на всякий случай
            }
        except Exception as e:
            logger.error(f"Ошибка нормализации документа: {e}")
            return None


# ═══════════════════════════════════════════════════
# 1С Logic
# ═══════════════════════════════════════════════════

class OneCClient:
    def __init__(self):
        self.url = settings.ONEC_URL
        self.auth = (settings.ONEC_USERNAME, settings.ONEC_PASSWORD)

    def send(self, xml_bytes: bytes, doc_type: str):
        return requests.post(
            self.url, data=xml_bytes,
            headers={'Content-Type': 'application/xml; charset=utf-8', 'X-Document-Type': doc_type},
            auth=self.auth, timeout=30
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
        except Exception as e:
            queue_entry.mark_error(f"Ошибка XML: {e}", None, max_retries)
            return False

    try:
        resp = onec.send(doc.xml_content.encode('utf-8'), doc.doc_type)
        if 200 <= resp.status_code < 300:
            queue_entry.mark_sent(resp.text, resp.status_code)
            return True
        else:
            msg = f"1C HTTP {resp.status_code}: {resp.text[:200]}"
            queue_entry.mark_error(msg, resp.status_code, max_retries)
            return False
    except Exception as e:
        queue_entry.mark_error(str(e), None, max_retries)
        return False