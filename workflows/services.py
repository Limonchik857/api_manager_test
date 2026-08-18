import json

from django.shortcuts import get_object_or_404

from vault.services import SecretService
from .models import Workflow, WorkflowNode


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
    elif node_type == 'telegram':
        secret_id = data.pop('secret_id', None)
        new_token = (data.pop('new_token') or '').strip()
        config = {
            'chat_id': data['chat_id'].strip(),
            'message': data['message'],
        }
        if secret_id:
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