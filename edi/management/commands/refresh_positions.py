"""
Массовое обновление документов без позиций из Docrobot API.
Запуск: python manage.py refresh_positions
        python manage.py refresh_positions --limit 20
        python manage.py refresh_positions --all   (включая документы с позициями)
"""
import time
from django.core.management.base import BaseCommand
from edi.models import EdiDocument, ActivityLog
from edi.services import DocrobotClient


class Command(BaseCommand):
    help = 'Обновить документы без позиций из Docrobot API'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0,
                            help='Максимум документов (0 = все)')
        parser.add_argument('--all', action='store_true',
                            help='Обновить все документы, включая те что уже с позициями')
        parser.add_argument('--delay', type=float, default=0.5,
                            help='Пауза между запросами в секундах (по умолчанию 0.5)')

    def handle(self, *args, **options):
        client = DocrobotClient()

        # Выбираем документы
        qs = EdiDocument.objects.filter(doc_type='ORDER').order_by('-received_at')
        if not options['all']:
            # Без позиций ИЛИ без места доставки
            docs_to_update = []
            for doc in qs:
                raw = doc.raw_json or {}
                if not raw.get('positions') or not raw.get('delivery_place_name'):
                    docs_to_update.append(doc)
        else:
            docs_to_update = list(qs)

        if options['limit']:
            docs_to_update = docs_to_update[:options['limit']]

        total = len(docs_to_update)
        self.stdout.write(f'Найдено документов для обновления: {total}')

        if total == 0:
            self.stdout.write(self.style.SUCCESS('Все документы уже имеют позиции.'))
            return

        updated = 0
        failed = 0

        for i, doc in enumerate(docs_to_update, 1):
            raw = doc.raw_json or {}
            doc_id  = raw.get('docrobotId') or (raw.get('raw') or {}).get('documentId', '')
            flow_id = (raw.get('raw') or {}).get('docflowId', '')

            self.stdout.write(f'[{i}/{total}] {doc.doc_type} №{doc.number} ({doc_id[:8]}...)', ending=' ')

            try:
                content = client._fetch_content(doc.doc_type, doc_id, flow_id)
                if not content or not content.get('content'):
                    self.stdout.write(self.style.WARNING('— нет содержимого'))
                    failed += 1
                    continue

                normalized = client.normalize_document(content, doc.doc_type)
                if not normalized:
                    self.stdout.write(self.style.WARNING('— ошибка нормализации'))
                    failed += 1
                    continue

                positions_count = len(normalized.get('positions') or [])

                doc.raw_json      = normalized
                doc.number        = normalized.get('number') or doc.number
                doc.doc_date      = normalized.get('date') or doc.doc_date
                doc.supplier_gln  = normalized.get('supplierGln') or doc.supplier_gln
                doc.buyer_gln     = normalized.get('buyerGln') or doc.buyer_gln
                doc.supplier_name = normalized.get('supplierName') or doc.supplier_name
                doc.buyer_name    = normalized.get('buyerName') or doc.buyer_name
                doc.save()

                updated += 1
                self.stdout.write(self.style.SUCCESS(f'✓ {positions_count} позиций'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ {e}'))
                failed += 1

            # Пауза чтобы не перегружать API
            if i < total:
                time.sleep(options['delay'])

        ActivityLog.objects.create(
            level='info',
            action='bulk_refresh',
            message=f'Массовое обновление: {updated} обновлено, {failed} ошибок из {total}',
        )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Готово: обновлено {updated}, ошибок {failed}, всего {total}'
        ))
