import json
import logging
import socket
from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import get_object_or_404

from executions.models import WorkflowExecution
from executions.services import truncate_data
from usage.services import enforce_execution_limit, LimitExceeded
from vault.services import SecretService
from .models import Workflow, WorkflowNode

logger = logging.getLogger(__name__)


def broker_available(timeout=1.0):
    """Быстрая проверка доступности Celery broker (Redis) без зависания.

    kombu при недоступном брокере ретраит подключение бесконечно,
    поэтому перед apply_async нужен socket-пробинг.
    """
    try:
        parsed = urlparse(settings.CELERY_BROKER_URL)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def get_user_workflow(user, workflow_id):
    return get_object_or_404(Workflow, pk=workflow_id, owner=user)


def get_user_node(user, node_id):
    return get_object_or_404(
        WorkflowNode,
        pk=node_id,
        workflow__owner=user,
    )


def build_configuration(form, user=None):
    data = form.cleaned_data
    node_type = data.pop('node_type')
    name = data.pop('name')
    config = {}

    if node_type == 'http':
        retry = {}
        max_attempts = data.pop('max_attempts', 1)
        backoff_base = data.pop('backoff_base', 5)
        if max_attempts and max_attempts > 1:
            retry = {'max_attempts': max_attempts, 'backoff_base': backoff_base}
        config = {
            'method': data['method'],
            'url': data['url'],
            'headers': _parse_json_or_empty(data.get('headers') or '{}'),
            'query_params': _parse_json_or_empty(data.get('query_params') or '{}'),
            'body': _parse_body(data.get('body')),
            'retry': retry,
        }
        if data.get('on_error'):
            config['on_error'] = data['on_error']
    elif node_type == 'telegram':
        connection_id = data.pop('connection_id', None)
        secret_id = data.pop('secret_id', None)
        new_token = (data.pop('new_token') or '').strip()
        config = {
            'chat_id': data['chat_id'].strip(),
            'message': data['message'],
        }
        if connection_id:
            config['connection_id'] = int(connection_id)
        elif secret_id:
            config['secret_id'] = int(secret_id)
        elif new_token and user is not None:
            secret = SecretService.set_secret(user, 'telegram-bot-token', new_token)
            config['secret_id'] = secret.pk
    elif node_type == 'condition':
        conditions = [{
            'left': data['left'],
            'operator': data['operator'],
            'right': data.get('right') or '',
        }]
        if data.get('left2'):
            conditions.append({
                'left': data['left2'],
                'operator': data.get('operator2') or '=',
                'right': data.get('right2') or '',
            })
        config = {
            'conditions': conditions,
            'logic': data.get('logic') or 'AND',
        }
    elif node_type == 'transform':
        mapping = _parse_json_or_empty(data.get('mapping') or '{}')
        config = {'mapping': mapping}
    elif node_type == 'webhook':
        config = {}

    return node_type, name, config


def _parse_json_or_empty(raw):
    raw = raw.strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    raise ValueError(f'Неверный JSON: {raw[:120]}')


def _parse_body(raw):
    raw = (raw or '').strip()
    if not raw:
        return {}
    if raw.startswith('{') or raw.startswith('['):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def can_delete_node(workflow, node):
    return workflow.nodes.filter(node_type='webhook').exclude(pk=node.pk).exists()


def reorder_nodes(workflow):
    nodes = list(workflow.nodes.all())
    for i, node in enumerate(nodes, start=1):
        node.position = i
    WorkflowNode.objects.bulk_update(nodes, ['position'])


# ── Async execution (Phase 3) ───────────────────────────────

def dispatch_execution(workflow, input_data, trigger='webhook',
                       resume_node_execution=None):
    """Создаёт WorkflowExecution (QUEUED) и отправляет в очередь Celery.

    Если брокер недоступен — выполняет inline (sync fallback).
    """
    enforce_execution_limit(workflow.owner)
    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        input_data=truncate_data(
            input_data if isinstance(input_data, dict) else {},
            settings.MAX_EXECUTION_INPUT, 'Входные данные',
        )[0],
        trigger=trigger,
        status=WorkflowExecution.Status.QUEUED,
    )
    kwargs = {
        'workflow_id': workflow.pk,
        'input_data': input_data if isinstance(input_data, dict) else {},
        'trigger': trigger,
        'execution_id': execution.pk,
    }
    if resume_node_execution is not None:
        kwargs['resume_node_execution'] = resume_node_execution

    if settings.EXECUTION_MODE == 'sync' or not broker_available():
        from .tasks import run_workflow_task
        run_workflow_task(**kwargs)
        return execution

    from .tasks import run_workflow_task
    try:
        run_workflow_task.apply_async(kwargs=kwargs)
    except Exception as exc:
        logger.warning('Broker unavailable (%s), running synchronously', exc)
        run_workflow_task(**kwargs)
    return execution


