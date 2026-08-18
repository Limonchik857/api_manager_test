import json
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from connections.models import Connection
from connections.services import create_connection
from executions.models import NodeExecution, WorkflowExecution
from usage.services import LimitExceeded
from vault.models import Secret
from vault.services import SecretService
from workflows.engine.context import render_value
from workflows.engine.executor import WorkflowExecutor
from workflows.engine.conditions import evaluate_conditions
from workflows.engine.scheduler import compute_next_run, run_due_schedules
from workflows.models import Workflow, WorkflowNode, WorkflowSchedule, WorkflowVersion
from workflows.services import (
    dispatch_execution,
    export_workflow,
    import_workflow,
    restore_workflow_version,
    save_workflow_version,
)

TEST_KEY = Fernet.generate_key().decode()

RETRY_HTTP_CONFIG = {
    'method': 'GET',
    'url': 'https://example.com/x',
    'headers': {}, 'query_params': {}, 'body': '',
    'retry': {'max_attempts': 3, 'backoff_base': 0},
    'on_error': 'retry',
}


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


def fake_response(status_code=200, json_body=None, text='', headers=None,
                  reason='OK', chunks=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.reason = reason
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError('no json')
    else:
        resp.json.return_value = json_body
    resp.iter_content.return_value = chunks or ([text.encode()] if text else [b''])
    resp.close = mock.Mock()
    return resp


class ExecutorTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('alex', password='secret123')

    def test_webhook_condition_telegram_success(self):
        wf = make_workflow(self.user, 'Large Order Alert')
        add_node(wf, WorkflowNode.NodeType.CONDITION, 'Condition', {
            'conditions': [{'left': '{{ amount }}', 'operator': '>', 'right': '3000'}],
            'logic': 'AND',
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-100123',
            'message': 'Order {{ order_id }} from {{ customer }}: {{ amount }}',
        })
        payload = {'order_id': 1537, 'customer': 'Alex', 'amount': 5000}

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(200, {'ok': True, 'result': {'message_id': 42}})
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
            'logic': 'AND',
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'hi',
        })

        execution = WorkflowExecutor().run(wf.pk, {'amount': 100})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        statuses = list(execution.node_executions.values_list('status', flat=True))
        self.assertEqual(statuses, ['success', 'success', 'skipped'])

    def test_and_conditions_both_required(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.CONDITION, 'C', {
            'conditions': [
                {'left': '{{ amount }}', 'operator': '>', 'right': '3000'},
                {'left': '{{ status }}', 'operator': '=', 'right': 'paid'},
            ],
            'logic': 'AND',
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'T', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
        })
        execution = WorkflowExecutor().run(wf.pk, {'amount': 5000, 'status': 'pending'})
        statuses = list(execution.node_executions.values_list('status', flat=True))
        self.assertEqual(statuses, ['success', 'success', 'skipped'])

    def test_or_conditions_any(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.CONDITION, 'C', {
            'conditions': [
                {'left': '{{ amount }}', 'operator': '>', 'right': '3000'},
                {'left': '{{ status }}', 'operator': '=', 'right': 'paid'},
            ],
            'logic': 'OR',
        })
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'T', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
        })
        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(200, {'ok': True, 'result': {'message_id': 1}})
            execution = WorkflowExecutor().run(wf.pk, {'amount': 100, 'status': 'paid'})
        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)

    def test_telegram_error_fails_execution(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'hi',
        })

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(401, {'ok': False, 'description': 'Unauthorized'})
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
            'headers': {}, 'query_params': {}, 'body': {},
            'retry': {},
        })

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.return_value = fake_response(200, {'ok': True}, '{"ok": true}')
            execution = WorkflowExecutor().run(wf.pk, {'customer': 'Alex', 'amount': 5000})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        self.assertEqual(mocked.call_args[0][0], 'POST')
        self.assertEqual(mocked.call_args[0][1], 'https://httpbin.org/post')

    def test_http_http_error_fails(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'https://example.com/x',
            'headers': {}, 'query_params': {}, 'body': '', 'retry': {},
        })

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.return_value = fake_response(500, reason='Internal Server Error', text='')
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('500', execution.error)

    def test_http_retry_succeeds_on_second_attempt(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', RETRY_HTTP_CONFIG)

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.side_effect = [
                fake_response(500, reason='Server Error', text=''),
                fake_response(200, {'ok': True}, '{"ok": true}'),
            ]
            execution = WorkflowExecutor().run(wf.pk, {})

        execution.refresh_from_db()
        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        self.assertEqual(mocked.call_count, 2)
        node_exec = execution.node_executions.get(node__node_type='http')
        self.assertEqual(node_exec.status, NodeExecution.Status.SUCCESS)
        self.assertEqual(node_exec.attempt_number, 2)
        self.assertEqual(node_exec.max_attempts, 3)

    def test_retry_exhausted_fails(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', RETRY_HTTP_CONFIG)

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.return_value = fake_response(503, reason='Unavailable', text='')
            execution = WorkflowExecutor().run(wf.pk, {})

        execution.refresh_from_db()
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertEqual(mocked.call_count, 3)
        node_exec = execution.node_executions.get(node__node_type='http')
        self.assertEqual(node_exec.status, NodeExecution.Status.FAILED)
        self.assertEqual(node_exec.attempt_number, 3)

    def test_transform_node(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'Transform', {
            'mapping': {
                'name': '{{ first_name }}',
                'amount': '{{ price }}',
                'currency': 'RUB',
            },
        })
        execution = WorkflowExecutor().run(wf.pk, {'first_name': 'Alex', 'price': 5000})
        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        transform_output = execution.node_executions.get(
            node__node_type='transform'
        ).output_data
        self.assertEqual(transform_output, {
            'name': 'Alex',
            'amount': 5000,
            'currency': 'RUB',
        })


class ErrorHandlingTests(TestCase):
    """Phase 5 — on_error: stop / retry / continue."""

    def setUp(self):
        self.user = User.objects.create_user('alex2', password='secret123')

    def test_continue_policy_keeps_workflow_running(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Fails', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
            'on_error': 'continue',
        })
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'After', {
            'mapping': {'ok': 'yes'},
        })

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(401, {'ok': False, 'description': 'No'})
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        statuses = list(execution.node_executions.values_list('status', flat=True))
        self.assertEqual(statuses, ['success', 'failed', 'success'])

    def test_stop_policy_fails_execution(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Fails', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
            'on_error': 'stop',
        })
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'After', {'mapping': {'ok': 'yes'}})

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(401, {'ok': False, 'description': 'No'})
            execution = WorkflowExecutor().run(wf.pk, {})
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        statuses = list(execution.node_executions.values_list('status', flat=True))
        self.assertEqual(statuses, ['success', 'failed'])
        self.assertEqual(execution.node_executions.count(), 2)


