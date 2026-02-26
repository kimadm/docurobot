"""
manage.py cleanup_old — Удаление старых документов и сжатие БД.
Настройка: поле cleanup_days в ConnectionSettings (0 = не удалять).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Удаляет старые документы и делает VACUUM SQLite'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None,
                            help='Удалить документы старше N дней (переопределяет настройки БД)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Показать что будет удалено, но не удалять')
        parser.add_argument('--vacuum', action='store_true', default=True,
                            help='Выполнить VACUUM после удаления (по умолчанию: да)')

    def handle(self, *args, **options):
        from edi.models import EdiDocument, ActivityLog, ConnectionSettings

        # Определяем порог
        days = options['days']
        if days is None:
            cfg  = ConnectionSettings.get()
            days = cfg.cleanup_days

        if not days or days <= 0:
            self.stdout.write(self.style.WARNING('Автоочистка отключена (cleanup_days = 0). Используйте --days N'))
            return

        threshold = timezone.now() - timedelta(days=days)
        dry_run   = options['dry_run']

        # Считаем что удалим
        old_docs = EdiDocument.objects.filter(received_at__lt=threshold)
        old_logs = ActivityLog.objects.filter(created_at__lt=threshold)
        doc_count = old_docs.count()
        log_count = old_logs.count()

        self.stdout.write(f'\n📅 Порог: {threshold.strftime("%d.%m.%Y")} (старше {days} дней)')
        self.stdout.write(f'   Документов к удалению: {doc_count}')
        self.stdout.write(f'   Логов к удалению:       {log_count}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Ничего не удалено.'))
            return

        if doc_count == 0 and log_count == 0:
            self.stdout.write(self.style.SUCCESS('✅ Нечего удалять.'))
            return

        # Удаляем
        deleted_docs, _ = old_docs.delete()
        deleted_logs, _ = old_logs.delete()

        self.stdout.write(self.style.SUCCESS(f'\n✅ Удалено: {deleted_docs} документов, {deleted_logs} логов'))

        # VACUUM — сжимаем SQLite
        if options.get('vacuum', True):
            try:
                from django.db import connection
                with connection.cursor() as cur:
                    cur.execute('VACUUM')
                self.stdout.write(self.style.SUCCESS('✅ VACUUM выполнен — база сжата'))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'VACUUM не выполнен: {e}'))

        # Пишем в лог
        ActivityLog.objects.create(
            level='info', action='cleanup',
            message=f'Автоочистка: удалено {deleted_docs} документов и {deleted_logs} логов старше {days} дней',
        )
