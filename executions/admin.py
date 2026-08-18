from django.contrib import admin

from .models import WorkflowExecution, NodeExecution


class NodeExecutionInline(admin.TabularInline):
    model = NodeExecution
    extra = 0
    readonly_fields = ('node', 'status', 'duration', 'error')


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'workflow', 'status', 'duration', 'started_at')
    list_filter = ('status', 'workflow__owner')
    search_fields = ('workflow__name', 'workflow__owner__username')
    readonly_fields = ('input_data', 'output_data', 'error')
    inlines = [NodeExecutionInline]


@admin.register(NodeExecution)
class NodeExecutionAdmin(admin.ModelAdmin):
    list_display = ('node_name', 'execution', 'status', 'duration', 'started_at')
    list_filter = ('status',)