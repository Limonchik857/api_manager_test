from django.contrib import admin
from django.utils.html import format_html

from .models import Workflow, WorkflowNode


class WorkflowNodeInline(admin.TabularInline):
    model = WorkflowNode
    extra = 0


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'is_active', 'webhook_token_short', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'owner__username')
    inlines = [WorkflowNodeInline]
    readonly_fields = ('webhook_token', 'created_at', 'updated_at')

    @admin.display(description='Webhook token')
    def webhook_token_short(self, obj):
        return format_html('<code>{}</code>', obj.webhook_token[:16] + '...')


@admin.register(WorkflowNode)
class WorkflowNodeAdmin(admin.ModelAdmin):
    list_display = ('workflow', 'node_type', 'name', 'position')
    list_filter = ('node_type',)
    search_fields = ('workflow__name', 'name')