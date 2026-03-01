from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.dashboard,        name='dashboard'),
    path('documents/',          views.documents,        name='documents'),
    path('documents/<int:pk>/', views.document_detail,  name='document_detail'),
    path('logs/',               views.logs,             name='logs'),
    path('reports/',            views.reports,          name='reports'),
    path('reports/export/',     views.reports_export,   name='reports_export'),
    # Настройки и шаблоны
    path('settings/',                views.settings_view,  name='settings'),
    path('settings/<str:doc_type>/', views.template_edit,  name='template_edit'),
    # Подключения
    path('connections/',             views.connections_view, name='connections'),
    # API
    path('api/retry/<int:pk>/',    views.api_retry,          name='api_retry'),
    path('api/send/<int:pk>/',     views.api_send_document,  name='api_send'),
    path('api/webhook/',           views.api_webhook,        name='api_webhook'),
    path('api/test-xml/',          views.api_test_xml,       name='api_test_xml'),
    path('api/test-send/',         views.api_test_send,      name='api_test_send'),
    path('api/test-docrobot/',     views.api_test_docrobot,  name='api_test_docrobot'),
    path('api/test-onec/',         views.api_test_onec,      name='api_test_onec'),
    path('api/search/',            views.api_search,         name='api_search'),
    path('api/poll-now/',          views.api_poll_now,       name='api_poll_now'),
    path('health/',                views.healthcheck,        name='healthcheck'),
    path('api/dashboard/stats/',   views.api_dashboard_stats, name='api_dashboard_stats'),
    path('backup/',                views.backup_db,          name='backup_db'),
    path('api/cleanup/',           views.api_cleanup_now,    name='api_cleanup'),
    path('suppliers/',             views.suppliers,          name='suppliers'),
    path('daily-report/',          views.daily_report,         name='daily_report'),
    path('daily-report/grouped/',  views.daily_report_grouped, name='daily_report_grouped'),
    path('api/refresh/<int:pk>/',              views.api_refresh_document, name='api_refresh'),
    path('api/comments/<int:pk>/add/',          views.api_comment_add,    name='api_comment_add'),
    path('api/comments/<int:comment_id>/delete/', views.api_comment_delete, name='api_comment_delete'),
    path('log-files/',             views.log_files,          name='log_files'),
]
