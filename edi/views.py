"""
edi/views.py — Представления: дашборд, отчёты, API-действия

GET  /                   — дашборд
GET  /documents/         — список документов
GET  /documents/<id>/    — детали + XML-просмотр
GET  /queue/             — очередь отправки
GET  /logs/              — логи активности
GET  /reports/           — отчёты и статистика
GET  /reports/export/    — экспорт в CSV

POST /api/retry/<id>/    — повторить отправку вручную
POST /api/send/<id>/     — отправить документ вручную
POST /api/webhook/       — вебхук: принять документ от Docrobot
"""
import json
import csv
import io
from datetime import date, timedelta, datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import EdiDocument, SendQueue, ActivityLog
from .services import process_document, DocrobotClient
from .xml_builder import build_xml


# ─── Дашборд ─────────────────────────────────────────────

def dashboard(request):
    # Статистика по статусам очереди
    queue_stats = {
        row['status']: row['cnt']
        for row in SendQueue.objects.values('status').annotate(cnt=Count('id'))
    }
    # Статистика по типам документов
    doc_stats = {
        row['doc_type']: row['cnt']
        for row in EdiDocument.objects.values('doc_type').annotate(cnt=Count('id'))
    }
    # Последние 8 документов
    recent_docs  = EdiDocument.objects.select_related('queue_entry').order_by('-received_at')[:8]
    # Ошибочные записи
    errors       = SendQueue.objects.filter(
        status__in=[SendQueue.STATUS_ERROR, SendQueue.STATUS_FAILED]
    ).select_related('document').order_by('-updated_at')[:5]
    # Последние 10 логов
    recent_logs  = ActivityLog.objects.order_by('-created_at')[:10]
    # Динамика за 7 дней
    seven_days = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        cnt = EdiDocument.objects.filter(received_at__date=day).count()
        seven_days.append({'day': day.strftime('%d.%m'), 'count': cnt})

    return render(request, 'edi/dashboard.html', {
        'queue_stats': queue_stats,
        'doc_stats':   doc_stats,
        'recent_docs': recent_docs,
        'errors':      errors,
        'recent_logs': recent_logs,
        'seven_days':  json.dumps(seven_days),
        'total_docs':  EdiDocument.objects.count(),
        'total_sent':  SendQueue.objects.filter(status=SendQueue.STATUS_SENT).count(),
        'total_errors':SendQueue.objects.filter(status__in=[SendQueue.STATUS_ERROR, SendQueue.STATUS_FAILED]).count(),
        'pending':     SendQueue.objects.filter(status=SendQueue.STATUS_PENDING).count(),
    })


# ─── Документы ───────────────────────────────────────────

