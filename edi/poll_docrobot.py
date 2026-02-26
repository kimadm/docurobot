import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Поллинг Docrobot API v3 и отправка документов в 1С'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Один цикл и выйти')
        parser.add_argument('--all', action='store_true', help='Получить все документы (не только unread)')

    def handle(self, *args, **options):
        from edi.services import DocrobotClient
        from edi.models import ConnectionSettings

        client = DocrobotClient()
        cfg = ConnectionSettings.get()
        interval = settings.DOCROBOT_POLL_INTERVAL

        self.stdout.write(self.style.SUCCESS(
            f'Поллинг запущен. Интервал: {interval}с. '
            f'Только непрочитанные: {client.poll_only_unread}. '
            f'Ctrl+C для остановки.'
        ))

        while True:
            try:
                self._poll_cycle(client, only_unread=not options['all'])
                self._process_queue()
                self._maybe_cleanup()
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

    def _poll_cycle(self, client, only_unread: bool = True):
        from edi.models import EdiDocument, SendQueue, ActivityLog

        try:
            documents = client.get_incoming_documents(only_unread=only_unread)
            logger.debug(f'Получено из Docrobot: {len(documents)} документов')
        except Exception as e:
            logger.error(f'Ошибка Docrobot API: {e}', exc_info=True)
            self.stdout.write(self.style.ERROR(f'Ошибка Docrobot: {e}'))
            return

        new_count = 0
        skipped_count = 0

        for normalized in documents:
            try:
                doc_id = normalized.get('docrobotId', '')
                docflow_id = normalized.get('docflowId', '')

                if not doc_id or not docflow_id:
                    logger.warning(f'Пропуск документа без ID: {normalized}')
                    continue

                # Проверяем по docrobot_id И docflow_id
                if EdiDocument.objects.filter(docflow_id=docflow_id).exists():
                    skipped_count += 1
                    continue

                # Создаём документ с новыми полями
                doc = EdiDocument.objects.create(
                    docrobot_id=doc_id,
                    docflow_id=docflow_id,
                    doc_type=normalized['docType'],
                    number=normalized.get('number', ''),
                    doc_date=normalized.get('date') or None,
                    supplier_gln=normalized.get('supplierGln', ''),
                    buyer_gln=normalized.get('buyerGln', ''),
                    supplier_name=normalized.get('supplierName', ''),
                    buyer_name=normalized.get('buyerName', ''),
                    # 🔥 Новые поля статусов
                    doc_status=normalized.get('docStatus', ''),
                    api_status=normalized.get('apiStatus', ''),
                    sign_till=normalized.get('signTill'),
                    timer=normalized.get('timer'),
                    raw_json=normalized,
                )
                SendQueue.objects.create(document=doc)
                new_count += 1

                # Отмечаем как прочитанный сразу (опционально)
                meta = normalized.get('_meta', {})
                if meta:
                    try:
                        client.mark_as_read(
                            meta.get('doc_type', doc.doc_type),
                            docflow_id,
                            doc_id
                        )
                        doc.marked_read_at = timezone.now()
                        doc.save(update_fields=['marked_read_at'])
                    except Exception as e:
                        logger.warning(f'Не удалось отметить документ {doc_id}: {e}')

                logger.info(f'Новый документ: {doc.doc_type} №{doc.number} от {doc.supplier_name}')
                self.stdout.write(self.style.SUCCESS(f'  [+] Новый документ: {doc.doc_type} №{doc.number}'))

            except Exception as e:
                logger.error(f'Ошибка сохранения {normalized.get("docrobotId")}: {e}', exc_info=True)
                self.stdout.write(self.style.ERROR(f'  [!] Ошибка сохранения: {e}'))

        if new_count > 0:
            ActivityLog.objects.create(
                level='info', action='docrobot_poll',
                message=f'Получено новых документов: {new_count}, пропущено: {skipped_count}',
            )
            self.stdout.write(self.style.SUCCESS(f'ИТОГО: Добавлено {new_count}, пропущено {skipped_count}'))
        else:
            self.stdout.write(self.style.WARNING('Новых документов для загрузки нет.'))

    def _process_queue(self):
        from edi.models import SendQueue
        from edi.services import process_document

        # Очередь на отправку
        from django.db.models import Q
        queue = SendQueue.objects.filter(
            Q(status=SendQueue.STATUS_PENDING, next_retry__isnull=True) |
            Q(status=SendQueue.STATUS_ERROR, next_retry__lte=timezone.now())
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

    def _maybe_cleanup(self):
        """Запускает очистку раз в сутки если настроена."""
        import threading
        from django.utils import timezone
        from edi.models import ConnectionSettings, ActivityLog

        try:
            cfg = ConnectionSettings.get()
            if not cfg.cleanup_days:
                return

            today = timezone.now().date()
            already = ActivityLog.objects.filter(
                action='cleanup',
                created_at__date=today,
            ).exists()

            if already:
                return

            def _run():
                from django.core.management import call_command
                call_command('cleanup_old')

            threading.Thread(target=_run, daemon=True).start()
        except Exception:
            pass