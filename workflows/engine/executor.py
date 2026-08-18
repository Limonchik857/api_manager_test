import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from executions.models import NodeExecution, WorkflowExecution
from executions.services import truncate_data
from workflows.models import Workflow, WorkflowNode
from .nodes import get_handler
from .nodes.condition import StopWorkflow
from .retry import RetrySignal


def slugify(name):
    slug = ''.join(
        c.lower() if c.isalnum() else '_' for c in name
    ).strip('_')
    slug = '_'.join(slug.split('_')) if slug else 'node'
    if not slug:
        slug = 'node'
    if not slug[0].isalpha() and not slug[0] == '_':
        slug = 'node_' + slug
    return slug


def _trim_context(context):
    return {k: v for k, v in context.items() if not k.startswith('_')}


class _RetryScheduled(Exception):
    """Внутренний сигнал: retry запланирован через Celery, выполнение приостановлено."""


class WorkflowExecutor:

    def run(self, workflow_id, input_data=None, trigger='webhook',
            execution_id=None, resume_node_execution=None):
        """Запускает (или продолжает) выполнение Workflow.

        - execution_id=None       → создаёт новое выполнение (QUEUED → RUNNING).
        - resume_node_execution   → стартует с конкретного узла; если он относится
          к тому же выполнению (execution_id), это повторная попытка (attempt+1),
          иначе — новый Replay с контекстом узла.
        """
        workflow = Workflow.objects.prefetch_related('nodes').get(pk=workflow_id)
        nodes = list(workflow.nodes.all())

        resume = None
        if execution_id is not None:
            execution = WorkflowExecution.objects.get(pk=execution_id, workflow=workflow)
            if resume_node_execution is not None:
                resume = NodeExecution.objects.get(pk=resume_node_execution)
                resume.input_data = resume.input_data or {}
                nodes = [
                    n for n in nodes
                    if resume.node is None or n.position >= resume.node.position
                ]
                if resume.execution_id == execution.pk:
                    resume.status = NodeExecution.Status.RUNNING
                    resume.attempt_number += 1
                    resume.error = ''
                    resume.finished_at = None
                    resume.duration = None
                    resume.next_retry_at = None
                    resume.save(update_fields=[
                        'status', 'attempt_number', 'error', 'finished_at',
                        'duration', 'next_retry_at',
                    ])
        else:
            execution = WorkflowExecution.objects.create(
                workflow=workflow,
                input_data=truncate_data(
                    input_data if isinstance(input_data, dict) else {},
                    settings.MAX_EXECUTION_INPUT,
                    'Входные данные',
                )[0],
                trigger=trigger,
                status=WorkflowExecution.Status.QUEUED,
            )

        context = {}
        if resume is not None:
            context = dict(resume.input_data)
        elif isinstance(input_data, dict):
            context = dict(input_data)
        context['trigger'] = input_data or {}
        context['execution_id'] = execution.pk
        context['_user'] = workflow.owner

        execution.status = WorkflowExecution.Status.RUNNING
        execution.error = ''
        execution.finished_at = None
        execution.duration = None
        execution.save(update_fields=['status', 'error', 'finished_at', 'duration'])

        try:
            for node in nodes:
                self._run_node(execution, node, context, resume=resume)
                resume = None
        except StopWorkflow as exc:
            self._skip_remaining(execution, nodes, context, exc)
            execution.status = WorkflowExecution.Status.SUCCESS
        except _RetryScheduled:
            execution.refresh_from_db()
            return execution
        except Exception as exc:
            execution.status = WorkflowExecution.Status.FAILED
            execution.error = str(exc)[:4000]
        else:
            execution.status = WorkflowExecution.Status.SUCCESS
        finally:
            if execution.status != WorkflowExecution.Status.RETRYING:
                execution.finished_at = timezone.now()
                execution.duration = round(
                    (execution.finished_at - execution.started_at).total_seconds(), 3
                )
                execution.output_data, _ = truncate_data(
                    _trim_context(context), settings.MAX_EXECUTION_OUTPUT,
                    'Выходные данные'
                )
                execution.save()

        if execution.status == WorkflowExecution.Status.FAILED:
            try:
                from workflows.services import broker_available
                from workflows.tasks import notify_failure_task
                if broker_available():
                    notify_failure_task.apply_async(
                        kwargs={'execution_id': execution.pk}
                    )
                else:
                    notify_failure_task(execution_id=execution.pk)
            except Exception:
                pass

        return execution

    def _error_policy(self, node, execution):
        return (
            node.configuration.get('on_error')
            or execution.workflow.default_on_error
            or Workflow.OnErrorPolicy.STOP
        )

    def _max_attempts(self, node, execution):
        retry = node.configuration.get('retry') or {}
        configured = int(retry.get('max_attempts') or 0)
        if configured > 0:
            return configured
        if self._error_policy(node, execution) == Workflow.OnErrorPolicy.RETRY:
            return 3
        return 1

    def _retry_delay(self, node, attempt):
        retry = node.configuration.get('retry') or {}
        base = float(retry.get('backoff_base') or 5)
        return min(base * (3 ** (attempt - 1)), 60)

    def _run_node(self, execution, node, context, resume=None):
        started = time.monotonic()
        if resume is not None and resume.node_id == node.pk and resume.execution_id == execution.pk:
            node_exec = resume
        else:
            node_exec = NodeExecution.objects.create(
                execution=execution,
                node=node,
                node_name=node.name or node.get_node_type_display(),
                status=NodeExecution.Status.RUNNING,
                input_data=_trim_context(context),
                attempt_number=1,
                max_attempts=self._max_attempts(node, execution),
            )

        try:
            handler = get_handler(node.node_type)
            output = handler(node.configuration, context)

            if isinstance(output, dict):
                context.update(output)
                key = slugify(node.name)
                if not key:
                    key = node.node_type
                context[key] = output

            node_exec.output_data, truncated = truncate_data(
                output, settings.MAX_NODE_OUTPUT, 'Выходные данные шага'
            )
            if truncated:
                node_exec.error = node_exec.output_data.get('truncated_note', {}).get(
                    'note', 'Выходные данные обрезаны'
                )[:4000]
            node_exec.status = NodeExecution.Status.SUCCESS
        except StopWorkflow:
            node_exec.status = NodeExecution.Status.SUCCESS
            node_exec.output_data = {'matched': False}
            raise
        except RetrySignal as exc:
            if self._error_policy(node, execution) == Workflow.OnErrorPolicy.RETRY \
                    and node_exec.attempt_number < node_exec.max_attempts:
                delay = self._retry_delay(node, node_exec.attempt_number)
                node_exec.status = NodeExecution.Status.RETRYING
                node_exec.error = (
                    f'Попытка {node_exec.attempt_number}/{node_exec.max_attempts}: {exc}'
                )[:4000]
                node_exec.next_retry_at = timezone.now() + timedelta(seconds=delay)
                node_exec.finished_at = None
                node_exec.duration = None
                node_exec.save(update_fields=[
                    'status', 'error', 'next_retry_at', 'finished_at', 'duration',
                ])
                execution.status = WorkflowExecution.Status.RETRYING
                execution.save(update_fields=['status'])
                from workflows.services import broker_available
                from workflows.tasks import retry_node_task
                if broker_available():
                    retry_node_task.apply_async(
                        kwargs={
                            'execution_id': execution.pk,
                            'node_execution_id': node_exec.pk,
                        },
                        countdown=delay,
                    )
                else:
                    retry_node_task(
                        execution_id=execution.pk,
                        node_execution_id=node_exec.pk,
                    )
                raise _RetryScheduled()
            node_exec.status = NodeExecution.Status.FAILED
            node_exec.error = f'{exc}'[:4000]
            node_exec.save(update_fields=['status', 'error'])
            raise
        except Exception as exc:
            node_exec.status = NodeExecution.Status.FAILED
            node_exec.error = str(exc)[:4000]
            node_exec.save(update_fields=['status', 'error'])
            if self._error_policy(node, execution) == Workflow.OnErrorPolicy.CONTINUE:
                return
            raise
        finally:
            if node_exec.status != NodeExecution.Status.RETRYING:
                node_exec.finished_at = timezone.now()
                node_exec.duration = round(time.monotonic() - started, 3)
                node_exec.save(update_fields=[
                    'status', 'output_data', 'error', 'finished_at', 'duration',
                ])

    def _skip_remaining(self, execution, nodes, context, exc):
        started_nodes = {
            ne.node_id for ne in execution.node_executions.all()
        }
        for node in nodes:
            if node.pk in started_nodes:
                continue
            NodeExecution.objects.create(
                execution=execution,
                node=node,
                node_name=node.name or node.get_node_type_display(),
                status=NodeExecution.Status.SKIPPED,
                error=f'Предыдущее условие не выполнено: {exc}',
            )