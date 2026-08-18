import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from executions.models import WorkflowExecution
from usage.services import (
    enforce_limits,
    enforce_node_limit,
    get_usage_summary,
    LimitExceeded,
)
from .engine.scheduler import compute_next_run
from .forms import (
    TelegramNodeForm,
    WorkflowForm,
    WorkflowScheduleForm,
    get_node_form_class,
)
from .models import Workflow, WorkflowNode, WorkflowSchedule, WorkflowVersion
from .services import (
    build_configuration,
    can_delete_node,
    dispatch_execution,
    export_workflow,
    get_user_workflow,
    import_workflow,
    reorder_nodes,
    restore_workflow_version,
    save_workflow_version,
)

ACTIVE_STATUSES = (
    WorkflowExecution.Status.QUEUED,
    WorkflowExecution.Status.RUNNING,
    WorkflowExecution.Status.RETRYING,
)


@login_required
def dashboard(request):
    """Phase 6 — Monitoring: здоровье автоматизаций + usage (Phase 13)."""
    workflows = list(request.user.workflows.annotate_execution_stats())
    schedule_map = {
        s.workflow_id: s
        for s in WorkflowSchedule.objects.filter(workflow__owner=request.user)
    }

    cards = []
    counts = {'healthy': 0, 'warning': 0, 'failed': 0}
    for wf in workflows:
        recent = list(
            wf.executions.exclude(status__in=ACTIVE_STATUSES)
            .order_by('-started_at')[:20]
        )
        consecutive = 0
        for execution in recent:
            if execution.status == WorkflowExecution.Status.FAILED:
                consecutive += 1
            else:
                break
        last = recent[0] if recent else None
        successes = sum(
            1 for execution in recent
            if execution.status == WorkflowExecution.Status.SUCCESS
        )
        success_rate = round(successes / len(recent) * 100) if recent else None

        if consecutive >= max(1, wf.notify_after_consecutive):
            health = 'failed'
        elif last and last.status == WorkflowExecution.Status.FAILED:
            health = 'warning'
        elif success_rate is not None and success_rate < 90:
            health = 'warning'
        else:
            health = 'healthy'
        counts[health] += 1

        schedule = schedule_map.get(wf.pk)
        cards.append({
            'workflow': wf,
            'execution_count': wf.execution_count,
            'last_run': wf.last_run,
            'last_execution': last,
            'consecutive_failures': consecutive,
            'success_rate': success_rate,
            'health': health,
            'schedule': schedule,
            'next_run_at': schedule.next_run_at if schedule and schedule.is_active else None,
        })

    usage = get_usage_summary(request.user)
    recent_executions = WorkflowExecution.objects.filter(
        workflow__owner=request.user
    ).select_related('workflow')[:10]
    return render(request, 'dashboard.html', {
        'cards': cards,
        'counts': counts,
        'usage': usage,
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
        'usage': get_usage_summary(request.user),
    })


@login_required
def workflow_create(request):
    try:
        enforce_limits(request.user)
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('workflows')

    if request.method == 'POST':
        form = WorkflowForm(request.POST, user=request.user)
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
            save_workflow_version(workflow)
            messages.success(request, 'Сценарий создан')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = WorkflowForm(user=request.user)
    return render(request, 'workflows/create.html', {'form': form})


@login_required
def workflow_detail(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    executions_qs = workflow.executions
    schedule = getattr(workflow, 'schedule', None)
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
        'schedule': schedule,
    })


