from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import WorkflowExecution


@login_required
def execution_list(request):
    executions = WorkflowExecution.objects.filter(
        workflow__owner=request.user
    ).select_related('workflow')
    return render(request, 'executions/list.html', {'executions': executions})


@login_required
def execution_detail(request, execution_id):
    execution = get_object_or_404(
        WorkflowExecution,
        pk=execution_id,
        workflow__owner=request.user,
    )
    node_executions = execution.node_executions.select_related('node').all()
    return render(request, 'executions/detail.html', {
        'execution': execution,
        'node_executions': node_executions,
    })