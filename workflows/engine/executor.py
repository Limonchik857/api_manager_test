import time

from django.conf import settings
from django.utils import timezone

from executions.models import WorkflowExecution, NodeExecution
from executions.services import truncate_data
from workflows.models import Workflow, WorkflowNode
from .nodes import get_handler
from .nodes.condition import StopWorkflow


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


class WorkflowExecutor:

    def run(self, workflow_id, input_data):
        workflow = Workflow.objects.prefetch_related('nodes').get(pk=workflow_id)
        nodes = list(workflow.nodes.all())
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            input_data=truncate_data(
                input_data, settings.MAX_EXECUTION_INPUT, 'Входные данные'
            )[0],
        )

        context = {
            'trigger': input_data or {},
            'execution_id': execution.pk,
            '_user': workflow.owner,
        }
        if isinstance(input_data, dict):
            context.update(input_data)

        try:
            for node in nodes:
                self._run_node(execution, node, context)
        except StopWorkflow as exc:
            self._skip_remaining(execution, nodes, context, exc)
        except Exception as exc:
            execution.status = WorkflowExecution.Status.FAILED
            execution.error = str(exc)[:4000]
        finally:
            execution.finished_at = timezone.now()
            execution.duration = round(
                (execution.finished_at - execution.started_at).total_seconds(), 3
            )
            execution.output_data, _ = truncate_data(
                _trim_context(context), settings.MAX_EXECUTION_OUTPUT, 'Выходные данные'
            )
            execution.save()

        return execution

    def _run_node(self, execution, node, context):
        started = time.monotonic()
        node_exec = NodeExecution.objects.create(
            execution=execution,
            node=node,
            node_name=node.name or node.get_node_type_display(),
            status=NodeExecution.Status.SUCCESS,
            input_data=_trim_context(context),
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
        except Exception as exc:
            node_exec.status = NodeExecution.Status.FAILED
            node_exec.error = str(exc)[:4000]
            raise
        finally:
            node_exec.finished_at = timezone.now()
            node_exec.duration = round(time.monotonic() - started, 3)
            node_exec.save(update_fields=[
                'output_data', 'status', 'error', 'finished_at', 'duration',
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