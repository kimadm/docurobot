from django.contrib import admin
from .models import EdiDocument, SendQueue, ActivityLog, XmlTemplate, ConnectionSettings


@admin.register(XmlTemplate)
class XmlTemplateAdmin(admin.ModelAdmin):
    list_display  = ('doc_type', 'name', 'is_active', 'updated_at')
    list_filter   = ('is_active', 'doc_type')


@admin.register(EdiDocument)
class EdiDocumentAdmin(admin.ModelAdmin):
    list_display  = ('docrobot_id', 'doc_type', 'number', 'supplier_name', 'buyer_name', 'received_at')
    list_filter   = ('doc_type',)
    search_fields = ('docrobot_id', 'number', 'supplier_name', 'buyer_name')
    readonly_fields = ('received_at', 'raw_json', 'xml_content')


@admin.register(SendQueue)
class SendQueueAdmin(admin.ModelAdmin):
    list_display  = ('document', 'status', 'attempts', 'updated_at', 'sent_at')
    list_filter   = ('status',)
    readonly_fields = ('created_at', 'updated_at', 'sent_at', 'last_error', 'response')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display  = ('created_at', 'level', 'action', 'message')
    list_filter   = ('level', 'action')
    readonly_fields = ('created_at',)


@admin.register(ConnectionSettings)
class ConnectionSettingsAdmin(admin.ModelAdmin):
    list_display = ('docrobot_url', 'docrobot_username', 'docrobot_status', 'onec_url', 'onec_status', 'updated_at')
    readonly_fields = ('updated_at', 'docrobot_tested_at', 'onec_tested_at', 'docrobot_status', 'onec_status')

    def has_add_permission(self, request):
        # Только одна запись
        return not ConnectionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
