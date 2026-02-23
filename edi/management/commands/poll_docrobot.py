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
            self.stdout.write(self.style.ERROR(f'Ошибка Docrobot: {e}'))
            return

        new_count = 0
        for normalized in documents:
            try:
                doc_id = normalized.get('docrobotId', '')
                if not doc_id:
                    continue

                # Пропускаем, если уже в базе
                if EdiDocument.objects.filter(docrobot_id=doc_id).exists():
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
                    raw_json = normalized,  # Сохраняем уже обработанный нами JSON с позициями
                )
                SendQueue.objects.create(document=doc)
                new_count += 1
                self.stdout.write(self.style.SUCCESS(f'  [+] Новый документ: {doc.doc_type} №{doc.number}'))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [!] Ошибка сохранения {normalized.get("docrobotId")}: {e}'))

        if new_count > 0:
            ActivityLog.objects.create(
                level='info', action='docrobot_poll',
                message=f'Получено новых документов: {new_count}',
            )
            self.stdout.write(self.style.SUCCESS(f'ИТОГО: Добавлено {new_count} новых записей.'))
        else:
            self.stdout.write(self.style.WARNING('Новых документов для загрузки нет.'))

    def _process_queue(self):
        from edi.models import SendQueue
        from edi.services import process_document

        # Очередь на отправку
        queue = SendQueue.objects.filter(
            status__in=[SendQueue.STATUS_PENDING, SendQueue.STATUS_ERROR]
        ).filter(
            next_retry__lte=timezone.now() if timezone.now() else True # Упрощенно для фильтра
        ).select_related('document')[:20]

        if not queue.exists():
            return

        self.stdout.write(f'Обработка очереди отправки в 1С ({queue.count()} записей)...')

        for entry in queue:
            try:
                entry.status = SendQueue.STATUS_SENDING
                entry.save(update_fields=['status'])
                
                success = process_document(entry)
                
                if success:
                    self.stdout.write(self.style.SUCCESS(f'  [>>] {entry.document.number} отправлен в 1С'))
                else:
                    self.stdout.write(self.style.ERROR(f'  [XX] {entry.document.number} — ошибка 1С'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [!] Ошибка очереди {entry.id}: {e}'))