class VariableTypingTests(TestCase):

    def test_preserves_types(self):
        context = {'amount': 5000, 'is_active': True, 'nullable': None, 'tags': ['a', 'b']}
        self.assertEqual(render_value('{{ amount }}', context), 5000)
        self.assertIsInstance(render_value('{{ amount }}', context), int)
        self.assertEqual(render_value('{{ is_active }}', context), True)
        self.assertEqual(render_value('{{ nullable }}', context), None)
        self.assertEqual(render_value('{{ tags }}', context), ['a', 'b'])
        self.assertEqual(
            render_value('Order amount: {{ amount }}', context),
            'Order amount: 5000',
        )


class SSRFProtectionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('bob', password='secret123')

    def _run_http(self, url):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': url,
            'headers': {}, 'query_params': {}, 'body': '', 'retry': {},
        })
        return WorkflowExecutor().run(wf.pk, {})

    def test_localhost_is_blocked(self):
        execution = self._run_http('http://127.0.0.1:8000/admin')
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('внутренней', execution.error.lower())

    def test_localhost_hostname_is_blocked(self):
        execution = self._run_http('http://localhost:8000/admin')
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)

    def test_private_ip_is_blocked(self):
        execution = self._run_http('http://192.168.1.10/')
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('внутренней', execution.error.lower())

    def test_link_local_is_blocked(self):
        execution = self._run_http('http://169.254.169.254/latest/meta-data/')
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)

    def test_redirect_to_internal_is_blocked(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'https://public.example.com/',
            'headers': {}, 'query_params': {}, 'body': '', 'retry': {},
        })

        def redirect_response(*args, **kwargs):
            return fake_response(
                302, headers={'Location': 'http://127.0.0.1:8000/internal/'}
            )

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.side_effect = redirect_response
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('внутренней', execution.error.lower())
        self.assertEqual(mocked.call_count, 1)


