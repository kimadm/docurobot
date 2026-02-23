"""
edi/management/commands/poll_docrobot.py

Фоновая команда, которую нужно запускать в отдельном окне:
  python manage.py poll_docrobot

Каждые DOCROBOT_POLL_INTERVAL секунд:
  1. Получает входящие документы из Docrobot
  2. Сохраняет новые в БД
  3. Добавляет в очередь отправки
  4. Обрабатывает ожидающие и ошибочные записи очереди
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
        parser.add_argument(
            '--once', action='store_true',
            help='Выполнить один цикл и выйти (для тестирования)',
        )

    def handle(self, *args, **options):
        from edi.models import EdiDocument, SendQueue, ActivityLog
        from edi.services import DocrobotClient, process_document

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
                logger.error(f'Ошибка цикла поллинга: {e}')
                ActivityLog.objects.create(
                    level='error', action='poll_error',
                    message=str(e),
                )

            if options['once']:
                break
            time.sleep(interval)

    def _poll_cycle(self, client):
        """Получает входящие документы и добавляет новые в очередь."""
        from edi.models import EdiDocument, SendQueue, ActivityLog

        try:
            documents = client.get_incoming_documents()
        except Exception as e:
            logger.error(f'Ошибка получения документов из Docrobot: {e}')
            ActivityLog.objects.create(
                level='error', action='docrobot_poll',
                message=f'Не удалось получить документы: {e}',
            )
            return

        new_count = 0
        for raw in documents:
            try:
                normalized = client.normalize_document(raw)
                doc_id = normalized['docrobotId']

                if not doc_id or EdiDocument.objects.filter(docrobot_id=doc_id).exists():
                    continue

                doc = EdiDocument.objects.create(
                    docrobot_id   = doc_id,
                    doc_type      = normalized['docType'],
                    number        = normalized['number'],
                    doc_date      = normalized['date'] or None,
                    supplier_gln  = normalized['supplierGln'],
                    buyer_gln     = normalized['buyerGln'],
                    supplier_name = normalized['supplierName'],
                    buyer_name    = normalized['buyerName'],
                    raw_json      = normalized['raw'],
                )
                SendQueue.objects.create(document=doc)
                client.mark_received(doc_id)
                new_count += 1

                logger.info(f'Новый документ: {doc}')
            except Exception as e:
                logger.error(f'Ошибка обработки документа {raw.get("id","?")}: {e}')

        if new_count:
            ActivityLog.objects.create(
                level='info', action='docrobot_poll',
                message=f'Получено новых документов: {new_count}',
            )

    def _process_queue(self):
        """Обрабатывает записи очереди в статусах pending и error."""
        from edi.models import SendQueue
        from edi.services import process_document

        entries = SendQueue.objects.filter(
            status__in=[SendQueue.STATUS_PENDING, SendQueue.STATUS_ERROR],
        ).filter(
            # Берём только те, у которых пришло время повтора (или нет ограничения)
            next_retry__lte=timezone.now(),
        ).select_related('document')[:20]

        # Дополнительно берём pending без next_retry
        pending = SendQueue.objects.filter(
            status=SendQueue.STATUS_PENDING,
            next_retry__isnull=True,
        ).select_related('document')[:20]

        all_entries = list(entries) + [e for e in pending if e not in list(entries)]

        for entry in all_entries:
            try:
                entry.status = SendQueue.STATUS_SENDING
                entry.save(update_fields=['status'])
                process_document(entry)
            except Exception as e:
                logger.error(f'Ошибка обработки очереди {entry.id}: {e}')
