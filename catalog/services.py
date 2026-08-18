"""Phase 15 — Templates: создание копии Workflow из шаблона."""

from django.shortcuts import get_object_or_404

from usage.services import enforce_limits, enforce_node_limit
from workflows.models import Workflow, WorkflowNode

TEMPLATE_DEFINITIONS = [
    {
        'name': 'Мониторинг сайта',
        'category': 'monitoring',
        'description': (
            'Каждые 30 минут проверяет доступность сайта. '
            'Если сайт недоступен — уведомление в Telegram.'
        ),
        'definition': {
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'http',
                    'name': 'HTTP Request',
                    'configuration': {
                        'method': 'GET',
                        'url': 'https://example.com/',
                        'headers': {},
                        'query_params': {},
                        'body': '',
                        'retry': {'max_attempts': 3, 'backoff_base': 10},
                        'on_error': 'retry',
                    },
                },
                {
                    'type': 'condition',
                    'name': 'Сайт недоступен',
                    'configuration': {
                        'logic': 'AND',
                        'conditions': [
                            {'left': '{{ http.status_code }}', 'operator': '>=', 'right': '500'}
                        ],
                    },
                },
                {
                    'type': 'telegram',
                    'name': 'Уведомление',
                    'configuration': {
                        'chat_id': '',
                        'message': '⚠ Сайт недоступен: HTTP {{ http.status_code }}',
                    },
                },
            ],
        },
    },
    {
        'name': 'Мониторинг цены',
        'category': 'monitoring',
        'description': (
            'Проверяет цену по API каждые 6 часов. '
            'Если цена упала ниже порога — уведомление в Telegram.'
        ),
        'definition': {
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'http',
                    'name': 'HTTP Request',
                    'configuration': {
                        'method': 'GET',
                        'url': 'https://api.example.com/price',
                        'headers': {},
                        'query_params': {},
                        'body': '',
                        'retry': {'max_attempts': 2, 'backoff_base': 10},
                        'on_error': 'retry',
                    },
                },
                {
                    'type': 'transform',
                    'name': 'Цена',
                    'configuration': {
                        'mapping': {'price': '{{ price }}', 'name': '{{ name }}'}
                    },
                },
                {
                    'type': 'condition',
                    'name': 'Цена упала',
                    'configuration': {
                        'logic': 'AND',
                        'conditions': [
                            {'left': '{{ price }}', 'operator': '<', 'right': '1000'}
                        ],
                    },
                },
                {
                    'type': 'telegram',
                    'name': 'Уведомление',
                    'configuration': {
                        'chat_id': '',
                        'message': '🔥 Цена упала: {{ name }} — {{ price }} ₽',
                    },
                },
            ],
        },
    },
    {
        'name': 'Webhook → Telegram',
        'category': 'basic',
        'description': 'Любой POST-запрос на webhook URL пересылается в Telegram.',
        'definition': {
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'telegram',
                    'name': 'Уведомление',
                    'configuration': {
                        'chat_id': '',
                        'message': 'Новый запрос:\n{{ trigger | tojson }}',
                    },
                },
            ],
        },
    },
    {
        'name': 'Health Check API',
        'category': 'monitoring',
        'description': (
            'Каждые 5 минут пингует /health API. '
            'При статусе не 200 — уведомление в Telegram.'
        ),
        'definition': {
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'http',
                    'name': 'Health check',
                    'configuration': {
                        'method': 'GET',
                        'url': 'https://api.example.com/health',
                        'headers': {},
                        'query_params': {},
                        'body': '',
                        'retry': {'max_attempts': 3, 'backoff_base': 5},
                        'on_error': 'retry',
                    },
                },
                {
                    'type': 'condition',
                    'name': 'API нездоров',
                    'configuration': {
                        'logic': 'AND',
                        'conditions': [
                            {'left': '{{ http.status_code }}', 'operator': '!=', 'right': '200'}
                        ],
                    },
                },
                {
                    'type': 'telegram',
                    'name': 'Уведомление',
                    'configuration': {
                        'chat_id': '',
                        'message': '🩺 API Health Check: HTTP {{ http.status_code }}',
                    },
                },
            ],
        },
    },
    {
        'name': 'Ежедневный отчёт API',
        'category': 'reporting',
        'description': 'Каждый день в 09:00 забирает данные из API и отправляет отчёт в Telegram.',
        'definition': {
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'http',
                    'name': 'HTTP Request',
                    'configuration': {
                        'method': 'GET',
                        'url': 'https://api.example.com/report',
                        'headers': {},
                        'query_params': {},
                        'body': '',
                        'retry': {'max_attempts': 2, 'backoff_base': 10},
                        'on_error': 'retry',
                    },
                },
                {
                    'type': 'transform',
                    'name': 'Отчёт',
                    'configuration': {
                        'mapping': {
                            'orders': '{{ orders }}',
                            'revenue': '{{ revenue }}',
                            'date': '{{ date }}',
                        }
                    },
                },
                {
                    'type': 'telegram',
                    'name': 'Отчёт в Telegram',
                    'configuration': {
                        'chat_id': '',
                        'message': (
                            '📊 Отчёт {{ date }}:\n'
                            'Заказы: {{ orders }}\nВыручка: {{ revenue }} ₽'
                        ),
                    },
                },
            ],
        },
    },
]


def seed_templates():
    for item in TEMPLATE_DEFINITIONS:
        WorkflowTemplate.objects.update_or_create(
            name=item['name'],
            defaults={
                'description': item['description'],
                'category': item['category'],
                'definition': item['definition'],
            },
        )


def create_workflow_from_template(owner, template, name=None):
    enforce_limits(owner)
    workflow = Workflow.objects.create(
        owner=owner,
        name=name or f'{template.name} (копия)',
        description=template.description,
    )
    definition = template.definition.get('nodes', [])
    for i, item in enumerate(definition, start=1):
        enforce_node_limit(owner, workflow)
        configuration = dict(item.get('configuration') or {})
        if item.get('type') == 'telegram':
            configuration.pop('secret_id', None)
            configuration.pop('bot_token', None)
            configuration.pop('connection_id', None)
        WorkflowNode.objects.create(
            workflow=workflow,
            node_type=item.get('type'),
            name=item.get('name') or item.get('type'),
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