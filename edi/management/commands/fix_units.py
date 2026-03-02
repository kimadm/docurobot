"""
edi/management/commands/fix_units.py

Обновляет поле unit в raw_json.positions для всех существующих документов.
Заменяет EDI-коды (PCE, KGM, LTR и т.д.) на читаемые названия (шт, кг, л и т.д.).

Использование:
    python manage.py fix_units
    python manage.py fix_units --dry-run       # только показать, не сохранять
    python manage.py fix_units --doc-type ORDER  # только один тип документов
"""

import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# Тот же маппинг что и в services.py
UNIT_MAP = {
    'PCE': 'шт',
    'PC':  'шт',
    'EA':  'шт',
    'KGM': 'кг',
    'GRM': 'г',
    'LTR': 'л',
    'MLT': 'мл',
    'MTR': 'м',
    'BX':  'кор',
    'CT':  'кор',
    'CS':  'кор',
    'PK':  'уп',
    'PR':  'пара',
    'SET': 'набор',
}


def _map_unit(code: str) -> str:
    if not code:
        return 'шт'
    return UNIT_MAP.get(str(code).upper().strip(), str(code))


class Command(BaseCommand):
    help = 'Обновляет единицы измерения в raw_json всех документов (PCE → шт и т.д.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать что будет изменено без сохранения в БД',
        )
        parser.add_argument(
            '--doc-type',
            type=str,
            default='',
            help='Обрабатывать только указанный тип документа (ORDER, INVOICE и т.д.)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=200,
            help='Размер батча обработки (по умолчанию 200)',
        )

    def handle(self, *args, **options):
        from edi.models import EdiDocument

        dry_run    = options['dry_run']
        doc_type   = options['doc_type'].upper() if options['doc_type'] else ''
        batch_size = options['batch_size']

        if dry_run:
            self.stdout.write(self.style.WARNING('⚠ DRY-RUN режим — изменения не сохраняются'))

        qs = EdiDocument.objects.exclude(raw_json__isnull=True)
        if doc_type:
            qs = qs.filter(doc_type=doc_type)

        total     = qs.count()
        updated   = 0
        skipped   = 0
        processed = 0

        self.stdout.write(f'Найдено документов: {total}')

        # Обрабатываем батчами чтобы не грузить память
        offset = 0
        while offset < total:
            batch = list(qs[offset:offset + batch_size])
            to_save = []

            for doc in batch:
                raw       = doc.raw_json or {}
                positions = raw.get('positions', [])

                if not positions:
                    skipped += 1
                    continue

                changed = False
                for pos in positions:
                    old_unit = pos.get('unit', '')
                    new_unit = _map_unit(old_unit)
                    if old_unit != new_unit:
                        pos['unit'] = new_unit
                        changed = True

                if changed:
                    doc.raw_json = raw
                    to_save.append(doc)
                    updated += 1
                else:
                    skipped += 1

            if to_save and not dry_run:
                EdiDocument.objects.bulk_update(to_save, ['raw_json'])

            processed += len(batch)
            self.stdout.write(
                f'  Обработано {processed}/{total} '
                f'(обновлено: {updated}, без изменений: {skipped})'
            )

            offset += batch_size

        # Итог
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY-RUN завершён. Было бы обновлено: {updated} документов.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Готово! Обновлено: {updated} документов, без изменений: {skipped}.'
            ))
