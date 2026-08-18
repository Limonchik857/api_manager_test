import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from executions.models import WorkflowExecution
from .engine.executor import WorkflowExecutor
from .forms import WorkflowForm, get_node_form_class
from .models import Workflow, WorkflowNode
from .services import (
    build_configuration,
    can_delete_node,
    get_user_node,
    get_user_workflow,
    reorder_nodes,
)


@login_required
def dashboard(request):
    workflows = request.user.workflows.annotate_execution_stats()
    recent_executions = WorkflowExecution.objects.filter(
        workflow__owner=request.user
    ).select_related('workflow')[:10]
    return render(request, 'dashboard.html', {
        'workflows': workflows,
        'recent_executions': recent_executions,
    })


@login_required
def workflow_list(request):
    workflows = request.user.workflows.annotate_execution_stats()
    context = [{
        'workflow': w,
        'execution_count': w.execution_count,
        'last_run': w.last_run,
    } for w in workflows]
    return render(request, 'workflows/list.html', {
        'workflows': context,
    })


@login_required
def workflow_create(request):
    if request.method == 'POST':
        form = WorkflowForm(request.POST)
        if form.is_valid():
            workflow = form.save(commit=False)
            workflow.owner = request.user
            workflow.save()
            WorkflowNode.objects.create(
                workflow=workflow,
                node_type=WorkflowNode.NodeType.WEBHOOK,
                name='Webhook',
                position=1,
                configuration={},
            )
            messages.success(request, 'Workflow created')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = WorkflowForm()
    return render(request, 'workflows/create.html', {'form': form})


