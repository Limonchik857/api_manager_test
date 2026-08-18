"""Celery-задачи: async execution (P3), retry (P4), scheduler (P1), уведомления (P7)."""

from celery import shared_task


@shared_task(bind=True, max_retries=0)
def run_workflow_task(self, workflow_id, input_data=None, trigger='webhook',
                      execution_id=None, resume_node_execution=None):
    from .engine.executor import WorkflowExecutor
    return WorkflowExecutor().run(
        workflow_id,
        input_data=input_data,
        trigger=trigger,
        execution_id=execution_id,
        resume_node_execution=resume_node_execution,
    )


@shared_task(bind=True, max_retries=0)
def retry_node_task(self, execution_id, node_execution_id):
    """Повторная попытка узла после временной ошибки (exponential backoff)."""
    from executions.models import WorkflowExecution
    from .engine.executor import WorkflowExecutor
    execution = WorkflowExecution.objects.get(pk=execution_id)
    return WorkflowExecutor().run(
        execution.workflow_id,
        execution_id=execution_id,
        resume_node_execution=node_execution_id,
    )


@shared_task(bind=True)
def scheduler_tick(self):
    """Celery Beat: каждую минуту запускает due-расписания."""
    from .engine.scheduler import run_due_schedules
    return run_due_schedules()


@shared_task(bind=True, max_retries=0)
def notify_failure_task(self, execution_id):
    from notifications.services import notify_workflow_failure
    return notify_workflow_failure(execution_id)