@override_settings(SECRET_ENCRYPTION_KEY=TEST_KEY)
class ConnectionTests(TestCase):
    """Phase 8 — Connections."""

    def setUp(self):
        self.user = User.objects.create_user('carol', password='secret123')
        self.other = User.objects.create_user('dan', password='secret123')

    def test_create_connection_encrypts_token(self):
        connection = create_connection(
            self.user, 'Мой бот', 'telegram', '123456:TOKEN'
        )
        self.assertNotEqual(connection.secret.encrypted_value, '123456:TOKEN')
        self.assertIn('123456', SecretService.decrypt(connection.secret.encrypted_value))

    def test_resolve_token_checks_ownership(self):
        connection = create_connection(
            self.user, 'Мой бот', 'telegram', '123456:TOKEN'
        )
        from connections.services import resolve_token
        self.assertEqual(resolve_token(connection, self.user), '123456:TOKEN')
        with self.assertRaises(Exception):
            resolve_token(connection, self.other)

    def test_telegram_node_via_connection(self):
        connection = create_connection(
            self.user, 'Мой бот', 'telegram', '123456:TOKEN'
        )
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'connection_id': connection.pk,
            'chat_id': '-100',
            'message': 'hi',
        })

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(200, {'ok': True, 'result': {'message_id': 1}})
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        url = mocked.call_args[0][0]
        self.assertIn('123456:TOKEN', url)