@login_required
def workflow_detail(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    executions_qs = workflow.executions
    return render(request, 'workflows/detail.html', {
        'workflow': workflow,
        'nodes': workflow.nodes.all(),
        'node_type_labels': dict(WorkflowNode.NodeType.choices),
        'success_count': executions_qs.filter(
            status=WorkflowExecution.Status.SUCCESS
        ).count(),
        'failed_count': executions_qs.filter(
            status=WorkflowExecution.Status.FAILED
        ).count(),
    })


@login_required
def workflow_edit(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    if request.method == 'POST':
        form = WorkflowForm(request.POST, instance=workflow)
        if form.is_valid():
            form.save()
            messages.success(request, 'Workflow updated')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = WorkflowForm(instance=workflow)

    return render(request, 'workflows/edit.html', {
        'workflow': workflow,
        'form': form,
        'nodes': workflow.nodes.all(),
        'node_type_labels': dict(WorkflowNode.NodeType.choices),
    })


@require_POST
@login_required
def workflow_toggle(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.is_active = not workflow.is_active
    workflow.save(update_fields=['is_active', 'updated_at'])
    status = 'enabled' if workflow.is_active else 'disabled'
    messages.success(request, f'Workflow {status}')
    return redirect('workflow_detail', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_delete(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.delete()
    messages.success(request, 'Workflow deleted')
    return redirect('dashboard')


@login_required
def node_add(request, workflow_id, node_type):
    workflow = get_user_workflow(request.user, workflow_id)
    form_class = get_node_form_class(node_type)
    if form_class is None:
        return HttpResponseForbidden('Unknown node type')

    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            config_node_type, name, configuration = build_configuration(form)
            position = workflow.nodes.count() + 1
            WorkflowNode.objects.create(
                workflow=workflow,
                node_type=config_node_type,
                name=name or node_type.title(),
                position=position,
                configuration=configuration,
            )
            messages.success(request, 'Step added')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = form_class()

    return render(request, 'workflows/node_form.html', {
        'workflow': workflow,
        'node_type': node_type,
        'form': form,
    })


@login_required
def node_edit(request, workflow_id, node_id):
    workflow = get_user_workflow(request.user, workflow_id)
    node = get_object_or_404(WorkflowNode, pk=node_id, workflow=workflow)
    form_class = get_node_form_class(node.node_type)

    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            config_node_type, name, configuration = build_configuration(form)
            node.node_type = config_node_type
            node.name = name or node.node_type.title()
            node.configuration = configuration
            node.save()
            messages.success(request, 'Step updated')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        initial = {'node_type': node.node_type, 'name': node.name}
        cfg = node.configuration
        if node.node_type == 'http':
            initial.update({
                'method': cfg.get('method', 'POST'),
                'url': cfg.get('url', ''),
                'headers': json.dumps(cfg.get('headers') or {}, indent=2, ensure_ascii=False),
                'query_params': json.dumps(cfg.get('query_params') or {}, indent=2, ensure_ascii=False),
                'body': json.dumps(cfg.get('body') or {}, indent=2, ensure_ascii=False)
                        if isinstance(cfg.get('body'), (dict, list)) else cfg.get('body', ''),
            })
        elif node.node_type == 'telegram':
            initial.update({
                'bot_token': cfg.get('bot_token', ''),
                'chat_id': cfg.get('chat_id', ''),
                'message': cfg.get('message', ''),
            })
        elif node.node_type == 'condition':
            condition = (cfg.get('conditions') or [{}])[0]
            initial.update({
                'left': condition.get('left', ''),
                'operator': condition.get('operator', '='),
                'right': condition.get('right', ''),
            })
        form = form_class(initial=initial)

    return render(request, 'workflows/node_form.html', {
        'workflow': workflow,
        'node': node,
        'node_type': node.node_type,
        'form': form,
    })


@require_POST
@login_required
def node_delete(request, workflow_id, node_id):
    workflow = get_user_workflow(request.user, workflow_id)
    node = get_object_or_404(WorkflowNode, pk=node_id, workflow=workflow)
    if not can_delete_node(workflow, node):
        messages.error(request, 'At least one Webhook trigger is required')
    else:
        node.delete()
        reorder_nodes(workflow)
        messages.success(request, 'Step deleted')
    return redirect('workflow_edit', workflow_id=workflow.pk)


@require_POST
@login_required
def node_move(request, workflow_id, node_id, direction):
    workflow = get_user_workflow(request.user, workflow_id)
    node = get_object_or_404(WorkflowNode, pk=node_id, workflow=workflow)
    siblings = list(workflow.nodes.all())
    index = siblings.index(node)
    target = index - 1 if direction == 'up' else index + 1
    if 0 <= target < len(siblings):
        siblings[index], siblings[target] = siblings[target], siblings[index]
        for i, n in enumerate(siblings, start=1):
            n.position = i
            WorkflowNode.objects.bulk_update(siblings, ['position'])
    return redirect('workflow_edit', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_regenerate_webhook(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.regenerate_webhook_token()
    messages.success(request, 'Webhook URL regenerated')
    return redirect('workflow_detail', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_run_test(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    try:
        payload = json.loads(request.POST.get('payload') or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Payload must be a JSON object')
    except json.JSONDecodeError as exc:
        messages.error(request, f'Invalid JSON payload: {exc}')
        return redirect('workflow_detail', workflow_id=workflow.pk)

    execution = WorkflowExecutor().run(workflow.pk, payload)
    messages.success(request, f'Test execution #{execution.pk} finished: {execution.get_status_display()}')
    return redirect('execution_detail', execution_id=execution.pk)


@csrf_exempt
def webhook_receive(request, token):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    workflow = Workflow.objects.filter(webhook_token=token, is_active=True).first()
    if workflow is None:
        return JsonResponse({'error': 'Not found'}, status=404)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
        if not isinstance(payload, dict):
            payload = {'payload': payload}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    execution = WorkflowExecutor().run(workflow.pk, payload)
    status_code = 200 if execution.status == WorkflowExecution.Status.SUCCESS else 502
    return JsonResponse({
        'execution_id': execution.pk,
        'status': execution.status,
    }, status=status_code)