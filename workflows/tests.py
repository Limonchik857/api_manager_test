import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from executions.models import NodeExecution, WorkflowExecution
from workflows.engine.executor import WorkflowExecutor
from workflows.models import Workflow, WorkflowNode


def make_workflow(owner, name='Test Workflow'):
    wf = Workflow.objects.create(owner=owner, name=name)
    WorkflowNode.objects.create(
        workflow=wf, node_type=WorkflowNode.NodeType.WEBHOOK,
        name='Webhook', position=1, configuration={},
    )
    return wf


def add_node(wf, node_type, name, config):
    return WorkflowNode.objects.create(
        workflow=wf, node_type=node_type, name=name,
        position=wf.nodes.count() + 1, configuration=config,
    )


class ExecutorTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('alex', password='secret123')

    def test_webhook_condition_telegram_success(self):
        wf = make_workflow(self.user, 'Large Order Alert')
        add_node(wf, WorkflowNode.NodeType.CONDITION, 'Condition', {
            'conditions': [{'left': '{{ amount }}', 'operator': '>', 'right': '3000'}],
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-100123',
            'message': 'Order {{ order_id }} from {{ customer }}: {{ amount }}',
        })
        payload = {'order_id': 1537, 'customer': 'Alex', 'amount': 5000}

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value.status_code = 200
            mocked.return_value.json.return_value = {'ok': True, 'result': {'message_id': 42}}
            execution = WorkflowExecutor().run(wf.pk, payload)

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        node_execs = list(execution.node_executions.all())
        self.assertEqual(len(node_execs), 3)
        self.assertTrue(all(n.status == NodeExecution.Status.SUCCESS for n in node_execs))
        sent = mocked.call_args.kwargs['json']
        self.assertEqual(sent['chat_id'], '-100123')
        self.assertEqual(sent['text'], 'Order 1537 from Alex: 5000')

    def test_condition_false_skips_remaining(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.CONDITION, 'Condition', {
            'conditions': [{'left': '{{ amount }}', 'operator': '>', 'right': '3000'}],
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'hi',
        })

        execution = WorkflowExecutor().run(wf.pk, {'amount': 100})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        statuses = list(execution.node_executions.values_list('status', flat=True))
        self.assertEqual(statuses, ['success', 'success', 'skipped'])

    def test_telegram_error_fails_execution(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'hi',
        })

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value.status_code = 401
            mocked.return_value.json.return_value = {'ok': False, 'description': 'Unauthorized'}
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('401', execution.error)
        node = execution.node_executions.get(node__node_type='telegram')
        self.assertEqual(node.status, NodeExecution.Status.FAILED)
        self.assertIn('Unauthorized', node.error)

    def test_http_node_renders_variables(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'POST', 'url': 'https://httpbin.org/post',
            'headers': {}, 'query_params': {},
            'body': {'customer': '{{ customer }}', 'amount': '{{ amount }}'},
        })

        with mock.patch('workflows.engine.nodes.http.requests.request') as mocked:
            mocked.return_value.status_code = 200
            mocked.return_value.text = '{"ok": true}'
            mocked.return_value.json.return_value = {'ok': True}
            mocked.return_value.headers = {}
            execution = WorkflowExecutor().run(wf.pk, {'customer': 'Alex', 'amount': 5000})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        self.assertEqual(mocked.call_args[0], ('POST', 'https://httpbin.org/post'))
        self.assertEqual(mocked.call_args.kwargs['json'], {'customer': 'Alex', 'amount': '5000'})

    def test_http_http_error_fails(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'https://example.com/x',
            'headers': {}, 'query_params': {}, 'body': '',
        })

        with mock.patch('workflows.engine.nodes.http.requests.request') as mocked:
            mocked.return_value.status_code = 500
            mocked.return_value.reason = 'Internal Server Error'
            mocked.return_value.text = ''
            mocked.return_value.headers = {}
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('500', execution.error)


class SSRFProtectionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('bob', password='secret123')

    def test_localhost_is_blocked(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'http://127.0.0.1:8000/admin',
            'headers': {}, 'query_params': {}, 'body': '',
        })
        execution = WorkflowExecutor().run(wf.pk, {})
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('internal address', execution.error.lower())


class WebhookEndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('carol', password='secret123')

    def test_webhook_endpoint_runs_workflow(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'ok',
        })
        url = reverse('webhook_receive', args=[wf.webhook_token])

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value.status_code = 200
            mocked.return_value.json.return_value = {'ok': True, 'result': {'message_id': 1}}
            response = self.client.post(
                url,
                data=json.dumps({'order_id': 1, 'amount': 10}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        execution = WorkflowExecution.objects.get(pk=response.json()['execution_id'])
        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)

    def test_webhook_wrong_token_returns_404(self):
        response = self.client.post(
            '/webhooks/definitely-not-a-token/',
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    def test_webhook_requires_post(self):
        wf = make_workflow(self.user)
        response = self.client.get(reverse('webhook_receive', args=[wf.webhook_token]))
        self.assertEqual(response.status_code, 405)

    def test_webhook_invalid_json_returns_400(self):
        wf = make_workflow(self.user)
        response = self.client.post(
            reverse('webhook_receive', args=[wf.webhook_token]),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)