@override_settings(SECRET_ENCRYPTION_KEY=TEST_KEY)
class SecretTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('erin', password='secret123')

    def test_encrypt_decrypt_roundtrip(self):
        secret = SecretService.set_secret(self.user, 'telegram-bot-token', '123456:ABC')
        self.assertNotEqual(secret.encrypted_value, '123456:ABC')
        self.assertEqual(
            SecretService.get_value(self.user, secret.pk), '123456:ABC'
        )

    def test_mask(self):
        self.assertEqual(
            SecretService.mask('1234567890abcdef'),
            '123456******************def',
        )

    def test_secret_not_exposed_in_template(self):
        token = '111111:SUPERSECRETTOKENXYZ'
        secret = SecretService.set_secret(self.user, 'telegram-bot-token', token)
        wf = make_workflow(self.user)
        node = add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'secret_id': secret.pk, 'chat_id': '1', 'message': 'hi',
        })

        self.client.force_login(self.user)
        response = self.client.get(reverse('node_edit', args=[wf.pk, node.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(token, response.content.decode('utf-8'))


class OwnershipTests(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user('owner', password='secret123')
        self.other = User.objects.create_user('other', password='secret123')
        self.wf = make_workflow(self.owner)

    def test_delete_requires_post(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('workflow_delete', args=[self.wf.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Workflow.objects.filter(pk=self.wf.pk).exists())

    def test_delete_via_post_works(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('workflow_delete', args=[self.wf.pk]))
        self.assertRedirects(response, '/dashboard/')
        self.assertFalse(Workflow.objects.filter(pk=self.wf.pk).exists())

    def test_cannot_delete_others_workflow(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('workflow_delete', args=[self.wf.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Workflow.objects.filter(pk=self.wf.pk).exists())

    def test_cannot_view_others_execution(self):
        self.client.force_login(self.owner)
        execution = WorkflowExecutor().run(self.wf.pk, {})
        self.client.force_login(self.other)
        response = self.client.get(reverse('execution_detail', args=[execution.pk]))
        self.assertEqual(response.status_code, 404)


class NodeReorderTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('dave', password='secret123')

    def test_node_reorder(self):
        wf = make_workflow(self.user)
        a = add_node(wf, WorkflowNode.NodeType.HTTP, 'A', {
            'method': 'GET', 'url': 'https://example.com', 'headers': {},
            'query_params': {}, 'body': '', 'retry': {},
        })
        b = add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'B', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
        })

        self.client.force_login(self.user)
        self.client.post(reverse('node_move', args=[wf.pk, b.pk, 'up']))

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.position, 3)
        self.assertEqual(b.position, 2)


class WebhookLimitsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('fred', password='secret123')

    def test_payload_too_large_returns_413(self):
        wf = make_workflow(self.user)
        url = reverse('webhook_receive', args=[wf.webhook_token])
        with override_settings(MAX_WEBHOOK_PAYLOAD=100):
            response = self.client.post(
                url,
                data=json.dumps({'data': 'x' * 500}),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 413)

    def test_rate_limit_returns_429(self):
        wf = make_workflow(self.user)
        url = reverse('webhook_receive', args=[wf.webhook_token])
        with override_settings(WEBHOOK_RATE_LIMIT_PER_MINUTE=2):
            for _ in range(2):
                self.client.post(url, data='{}', content_type='application/json')
            response = self.client.post(url, data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 429)

    def test_response_size_limit(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'https://example.com/',
            'headers': {}, 'query_params': {}, 'body': '', 'retry': {},
        })
        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.return_value = fake_response(200, text='x' * 5000)
            with override_settings(MAX_RESPONSE_SIZE=100):
                execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertIn('слишком большой', execution.error)

    def test_execution_log_truncation(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'Transform', {
            'mapping': {'big': '{{ data }}'},
        })
        payload = {'data': 'x' * 20000}
        with override_settings(MAX_NODE_OUTPUT=500):
            execution = WorkflowExecutor().run(wf.pk, payload)
        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        output = execution.node_executions.get(node__node_type='transform').output_data
        self.assertIn('truncated_note', output)


class WebhookEndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('grace', password='secret123')

    def test_webhook_endpoint_runs_workflow(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': '123:test', 'chat_id': '-1', 'message': 'ok',
        })
        url = reverse('webhook_receive', args=[wf.webhook_token])

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.return_value = fake_response(200, {'ok': True, 'result': {'message_id': 1}})
            response = self.client.post(
                url,
                data=json.dumps({'order_id': 1, 'amount': 10}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('execution_id', data)
        execution = WorkflowExecution.objects.get(pk=data['execution_id'])
        self.assertEqual(execution.trigger, 'webhook')
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


class SchedulerTests(TestCase):
    """Phase 1 — Scheduler."""

    def setUp(self):
        self.user = User.objects.create_user('hank', password='secret123')
        self.wf = make_workflow(self.user)

    def _schedule(self, schedule_type, **kwargs):
        return WorkflowSchedule.objects.create(
            workflow=self.wf, schedule_type=schedule_type, **kwargs
        )

    def test_compute_minutes(self):
        from django.utils import timezone
        s = self._schedule('minutes', interval=30, timezone='UTC')
        base = timezone.now().replace(microsecond=0)
        self.assertEqual(
            compute_next_run(s, base), base + __import__('datetime').timedelta(minutes=30)
        )

    def test_compute_daily_time(self):
        import datetime
        from django.utils import timezone
        s = self._schedule('daily', daily_time=datetime.time(9, 0), timezone='UTC')
        base = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        next_run = compute_next_run(s, base)
        self.assertEqual(next_run.hour, 9)
        self.assertEqual(next_run.minute, 0)
        self.assertEqual((next_run - base).days, 0)

    def test_compute_daily_time_passed(self):
        import datetime
        from django.utils import timezone
        s = self._schedule('daily', daily_time=datetime.time(9, 0), timezone='UTC')
        base = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        next_run = compute_next_run(s, base)
        self.assertEqual(next_run.hour, 9)
        self.assertEqual((next_run - base).total_seconds(), 23 * 3600)

    def test_compute_cron(self):
        from django.utils import timezone
        s = self._schedule('cron', cron_expression='0 */2 * * *', timezone='UTC')
        base = timezone.now().replace(minute=5, second=0, microsecond=0)
        next_run = compute_next_run(s, base)
        self.assertEqual(next_run.minute, 0)
        self.assertEqual(next_run.hour % 2, 0)
        self.assertGreater(next_run, base)

    def test_run_due_schedules_creates_executions(self):
        from django.utils import timezone
        s = self._schedule(
            'minutes', interval=30, timezone='UTC',
            is_active=True, next_run_at=timezone.now() - __import__('datetime').timedelta(minutes=1),
        )
        count = run_due_schedules()
        self.assertEqual(count, 1)
        self.assertEqual(
            WorkflowExecution.objects.filter(workflow=self.wf, trigger='schedule').count(), 1
        )
        s.refresh_from_db()
        self.assertIsNotNone(s.last_run_at)
        self.assertGreater(s.next_run_at, s.last_run_at)

    def test_inactive_schedule_skipped(self):
        s = self._schedule('minutes', interval=30, timezone='UTC', is_active=False)
        self.assertEqual(run_due_schedules(), 0)
        self.assertIsNone(s.last_run_at)


class UsageLimitsTests(TestCase):
    """Phase 13-14 — Usage и Limits."""

    def setUp(self):
        self.user = User.objects.create_user('iris', password='secret123')

    def test_monthly_execution_count(self):
        wf = make_workflow(self.user)
        for _ in range(3):
            WorkflowExecutor().run(wf.pk, {})
        from usage.services import get_monthly_execution_count
        self.assertEqual(get_monthly_execution_count(self.user), 3)

    def test_usage_summary(self):
        wf = make_workflow(self.user)
        WorkflowExecutor().run(wf.pk, {})
        from usage.services import get_usage_summary
        usage = get_usage_summary(self.user)
        self.assertEqual(usage['plan'], 'free')
        self.assertEqual(usage['executions'], 1)
        self.assertEqual(usage['workflows_count'], 1)
        self.assertEqual(usage['executions_limit'], 1000)

    def test_workflow_limit_enforced(self):
        with mock.patch('usage.services.PLANS', {
            'free': {'workflows': 2, 'nodes_per_workflow': 10,
                     'executions_per_month': 1000, 'schedules': 5},
            'pro': {'workflows': 50, 'nodes_per_workflow': 50,
                    'executions_per_month': 25000, 'schedules': 50},
        }):
            make_workflow(self.user, 'A')
            make_workflow(self.user, 'B')
            self.client.force_login(self.user)
            response = self.client.post(reverse('workflow_create'), {
                'name': 'C', 'description': '', 'is_active': 'on',
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Workflow.objects.filter(owner=self.user).count(), 2)

    def test_node_limit_enforced(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'T1', {'mapping': {'a': '1'}})
        with mock.patch('usage.services.PLANS', {
            'free': {'workflows': 5, 'nodes_per_workflow': 2,
                     'executions_per_month': 1000, 'schedules': 5},
            'pro': {'workflows': 50, 'nodes_per_workflow': 50,
                    'executions_per_month': 25000, 'schedules': 50},
        }):
            self.client.force_login(self.user)
            response = self.client.post(
                reverse('node_add', args=[wf.pk, 'transform']),
                {'node_type': 'transform', 'name': 'T2',
                 'mapping': '{"b": "2"}', 'on_error': 'stop'},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(wf.nodes.count(), 2)

    def test_execution_limit_webhook_429(self):
        wf = make_workflow(self.user)
        url = reverse('webhook_receive', args=[wf.webhook_token])
        with mock.patch('usage.services.PLANS', {
            'free': {'workflows': 5, 'nodes_per_workflow': 10,
                     'executions_per_month': 1, 'schedules': 5},
            'pro': {'workflows': 50, 'nodes_per_workflow': 50,
                    'executions_per_month': 25000, 'schedules': 50},
        }):
            first = self.client.post(url, data='{}', content_type='application/json')
            self.assertEqual(first.status_code, 200)
            second = self.client.post(url, data='{}', content_type='application/json')
            self.assertEqual(second.status_code, 429)
            self.assertIn('лимит', second.json()['error'])


@override_settings(SECRET_ENCRYPTION_KEY=TEST_KEY)
class FailureNotificationTests(TestCase):
    """Phase 7 — уведомление после N ошибок подряд."""

    def setUp(self):
        self.user = User.objects.create_user('jack', password='secret123')
        self.connection = create_connection(
            self.user, 'Alert Bot', 'telegram', '999:TOKEN'
        )

    def _fake_send(self, token, chat_id, text):
        if token == '999:TOKEN':
            return {'ok': True, 'result': {'message_id': 1}}
        raise ValueError('Ошибка Telegram API 401: Unauthorized')

    def _failing_workflow(self, notify_after=3):
        wf = make_workflow(self.user, 'Order Sync')
        wf.notify_on_failure = True
        wf.notify_after_consecutive = notify_after
        wf.notify_telegram_connection = self.connection
        wf.notify_telegram_chat_id = '-100'
        wf.save()
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
        })
        return wf

    def _notify_calls(self, send):
        return [c for c in send.call_args_list if c[0][0] == '999:TOKEN']

    def test_no_notification_below_threshold(self):
        wf = self._failing_workflow(notify_after=5)
        with mock.patch('workflows.engine.nodes.telegram.send_telegram_message',
                        side_effect=self._fake_send) as send:
            for _ in range(3):
                execution = WorkflowExecutor().run(wf.pk, {})
        self.assertEqual(execution.status, WorkflowExecution.Status.FAILED)
        self.assertEqual(self._notify_calls(send), [])

    def test_notification_after_threshold(self):
        wf = self._failing_workflow()
        with mock.patch('workflows.engine.nodes.telegram.send_telegram_message',
                        side_effect=self._fake_send) as send:
            for _ in range(3):
                execution = WorkflowExecutor().run(wf.pk, {})
        notify_calls = self._notify_calls(send)
        self.assertEqual(len(notify_calls), 1)
        text = notify_calls[0][0][2]
        self.assertIn('Order Sync', text)
        self.assertIn('3', text)

    def test_notify_disabled_no_notification(self):
        wf = self._failing_workflow()
        wf.notify_on_failure = False
        wf.save()
        with mock.patch('workflows.engine.nodes.telegram.send_telegram_message',
                        side_effect=self._fake_send) as send:
            for _ in range(3):
                WorkflowExecutor().run(wf.pk, {})
        self.assertEqual(self._notify_calls(send), [])


class TemplateTests(TestCase):
    """Phase 15 — Templates."""

    def setUp(self):
        self.user = User.objects.create_user('kim', password='secret123')

    def test_use_template_creates_copy(self):
        from catalog.models import WorkflowTemplate
        template = WorkflowTemplate.objects.get(name='Webhook → Telegram')
        from catalog.services import create_workflow_from_template
        workflow = create_workflow_from_template(self.user, template)
        self.assertEqual(workflow.name, 'Webhook → Telegram (копия)')
        self.assertEqual(workflow.nodes.count(), 2)
        telegram_node = workflow.nodes.get(node_type='telegram')
        self.assertNotIn('connection_id', telegram_node.configuration)
        self.assertNotIn('secret_id', telegram_node.configuration)

    def test_templates_seeded(self):
        from catalog.models import WorkflowTemplate
        self.assertEqual(WorkflowTemplate.objects.count(), 5)

    def test_use_template_limits(self):
        from catalog.models import WorkflowTemplate
        from catalog.services import create_workflow_from_template
        with mock.patch('usage.services.PLANS', {
            'free': {'workflows': 0, 'nodes_per_workflow': 10,
                     'executions_per_month': 1000, 'schedules': 5},
            'pro': {'workflows': 50, 'nodes_per_workflow': 50,
                    'executions_per_month': 25000, 'schedules': 50},
        }):
            with self.assertRaises(LimitExceeded):
                create_workflow_from_template(
                    self.user, WorkflowTemplate.objects.get(name='Webhook → Telegram')
                )


class VersioningTests(TestCase):
    """Phase 16 — Versioning."""

    def setUp(self):
        self.user = User.objects.create_user('leo', password='secret123')
        self.wf = make_workflow(self.user, 'v1 name')

    def test_version_created_on_change(self):
        save_workflow_version(self.wf)
        self.wf.name = 'v2 name'
        self.wf.save()
        save_workflow_version(self.wf)
        versions = list(self.wf.versions.all())
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].version, 2)
        self.assertTrue(versions[0].is_current)
        self.assertEqual(versions[1].name_snapshot, 'v1 name')

    def test_identical_change_skips_version(self):
        save_workflow_version(self.wf)
        save_workflow_version(self.wf)
        self.assertEqual(self.wf.versions.count(), 1)

    def test_restore_creates_new_version(self):
        save_workflow_version(self.wf)
        add_node(self.wf, WorkflowNode.NodeType.TRANSFORM, 'Extra', {'mapping': {'a': '1'}})
        save_workflow_version(self.wf)
        self.wf.name = 'renamed'
        self.wf.save()
        save_workflow_version(self.wf)

        restore_workflow_version(self.wf, 1)
        self.wf.refresh_from_db()
        self.assertEqual(self.wf.name, 'v1 name')
        self.assertFalse(self.wf.nodes.filter(name='Extra').exists())
        self.assertEqual(self.wf.versions.count(), 4)
        current = self.wf.versions.filter(is_current=True).get()
        self.assertEqual(current.version, 4)


@override_settings(SECRET_ENCRYPTION_KEY=TEST_KEY)
class ImportExportTests(TestCase):
    """Phase 17 — Import / Export."""

    def setUp(self):
        self.user = User.objects.create_user('mia', password='secret123')

    def test_export_strips_secrets(self):
        connection = create_connection(self.user, 'Мой бот', 'telegram', '111:TOKEN')
        wf = make_workflow(self.user, 'Export me')
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Telegram', {
            'connection_id': connection.pk,
            'chat_id': '-1',
            'message': 'hi {{ x }}',
        })
        data = export_workflow(wf)
        telegram = data['nodes'][1]
        self.assertNotIn('connection_id', telegram['configuration'])
        self.assertNotIn('secret_id', telegram['configuration'])
        self.assertEqual(
            telegram['configuration']['connection']['connection_name'], 'Мой бот'
        )

    def test_import_creates_new_workflow(self):
        data = {
            'name': 'Imported',
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {'type': 'transform', 'name': 'T', 'configuration': {'mapping': {'a': '{{ x }}'}}},
            ],
        }
        workflow = import_workflow(self.user, data)
        self.assertEqual(workflow.name, 'Imported (импорт)')
        self.assertEqual(workflow.nodes.count(), 2)
        self.assertNotEqual(workflow.pk, make_workflow(self.user).pk)

    def test_import_matches_connection_by_name(self):
        create_connection(self.user, 'Мой бот', 'telegram', '111:TOKEN')
        data = {
            'name': 'Imported',
            'nodes': [
                {'type': 'webhook', 'name': 'Webhook', 'configuration': {}},
                {
                    'type': 'telegram', 'name': 'Telegram',
                    'configuration': {
                        'connection': {'connection_type': 'telegram', 'connection_name': 'Мой бот'},
                        'chat_id': '-1', 'message': 'hi',
                    },
                },
            ],
        }
        workflow = import_workflow(self.user, data)
        telegram = workflow.nodes.get(node_type='telegram')
        connection = Connection.objects.get(pk=telegram.configuration['connection_id'])
        self.assertEqual(connection.name, 'Мой бот')

    def test_import_requires_webhook_node(self):
        data = {'name': 'NoWebhook', 'nodes': []}
        workflow = import_workflow(self.user, data)
        self.assertTrue(workflow.nodes.filter(node_type='webhook').exists())


