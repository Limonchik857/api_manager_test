import json

from django.shortcuts import get_object_or_404

from .models import Workflow, WorkflowNode


def get_user_workflow(user, workflow_id):
    return get_object_or_404(Workflow, pk=workflow_id, owner=user)


def get_user_node(user, node_id):
    return get_object_or_404(
        WorkflowNode,
        pk=node_id,
        workflow__owner=user,
    )


def build_configuration(form):
    data = form.cleaned_data
    node_type = data.pop('node_type')
    name = data.pop('name')
    config = {}

    if node_type == 'http':
        config = {
            'method': data['method'],
            'url': data['url'],
            'headers': _parse_json_or_empty(data.get('headers') or '{}'),
            'query_params': _parse_json_or_empty(data.get('query_params') or '{}'),
            'body': _parse_body(data.get('body')),
        }
    elif node_type == 'telegram':
        config = {
            'bot_token': data['bot_token'].strip(),
            'chat_id': data['chat_id'].strip(),
            'message': data['message'],
        }
    elif node_type == 'condition':
        config = {
            'conditions': [{
                'left': data['left'],
                'operator': data['operator'],
                'right': data.get('right') or '',
            }]
        }
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
    raise ValueError(f'Invalid JSON: {raw[:120]}')


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
    for index, node in enumerate(workflow.nodes.all(), start=1):
        if node.position != index:
            node.position = index
            node.save(update_fields=['position'])