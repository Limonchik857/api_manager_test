from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from usage.services import LimitExceeded
from workflows.services import dispatch_execution
from .models import NodeExecution, WorkflowExecution


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


@require_POST
@login_required
def execution_replay(request, execution_id):
    """Phase 12 — Replay: запускает Workflow заново с исходным input."""
    execution = get_object_or_404(
        WorkflowExecution,
        pk=execution_id,
        workflow__owner=request.user,
    )
    try:
        new_execution = dispatch_execution(
            execution.workflow, execution.input_data, trigger='replay'
        )
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('execution_detail', execution_id=execution.pk)
    new_execution.refresh_from_db()
    messages.success(
        request,
        f'Replay запущен: #{new_execution.pk} ({new_execution.get_status_display()})',
    )
    return redirect('execution_detail', execution_id=new_execution.pk)


@require_POST
@login_required
def execution_retry_from_node(request, execution_id, node_execution_id):
    """Phase 12 — Retry from failed node: новый запуск с контекста упавшего узла."""
    execution = get_object_or_404(
        WorkflowExecution,
        pk=execution_id,
        workflow__owner=request.user,
    )
    node_execution = get_object_or_404(
        NodeExecution,
        pk=node_execution_id,
        execution=execution,
    )
    if node_execution.status != NodeExecution.Status.FAILED:
        messages.error(request, 'Повтор доступен только для упавшего шага')
        return redirect('execution_detail', execution_id=execution.pk)
    try:
        new_execution = dispatch_execution(
            execution.workflow,
            execution.input_data,
            trigger='replay',
            resume_node_execution=node_execution.pk,
        )
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('execution_detail', execution_id=execution.pk)
    new_execution.refresh_from_db()
    messages.success(
        request,
        f'Запуск #{new_execution.pk} с шага «{node_execution.node_name}»: '
        f'{new_execution.get_status_display()}',
    )
    return redirect('execution_detail', execution_id=new_execution.pk)