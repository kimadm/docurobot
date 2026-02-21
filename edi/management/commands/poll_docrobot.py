"""
edi/management/commands/poll_docrobot.py

Запуск: python manage.py poll_docrobot

Каждые DOCROBOT_POLL_INTERVAL секунд:
  1. Получает входящие документы из Docrobot (все типы за 7 дней)
  2. Сохраняет новые в БД
  3. Добавляет в очередь отправки в 1С
  4. Обрабатывает ожидающие записи очереди
"""
import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Поллинг Docrobot API и отправка документов в 1С'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Один цикл и выйти')

    def handle(self, *args, **options):
        from edi.services import DocrobotClient
        client   = DocrobotClient()
        interval = settings.DOCROBOT_POLL_INTERVAL

        self.stdout.write(self.style.SUCCESS(
            f'Поллинг запущен. Интервал: {interval}с. Ctrl+C для остановки.'
        ))

        while True:
            try:
                self._poll_cycle(client)
                self._process_queue()
            except KeyboardInterrupt:
                self.stdout.write('\nОстановлено.')
                break
            except Exception as e:
                from edi.models import ActivityLog
                logger.error(f'Ошибка цикла: {e}')
                ActivityLog.objects.create(level='error', action='poll_error', message=str(e))

            if options['once']:
                break
            time.sleep(interval)

    def _poll_cycle(self, client):
        from edi.models import EdiDocument, SendQueue, ActivityLog

        try:
            documents = client.get_incoming_documents()
        except Exception as e:
            logger.error(f'Ошибка получения документов: {e}')
            ActivityLog.objects.create(
                level='error', action='docrobot_poll',
                message=f'Не удалось получить документы: {e}',
            )
            return

        new_count = 0
        for normalized in documents:
            try:
                doc_id = normalized.get('docrobotId', '')
                if not doc_id or EdiDocument.objects.filter(docrobot_id=doc_id).exists():
                    continue

                doc = EdiDocument.objects.create(
                    docrobot_id   = doc_id,
                    doc_type      = normalized['docType'],
                    number        = normalized.get('number', ''),
                    doc_date      = normalized.get('date') or None,
                    supplier_gln  = normalized.get('supplierGln', ''),
                    buyer_gln     = normalized.get('buyerGln', ''),
                    supplier_name = normalized.get('supplierName', ''),
                    buyer_name    = normalized.get('buyerName', ''),
                    raw_json      = normalized.get('raw', normalized),
                )
                SendQueue.objects.create(document=doc)
                new_count += 1
                logger.info(f'Новый документ: {doc}')
            except Exception as e:
                logger.error(f'Ошибка сохранения документа: {e}')

        if new_count:
            ActivityLog.objects.create(
                level='info', action='docrobot_poll',
                message=f'Получено новых документов: {new_count}',
            )
        else:
            ActivityLog.objects.create(
                level='info', action='docrobot_poll',
                message='Новых документов нет',
            )

    def _process_queue(self):
        from edi.models import SendQueue
        from edi.services import process_document

        # Pending без next_retry
        pending = list(SendQueue.objects.filter(
            status=SendQueue.STATUS_PENDING, next_retry__isnull=True,
        ).select_related('document')[:20])

        # Error с истёкшим next_retry
        retry = list(SendQueue.objects.filter(
            status=SendQueue.STATUS_ERROR,
            next_retry__lte=timezone.now(),
        ).select_related('document')[:20])

        for entry in pending + retry:
            try:
                entry.status = SendQueue.STATUS_SENDING
                entry.save(update_fields=['status'])
                process_document(entry)
            except Exception as e:
                logger.error(f'Ошибка обработки очереди {entry.id}: {e}')