def documents(request):
    qs = EdiDocument.objects.select_related('queue_entry').order_by('-received_at')
    # Фильтры
    doc_type = request.GET.get('type', '')
    search   = request.GET.get('q', '')
    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')

    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if search:
        qs = qs.filter(Q(number__icontains=search) | Q(supplier_name__icontains=search) | Q(buyer_name__icontains=search))
    if date_from:
        qs = qs.filter(received_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(received_at__date__lte=date_to)

    return render(request, 'edi/documents.html', {
        'documents': qs[:100],
        'doc_types': EdiDocument.DOC_TYPES,
        'filters': {'type': doc_type, 'q': search, 'date_from': date_from, 'date_to': date_to},
    })


def document_detail(request, pk):
    doc = get_object_or_404(EdiDocument, pk=pk)
    queue = getattr(doc, 'queue_entry', None)
    logs  = doc.logs.order_by('-created_at')

    # Генерируем XML для просмотра если нет
    if not doc.xml_content and doc.raw_json:
        try:
            doc.xml_content = build_xml(doc.doc_type, doc.raw_json).decode('utf-8')
            doc.save(update_fields=['xml_content'])
        except Exception:
            pass

    return render(request, 'edi/document_detail.html', {
        'doc': doc, 'queue': queue, 'logs': logs,
    })


# ─── Очередь ─────────────────────────────────────────────

def queue(request):
    qs = SendQueue.objects.select_related('document').order_by('-updated_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(status=status_filter)
    return render(request, 'edi/queue.html', {
        'entries': qs[:100],
        'statuses': SendQueue.STATUSES,
        'filter_status': status_filter,
    })


# ─── Логи ────────────────────────────────────────────────

def logs(request):
    qs = ActivityLog.objects.select_related('document').order_by('-created_at')
    level = request.GET.get('level', '')
    action = request.GET.get('action', '')
    if level:
        qs = qs.filter(level=level)
    if action:
        qs = qs.filter(action__icontains=action)
    return render(request, 'edi/logs.html', {
        'logs': qs[:200],
        'levels': ActivityLog.LEVELS,
        'filter_level': level,
        'filter_action': action,
    })


# ─── Отчёты ──────────────────────────────────────────────

def reports(request):
    # Период
    days = int(request.GET.get('days', 30))
    since = timezone.now() - timedelta(days=days)

    # Документы по типам за период
    by_type = list(
        EdiDocument.objects.filter(received_at__gte=since)
        .values('doc_type').annotate(cnt=Count('id'))
        .order_by('-cnt')
    )
    # Успешно / с ошибкой
    sent_count   = SendQueue.objects.filter(status=SendQueue.STATUS_SENT, updated_at__gte=since).count()
    failed_count = SendQueue.objects.filter(status=SendQueue.STATUS_FAILED, updated_at__gte=since).count()
    error_count  = SendQueue.objects.filter(status=SendQueue.STATUS_ERROR, updated_at__gte=since).count()

    # Топ поставщиков
    top_suppliers = list(
        EdiDocument.objects.filter(received_at__gte=since)
        .values('supplier_name').annotate(cnt=Count('id'))
        .order_by('-cnt')[:10]
    )
    # Динамика по дням
    daily = []
    for i in range(days - 1, -1, -1):
        day = date.today() - timedelta(days=i)
        cnt = EdiDocument.objects.filter(received_at__date=day).count()
        err = SendQueue.objects.filter(updated_at__date=day, status__in=[SendQueue.STATUS_ERROR, SendQueue.STATUS_FAILED]).count()
        daily.append({'day': day.strftime('%d.%m'), 'count': cnt, 'errors': err})

    return render(request, 'edi/reports.html', {
        'days': days,
        'by_type': by_type,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'error_count': error_count,
        'top_suppliers': top_suppliers,
        'daily_json': json.dumps(daily),
        'total_period': EdiDocument.objects.filter(received_at__gte=since).count(),
    })


def reports_export(request):
    """Экспорт всех документов за период в CSV (UTF-8 с BOM для Excel)."""
    days  = int(request.GET.get('days', 30))
    since = timezone.now() - timedelta(days=days)
    docs  = EdiDocument.objects.filter(received_at__gte=since).select_related('queue_entry').order_by('-received_at')

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ID Docrobot', 'Тип', 'Номер', 'Дата', 'Поставщик', 'Покупатель', 'Статус очереди', 'Попыток', 'Получен'])
    for d in docs:
        q = getattr(d, 'queue_entry', None)
        writer.writerow([
            d.docrobot_id, d.get_doc_type_display(), d.number,
            d.doc_date or '', d.supplier_name, d.buyer_name,
            q.get_status_display() if q else '—',
            q.attempts if q else 0,
            d.received_at.strftime('%d.%m.%Y %H:%M'),
        ])

    content = '\ufeff' + buf.getvalue()  # BOM для Excel
    response = HttpResponse(content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="edi-report-{date.today()}.csv"'
    return response


# ─── API: ручные действия ────────────────────────────────

@api_view(['POST'])
def api_retry(request, pk):
    """Повторить отправку записи очереди вручную."""
    entry = get_object_or_404(SendQueue, pk=pk)
    if entry.status in [SendQueue.STATUS_SENT]:
        return Response({'error': 'Документ уже отправлен'}, status=400)

    entry.status     = SendQueue.STATUS_PENDING
    entry.next_retry = None
    entry.save(update_fields=['status', 'next_retry'])

    success = process_document(entry)
    entry.refresh_from_db()
    return Response({
        'success': success,
        'status':  entry.status,
        'error':   entry.last_error,
    })


@api_view(['POST'])
def api_send_document(request, pk):
    """Отправить конкретный документ в 1С."""
    doc   = get_object_or_404(EdiDocument, pk=pk)
    entry, _ = SendQueue.objects.get_or_create(document=doc)
    entry.status     = SendQueue.STATUS_PENDING
    entry.next_retry = None
    entry.save(update_fields=['status', 'next_retry'])
    success = process_document(entry)
    entry.refresh_from_db()
    return Response({'success': success, 'status': entry.status, 'error': entry.last_error})


@csrf_exempt
@require_POST
def api_webhook(request):
    """
    Вебхук: Docrobot отправляет документ → сохраняем → добавляем в очередь.
    POST /api/webhook/
    Body: JSON с полями документа
    """
    try:
        raw = json.loads(request.body)
        client = DocrobotClient()
        normalized = client.normalize_document(raw)
        doc_id = normalized['docrobotId']

        if not doc_id:
            return JsonResponse({'error': 'docrobotId обязателен'}, status=400)

        doc, created = EdiDocument.objects.get_or_create(
            docrobot_id=doc_id,
            defaults={
                'doc_type':      normalized['docType'],
                'number':        normalized['number'],
                'doc_date':      normalized['date'] or None,
                'supplier_gln':  normalized['supplierGln'],
                'buyer_gln':     normalized['buyerGln'],
                'supplier_name': normalized['supplierName'],
                'buyer_name':    normalized['buyerName'],
                'raw_json':      normalized['raw'],
            }
        )
        if created:
            SendQueue.objects.create(document=doc)
            ActivityLog.objects.create(
                level='info', action='webhook_received',
                message=f'Получен документ {doc}', document=doc,
            )
        return JsonResponse({'saved': created, 'id': doc.id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ─── Настройки: XML-шаблоны ──────────────────────────────

def settings_view(request):
    """Страница настроек: шаблоны XML, параметры 1С."""
    from .models import XmlTemplate
    from .xml_builder import DEFAULT_TEMPLATES

    # Авто-создание дефолтных шаблонов при первом открытии
    for doc_type, tpl_data in DEFAULT_TEMPLATES.items():
        XmlTemplate.objects.get_or_create(
            doc_type=doc_type,
            defaults={
                'name':         tpl_data['name'],
                'position_tpl': tpl_data['position_tpl'],
                'body_tpl':     tpl_data['body_tpl'],
            }
        )

    templates = XmlTemplate.objects.all().order_by('doc_type')

    VARS = [
        ('{{number}}',         'Номер документа'),
        ('{{date}}',           'Дата документа'),
        ('{{delivery_date}}',  'Дата доставки'),
        ('{{supplier_gln}}',   'GLN поставщика'),
        ('{{supplier_name}}',  'Название поставщика'),
        ('{{buyer_gln}}',      'GLN покупателя'),
        ('{{buyer_name}}',     'Название покупателя'),
        ('{{currency}}',       'Валюта'),
        ('{{order_number}}',   'Номер заказа-основания'),
        ('{{shipment_date}}',  'Дата отгрузки'),
        ('{{total_amount}}',   'Сумма без НДС'),
        ('{{total_vat}}',      'Сумма НДС'),
        ('{{total_with_vat}}', 'Сумма с НДС'),
        ('{{positions}}',      'Блок позиций (из шаблона позиции)'),
        ('{{positions_json}}', 'Позиции как JSON'),
        ('{{raw_json}}',       'Весь документ как JSON'),
    ]

    return render(request, 'edi/settings.html', {'templates': templates, 'vars': VARS})


def template_edit(request, doc_type):
    """Редактирование конкретного XML-шаблона."""
    from .models import XmlTemplate
    tpl = get_object_or_404(XmlTemplate, doc_type=doc_type)

    if request.method == 'POST':
        tpl.name         = request.POST.get('name', tpl.name)
        tpl.body_tpl     = request.POST.get('body_tpl', tpl.body_tpl)
        tpl.position_tpl = request.POST.get('position_tpl', tpl.position_tpl)
        tpl.content_type = request.POST.get('content_type', tpl.content_type)
        tpl.is_active    = request.POST.get('is_active') == 'on'
        tpl.save()
        ActivityLog.objects.create(
            level='info', action='template_updated',
            message=f'Шаблон {doc_type} обновлён',
        )
        return redirect('settings')

    doc_vars = [
        'number', 'date', 'delivery_date', 'supplier_gln', 'supplier_name',
        'buyer_gln', 'buyer_name', 'currency', 'order_number', 'shipment_date',
        'total_amount', 'total_vat', 'total_with_vat', 'positions', 'positions_json', 'raw_json',
    ]
    pos_vars = ['line', 'ean', 'item_code', 'item_name', 'quantity', 'unit_price', 'vat', 'amount', 'amount_with_vat']

    return render(request, 'edi/template_edit.html', {
        'tpl': tpl, 'doc_vars': doc_vars, 'pos_vars': pos_vars,
    })


@api_view(['POST'])
def api_test_xml(request):
    """
    Рендерит шаблон с тестовыми данными и возвращает XML.
    Тело запроса: { doc_type, body_tpl, position_tpl, sample_data (опц.) }
    """
    from .models import XmlTemplate

    doc_type     = request.data.get('doc_type', 'ORDER')
    body_tpl     = request.data.get('body_tpl', '')
    position_tpl = request.data.get('position_tpl', '')

    sample = request.data.get('sample_data') or {
        'number':       'TEST-001',
        'date':         '2026-02-20',
        'deliveryDate': '2026-02-25',
        'supplierGln':  '4600000000001',
        'supplierName': 'ТОО Поставщик',
        'buyerGln':     '4600000000002',
        'buyerName':    'ТОО Покупатель',
        'currency':     'KZT',
        'orderNumber':  'ORD-001',
        'totalAmount':  '10000',
        'totalVat':     '1200',
        'totalWithVat': '11200',
        'positions': [
            {
                'ean': '4600123456789', 'itemCode': 'SKU-001',
                'itemName': 'Товар тестовый', 'quantity': 10,
                'unitPrice': 1000, 'vat': 12, 'amount': 10000, 'amountWithVat': 11200,
            }
        ],
    }

    tpl = XmlTemplate(doc_type=doc_type, name='test', body_tpl=body_tpl, position_tpl=position_tpl)
    try:
        xml = tpl.render(sample)
        return Response({'xml': xml, 'success': True})
    except Exception as e:
        return Response({'error': str(e), 'success': False}, status=400)


@api_view(['POST'])
def api_test_send(request):
    """
    Отправляет тестовый XML в 1С и возвращает результат.
    Тело: { doc_type, xml (строка) }
    """
    from .services import OneCClient
    doc_type = request.data.get('doc_type', 'ORDER')
    xml_str  = request.data.get('xml', '')
    if not xml_str:
        return Response({'error': 'xml обязателен'}, status=400)
    try:
        client = OneCClient()
        code, resp = client.send(xml_str.encode('utf-8'), doc_type)
        ActivityLog.objects.create(
            level='info' if 200 <= code < 300 else 'warn',
            action='test_send',
            message=f'Тест {doc_type}: HTTP {code} → {resp[:200]}',
        )
        return Response({'http_status': code, 'response': resp, 'success': 200 <= code < 300})
    except Exception as e:
        return Response({'error': str(e), 'success': False}, status=500)


# ─── Страница подключений ─────────────────────────────────

def connections_view(request):
    """Страница настройки подключений к Docrobot и 1С."""
    from .models import ConnectionSettings
    cfg = ConnectionSettings.get()

    if request.method == 'POST':
        cfg.docrobot_url           = request.POST.get('docrobot_url', cfg.docrobot_url).strip()
        cfg.docrobot_username      = request.POST.get('docrobot_username', '').strip()
        new_dr_pass                = request.POST.get('docrobot_password', '').strip()
        if new_dr_pass:
            cfg.docrobot_password  = new_dr_pass
        cfg.docrobot_poll_interval = int(request.POST.get('docrobot_poll_interval', 60))

        cfg.onec_url      = request.POST.get('onec_url', cfg.onec_url).strip()
        cfg.onec_username = request.POST.get('onec_username', '').strip()
        new_1c_pass       = request.POST.get('onec_password', '').strip()
        if new_1c_pass:
            cfg.onec_password = new_1c_pass
        cfg.onec_timeout  = int(request.POST.get('onec_timeout', 30))

        cfg.telegram_token   = request.POST.get('telegram_token', '').strip()
        cfg.telegram_chat_id = request.POST.get('telegram_chat_id', '').strip()

        cfg.save()
        cfg.apply_to_django_settings()

        ActivityLog.objects.create(
            level='info', action='settings_saved',
            message='Настройки подключений обновлены',
        )
        return redirect('connections')

    return render(request, 'edi/connections.html', {'cfg': cfg})


@api_view(['POST'])
def api_test_docrobot(request):
    """Тест авторизации в Docrobot — использует данные из запроса или из БД."""
    from .models import ConnectionSettings
    import requests as req

    url      = request.data.get('url', '').strip()
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '').strip()

    # Если пароль не передан — берём из БД
    if not password:
        cfg = ConnectionSettings.get()
        password = cfg.docrobot_password

    if not url or not username:
        return Response({'success': False, 'error': 'URL и логин обязательны'}, status=400)

    try:
        resp = req.post(
            f'{url.rstrip("/")}/api/v1/auth',
            json={'login': username, 'password': password},
            headers={'Content-type': 'application/json'},
            timeout=15,
        )
        data = resp.json() if resp.content else {}

        if resp.status_code == 200:
            token = data.get('token') or data.get('access_token') or data.get('accessToken', '')
            # Сохраняем статус
            from .models import ConnectionSettings
            from django.utils import timezone
            cfg = ConnectionSettings.get()
            cfg.docrobot_status    = 'ok'
            cfg.docrobot_tested_at = timezone.now()
            cfg.save(update_fields=['docrobot_status', 'docrobot_tested_at'])

            ActivityLog.objects.create(level='info', action='docrobot_auth_ok',
                message=f'Авторизация Docrobot успешна: {username}@{url}')
            return Response({'success': True, 'token_preview': token[:20] + '...' if token else '(пусто)', 'http_status': 200})
        else:
            cfg = ConnectionSettings.get()
            cfg.docrobot_status = 'error'
            cfg.save(update_fields=['docrobot_status'])
            ActivityLog.objects.create(level='error', action='docrobot_auth_fail',
                message=f'Ошибка авторизации Docrobot HTTP {resp.status_code}: {resp.text[:200]}')
            return Response({'success': False, 'error': f'HTTP {resp.status_code}: {resp.text[:300]}', 'http_status': resp.status_code})

    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['POST'])
def api_test_onec(request):
    """Тест подключения к 1С HTTP-сервису."""
    import requests as req

    url      = request.data.get('url', '').strip()
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '').strip()

    if not password:
        from .models import ConnectionSettings
        cfg = ConnectionSettings.get()
        password = cfg.onec_password

    if not url:
        return Response({'success': False, 'error': 'URL обязателен'}, status=400)

    try:
        auth = (username, password) if username else None
        resp = req.get(
            url,
            auth=auth,
            headers={'Accept': 'application/xml, text/xml, */*'},
            timeout=10,
        )
        from .models import ConnectionSettings
        from django.utils import timezone
        cfg = ConnectionSettings.get()

        # 1С может ответить 200, 400, 405 — всё это значит "доступен"
        reachable = resp.status_code < 500
        cfg.onec_status    = 'ok' if reachable else 'error'
        cfg.onec_tested_at = timezone.now()
        cfg.save(update_fields=['onec_status', 'onec_tested_at'])

        ActivityLog.objects.create(
            level='info' if reachable else 'error',
            action='onec_test',
            message=f'Тест 1С {url}: HTTP {resp.status_code}',
        )
        return Response({
            'success':     reachable,
            'http_status': resp.status_code,
            'response':    resp.text[:300],
            'note':        'Статус < 500 означает что сервер доступен' if reachable else 'Сервер недоступен',
        })
    except req.exceptions.ConnectionError:
        return Response({'success': False, 'error': 'Не удалось подключиться — проверьте URL и что 1С запущен'}, status=200)
    except req.exceptions.Timeout:
        return Response({'success': False, 'error': 'Таймаут — 1С не отвечает за 10 секунд'}, status=200)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)