# ── Versioning (Phase 16) ───────────────────────────────────

def snapshot_workflow(workflow):
    return {
        'name': workflow.name,
        'description': workflow.description,
        'nodes': [
            {
                'node_type': n.node_type,
                'name': n.name,
                'position': n.position,
                'configuration': n.configuration,
            }
            for n in workflow.nodes.order_by('position')
        ],
    }


def save_workflow_version(workflow):
    from .models import WorkflowVersion
    snapshot = snapshot_workflow(workflow)
    latest = workflow.versions.order_by('-version').first()
    if latest is not None:
        if (latest.nodes_snapshot == snapshot['nodes']
                and latest.name_snapshot == workflow.name):
            return latest
        version = latest.version + 1
    else:
        version = 1
    new_version = WorkflowVersion.objects.create(
        workflow=workflow,
        version=version,
        name_snapshot=workflow.name,
        description_snapshot=workflow.description,
        nodes_snapshot=snapshot['nodes'],
        is_current=True,
    )
    WorkflowVersion.objects.filter(
        workflow=workflow
    ).exclude(pk=new_version.pk).update(is_current=False)
    return new_version


def restore_workflow_version(workflow, version_number):
    from .models import WorkflowVersion
    version = workflow.versions.get(version=version_number)
    workflow.name = version.name_snapshot
    workflow.description = version.description_snapshot
    workflow.save(update_fields=['name', 'description', 'updated_at'])
    workflow.nodes.all().delete()
    for item in version.nodes_snapshot:
        WorkflowNode.objects.create(
            workflow=workflow,
            node_type=item['node_type'],
            name=item['name'],
            position=item['position'],
            configuration=item.get('configuration') or {},
        )
    reorder_nodes(workflow)
    return save_workflow_version(workflow)


# ── Import / Export (Phase 17) ──────────────────────────────

def _telegram_connection_reference(config, workflow):
    from connections.models import Connection
    reference = {'connection_type': 'telegram'}
    connection_id = config.get('connection_id')
    if connection_id:
        connection = Connection.objects.filter(
            pk=connection_id, owner=workflow.owner
        ).first()
        if connection:
            reference['connection_name'] = connection.name
    return reference


def export_workflow(workflow):
    """Экспорт без секретов: credentials заменяются на reference подключения."""
    nodes = []
    for node in workflow.nodes.order_by('position'):
        configuration = dict(node.configuration)
        if node.node_type == 'telegram':
            configuration = {
                'connection': _telegram_connection_reference(
                    configuration, workflow
                ),
                'chat_id': configuration.get('chat_id', ''),
                'message': configuration.get('message', ''),
            }
        nodes.append({
            'type': node.node_type,
            'name': node.name,
            'configuration': configuration,
        })
    return {
        'name': workflow.name,
        'description': workflow.description,
        'nodes': nodes,
    }


def import_workflow(owner, data):
    """Импорт создаёт новый Workflow (не перезаписывает существующий)."""
    from connections.services import matches_connection
    from usage.services import enforce_limits, enforce_node_limit
    enforce_limits(owner)

    name = (data.get('name') or 'Импортированный сценарий').strip()
    workflow = Workflow.objects.create(
        owner=owner,
        name=f'{name} (импорт)',
        description=data.get('description') or '',
    )
    for i, item in enumerate(data.get('nodes', []), start=1):
        enforce_node_limit(owner, workflow)
        node_type = item.get('type')
        configuration = dict(item.get('configuration') or {})
        if node_type == 'telegram':
            configuration.pop('secret_id', None)
            configuration.pop('bot_token', None)
            reference = configuration.pop('connection', None) or {}
            connection = None
            if reference.get('connection_name'):
                connection = matches_connection(
                    owner,
                    reference.get('connection_type') or 'telegram',
                    reference['connection_name'],
                )
            if connection is not None:
                configuration['connection_id'] = connection.pk
        WorkflowNode.objects.create(
            workflow=workflow,
            node_type=node_type,
            name=item.get('name') or node_type,
            position=i,
            configuration=configuration,
        )
    if not workflow.nodes.filter(node_type='webhook').exists():
        WorkflowNode.objects.create(
            workflow=workflow,
            node_type='webhook',
            name='Webhook',
            position=workflow.nodes.count() + 1,
            configuration={},
        )
    return workflow