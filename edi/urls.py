from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.dashboard,        name='dashboard'),
    path('documents/',          views.documents,        name='documents'),
    path('documents/<int:pk>/', views.document_detail,  name='document_detail'),
    path('queue/',              views.queue,            name='queue'),
    path('logs/',               views.logs,             name='logs'),
    path('reports/',            views.reports,          name='reports'),
    path('reports/export/',     views.reports_export,   name='reports_export'),
    # Настройки и шаблоны
    path('settings/',                views.settings_view,  name='settings'),
    path('settings/<str:doc_type>/', views.template_edit,  name='template_edit'),
    # Подключения
    path('connections/',             views.connections_view,   name='connections'),
    # API
    path('api/retry/<int:pk>/',    views.api_retry,          name='api_retry'),
    path('api/send/<int:pk>/',     views.api_send_document,  name='api_send'),
    path('api/webhook/',           views.api_webhook,        name='api_webhook'),
    path('api/test-xml/',          views.api_test_xml,       name='api_test_xml'),
    path('api/test-send/',         views.api_test_send,      name='api_test_send'),
    path('api/test-docrobot/',     views.api_test_docrobot,  name='api_test_docrobot'),
    path('api/test-onec/',         views.api_test_onec,      name='api_test_onec'),
]
