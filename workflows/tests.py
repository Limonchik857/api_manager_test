import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from executions.models import NodeExecution, WorkflowExecution
from vault.models import Secret
from vault.services import SecretService
from workflows.engine.context import render_value
from workflows.engine.executor import WorkflowExecutor
from workflows.engine.conditions import evaluate_conditions
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
        add_node(wf, WorkflowNode.NodeType.HTTP, 'HTTP Request', {
            'method': 'GET', 'url': 'https://example.com/x',
            'headers': {}, 'query_params': {}, 'body': '',
            'retry': {'max_attempts': 3, 'backoff_base': 0},
        })

        with mock.patch('workflows.engine.nodes.http.resolve_host_ips',
                        return_value={'93.184.216.34'}), \
             mock.patch('workflows.engine.nodes.http.requests.Session.request') as mocked:
            mocked.side_effect = [
                fake_response(500, reason='Server Error', text=''),
                fake_response(200, {'ok': True}, '{"ok": true}'),
            ]
            execution = WorkflowExecutor().run(wf.pk, {})

        self.assertEqual(execution.status, WorkflowExecution.Status.SUCCESS)
        self.assertEqual(mocked.call_count, 2)

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


class SecretTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('carol', password='secret123')

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
        self.user = User.objects.create_user('erin', password='secret123')

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
        self.user = User.objects.create_user('carol', password='secret123')

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