class ReplayTests(TestCase):
    """Phase 12 — Replay."""

    def setUp(self):
        self.user = User.objects.create_user('nina', password='secret123')

    def test_replay_entire_execution(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'T', {'mapping': {'x': '{{ n }}'}})
        execution = WorkflowExecutor().run(wf.pk, {'n': 42})
        self.client.force_login(self.user)
        response = self.client.post(reverse('execution_replay', args=[execution.pk]))
        self.assertEqual(response.status_code, 302)
        new_execution = WorkflowExecution.objects.exclude(pk=execution.pk).get()
        self.assertEqual(new_execution.trigger, 'replay')
        self.assertEqual(new_execution.input_data, {'n': 42})

    def test_retry_from_failed_node(self):
        wf = make_workflow(self.user)
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'Ok', {'mapping': {'a': '1'}})
        add_node(wf, WorkflowNode.NodeType.TELEGRAM, 'Bad', {
            'bot_token': 'x', 'chat_id': '1', 'message': 'hi',
        })
        add_node(wf, WorkflowNode.NodeType.TRANSFORM, 'Tail', {'mapping': {'c': '3'}})

        with mock.patch('workflows.engine.nodes.telegram.requests.post') as mocked:
            mocked.side_effect = [
                fake_response(401, {'ok': False, 'description': 'No'}),
                fake_response(200, {'ok': True, 'result': {'message_id': 1}}),
            ]
            execution = WorkflowExecutor().run(wf.pk, {'n': 1})
            failed = execution.node_executions.get(node__name='Bad')

            self.client.force_login(self.user)
            response = self.client.post(
                reverse('execution_retry_from_node', args=[execution.pk, failed.pk])
            )
        self.assertEqual(response.status_code, 302)
        new_execution = WorkflowExecution.objects.exclude(pk=execution.pk).latest('pk')
        names = list(new_execution.node_executions.values_list('node_name', flat=True))
        self.assertEqual(names, ['Bad', 'Tail'])
        self.assertEqual(new_execution.status, WorkflowExecution.Status.SUCCESS)