@login_required
def workflow_edit(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    if request.method == 'POST':
        form = WorkflowForm(request.POST, instance=workflow, user=request.user)
        if form.is_valid():
            form.save()
            save_workflow_version(workflow)
            messages.success(request, 'Сценарий обновлён')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = WorkflowForm(instance=workflow, user=request.user)

    schedule, _ = WorkflowSchedule.objects.get_or_create(workflow=workflow)
    schedule_form = WorkflowScheduleForm(instance=schedule)
    return render(request, 'workflows/edit.html', {
        'workflow': workflow,
        'form': form,
        'schedule_form': schedule_form,
        'schedule': schedule,
        'nodes': workflow.nodes.all(),
        'node_type_labels': dict(WorkflowNode.NodeType.choices),
        'versions': workflow.versions.all()[:10],
    })


@login_required
def workflow_schedule_update(request, workflow_id):
    """Phase 1 — Scheduler UI: сохранить расписание и пересчитать next_run_at."""
    workflow = get_user_workflow(request.user, workflow_id)
    schedule, _ = WorkflowSchedule.objects.get_or_create(workflow=workflow)
    if request.method == 'POST':
        form = WorkflowScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.is_active = form.cleaned_data['is_active']
            if schedule.is_active:
                schedule.next_run_at = compute_next_run(schedule)
            else:
                schedule.next_run_at = None
            schedule.save()
            messages.success(
                request,
                'Расписание сохранено' if schedule.is_active else 'Расписание отключено',
            )
        else:
            for error in form.errors.values():
                messages.error(request, '; '.join(error))
        return redirect('workflow_edit', workflow_id=workflow.pk)
    return redirect('workflow_edit', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_toggle(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.is_active = not workflow.is_active
    workflow.save(update_fields=['is_active', 'updated_at'])
    status_word = 'включён' if workflow.is_active else 'отключён'
    messages.success(request, f'Сценарий {status_word}')
    return redirect('workflow_detail', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_delete(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.delete()
    messages.success(request, 'Сценарий удалён')
    return redirect('dashboard')


@login_required
def node_add(request, workflow_id, node_type):
    workflow = get_user_workflow(request.user, workflow_id)
    form_class = get_node_form_class(node_type)
    if form_class is None:
        return HttpResponseForbidden('Неизвестный тип узла')

    try:
        enforce_node_limit(request.user, workflow)
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('workflow_edit', workflow_id=workflow.pk)

    if request.method == 'POST':
        form = form_class(request.POST, user=request.user) if form_class is TelegramNodeForm \
            else form_class(request.POST)
        if form.is_valid():
            config_node_type, name, configuration = build_configuration(form, request.user)
            position = workflow.nodes.count() + 1
            WorkflowNode.objects.create(
                workflow=workflow,
                node_type=config_node_type,
                name=name or node_type.title(),
                position=position,
                configuration=configuration,
            )
            save_workflow_version(workflow)
            messages.success(request, 'Шаг добавлен')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        form = form_class(user=request.user) if form_class is TelegramNodeForm \
            else form_class()

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
        form = form_class(request.POST, user=request.user) if form_class is TelegramNodeForm \
            else form_class(request.POST)
        if form.is_valid():
            config_node_type, name, configuration = build_configuration(form, request.user)
            node.node_type = config_node_type
            node.name = name or node.node_type.title()
            node.configuration = configuration
            node.save()
            save_workflow_version(workflow)
            messages.success(request, 'Шаг обновлён')
            return redirect('workflow_edit', workflow_id=workflow.pk)
    else:
        initial = {
            'node_type': node.node_type,
            'name': node.name,
            'on_error': node.configuration.get('on_error') or workflow.default_on_error,
        }
        cfg = node.configuration
        if node.node_type == 'http':
            retry = cfg.get('retry') or {}
            initial.update({
                'method': cfg.get('method', 'POST'),
                'url': cfg.get('url', ''),
                'headers': json.dumps(cfg.get('headers') or {}, indent=2, ensure_ascii=False),
                'query_params': json.dumps(cfg.get('query_params') or {}, indent=2, ensure_ascii=False),
                'body': json.dumps(cfg.get('body') or {}, indent=2, ensure_ascii=False)
                        if isinstance(cfg.get('body'), (dict, list)) else cfg.get('body', ''),
                'max_attempts': retry.get('max_attempts', 1),
                'backoff_base': retry.get('backoff_base', 5),
            })
        elif node.node_type == 'telegram':
            initial.update({
                'connection_id': cfg.get('connection_id', ''),
                'secret_id': cfg.get('secret_id', ''),
                'chat_id': cfg.get('chat_id', ''),
                'message': cfg.get('message', ''),
            })
        elif node.node_type == 'condition':
            conditions = cfg.get('conditions') or [{}]
            initial.update({
                'logic': cfg.get('logic', 'AND'),
                'left': (conditions[0] or {}).get('left', ''),
                'operator': (conditions[0] or {}).get('operator', '='),
                'right': (conditions[0] or {}).get('right', ''),
            })
            if len(conditions) > 1:
                initial.update({
                    'left2': conditions[1].get('left', ''),
                    'operator2': conditions[1].get('operator', '='),
                    'right2': conditions[1].get('right', ''),
                })
        elif node.node_type == 'transform':
            initial.update({
                'mapping': json.dumps(cfg.get('mapping') or {}, indent=2, ensure_ascii=False),
            })
        form = form_class(initial=initial, user=request.user) if form_class is TelegramNodeForm \
            else form_class(initial=initial)

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
        messages.error(request, 'Нужен как минимум один Webhook-триггер')
    else:
        node.delete()
        reorder_nodes(workflow)
        save_workflow_version(workflow)
        messages.success(request, 'Шаг удалён')
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
        save_workflow_version(workflow)
    return redirect('workflow_edit', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_regenerate_webhook(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    workflow.regenerate_webhook_token()
    messages.success(request, 'Webhook URL обновлён')
    return redirect('workflow_detail', workflow_id=workflow.pk)


@require_POST
@login_required
def workflow_run_test(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    try:
        payload = json.loads(request.POST.get('payload') or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Payload должен быть JSON-объектом')
    except json.JSONDecodeError as exc:
        messages.error(request, f'Неверный JSON payload: {exc}')
        return redirect('workflow_detail', workflow_id=workflow.pk)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('workflow_detail', workflow_id=workflow.pk)

    try:
        execution = dispatch_execution(workflow, payload, trigger='test')
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('workflow_detail', workflow_id=workflow.pk)

    execution.refresh_from_db()
    messages.success(
        request,
        f'Тестовый запуск #{execution.pk}: {execution.get_status_display()}',
    )
    return redirect('execution_detail', execution_id=execution.pk)


# ── Versioning (Phase 16) ───────────────────────────────────

@login_required
def workflow_versions(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    return render(request, 'workflows/versions.html', {
        'workflow': workflow,
        'versions': workflow.versions.all(),
    })


@require_POST
@login_required
def workflow_version_restore(request, workflow_id, version_number):
    workflow = get_user_workflow(request.user, workflow_id)
    try:
        version = workflow.versions.get(version=version_number)
    except WorkflowVersion.DoesNotExist:
        messages.error(request, 'Версия не найдена')
        return redirect('workflow_versions', workflow_id=workflow.pk)
    restore_workflow_version(workflow, version_number)
    messages.success(
        request,
        f'Версия v{version_number} восстановлена как v{workflow.versions.latest("version").version}',
    )
    return redirect('workflow_edit', workflow_id=workflow.pk)


# ── Import / Export (Phase 17) ──────────────────────────────

@login_required
def workflow_export(request, workflow_id):
    workflow = get_user_workflow(request.user, workflow_id)
    data = export_workflow(workflow)
    filename = f'{workflow.name.lower().replace(" ", "-")}.workflow.json'
    response = HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@require_POST
@login_required
def workflow_import(request):
    uploaded = request.FILES.get('file')
    if uploaded is None:
        messages.error(request, 'Выберите файл для импорта')
        return redirect('workflows')
    try:
        data = json.loads(uploaded.read().decode('utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('nodes'), list):
            raise ValueError('Неверный формат: ожидается объект с полем nodes')
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        messages.error(request, f'Не удалось прочитать файл: {exc}')
        return redirect('workflows')

    try:
        workflow = import_workflow(request.user, data)
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('workflows')
    messages.success(request, f'Сценарий «{workflow.name}» импортирован')
    return redirect('workflow_edit', workflow_id=workflow.pk)


# ── Webhook (async) ─────────────────────────────────────────

@csrf_exempt
def webhook_receive(request, token):
    from django.conf import settings
    from django.core.cache import cache

    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешён'}, status=405)

    workflow = Workflow.objects.filter(webhook_token=token, is_active=True).first()
    if workflow is None:
        return JsonResponse({'error': 'Не найдено'}, status=404)

    # Лимит размера payload (DoS-защита).
    content_length = request.headers.get('Content-Length')
    if content_length and int(content_length) > settings.MAX_WEBHOOK_PAYLOAD:
        return JsonResponse(
            {'error': 'Payload слишком большой'}, status=413
        )
    body = request.body
    if len(body) > settings.MAX_WEBHOOK_PAYLOAD:
        return JsonResponse(
            {'error': 'Payload слишком большой'}, status=413
        )

    # Rate limit: N запросов в минуту на workflow.
    limit = settings.WEBHOOK_RATE_LIMIT_PER_MINUTE
    window_key = 'webhook_rl_{}_'.format(workflow.pk)
    minute_key = int(timezone.now().timestamp() // 60)
    counter_key = f'{window_key}{minute_key}'
    count = cache.get(counter_key, 0)
    if count >= limit:
        return JsonResponse(
            {'error': 'Слишком много запросов, попробуйте позже'}, status=429
        )
    cache.set(counter_key, count + 1, 70)

    try:
        payload = json.loads(body.decode('utf-8') or '{}')
        if not isinstance(payload, dict):
            payload = {'payload': payload}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Неверный JSON body'}, status=400)

    try:
        execution = dispatch_execution(workflow, payload, trigger='webhook')
    except LimitExceeded as exc:
        return JsonResponse({'error': str(exc)}, status=429)

    execution.refresh_from_db()
    return JsonResponse({
        'execution_id': execution.pk,
        'status': execution.status,
    })