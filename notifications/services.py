"""Phase 7 — Failure notifications: полезные уведомления о реальных сбоях."""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def count_consecutive_failures(workflow, limit=50):
    from executions.models import WorkflowExecution
    count = 0
    for execution in workflow.executions.order_by('-started_at')[:limit]:
        if execution.status == WorkflowExecution.Status.FAILED:
            count += 1
        elif execution.status == WorkflowExecution.Status.SUCCESS:
            break
    return count


def notify_workflow_failure(execution_id):
    """Отправляет Telegram-уведомление, если workflow сломался.

    Уведомление отправляется только каждые N подряд идущих ошибок
    (notify_after_consecutive), чтобы не спамить после временных сбоев.
    """
    from executions.models import WorkflowExecution
    from connections.services import resolve_token
    from workflows.engine.nodes.telegram import send_telegram_message

    execution = WorkflowExecution.objects.select_related('workflow').get(
        pk=execution_id
    )
    workflow = execution.workflow
    if not workflow.notify_on_failure:
        return False
    if execution.trigger == 'replay':
        return False

    threshold = max(1, workflow.notify_after_consecutive)
    consecutive = count_consecutive_failures(workflow)
    if consecutive < threshold or consecutive % threshold != 0:
        return False

    connection = workflow.notify_telegram_connection
    chat_id = workflow.notify_telegram_chat_id
    if connection is None or not chat_id:
        return False

    try:
        token = resolve_token(connection, workflow.owner)
        text = (
            f'⚠ {workflow.name} завершился ошибкой {consecutive} раз подряд.\n\n'
            f'Последняя ошибка:\n{execution.error[:500]}'
        )
        send_telegram_message(token, chat_id, text)
        return True
    except Exception as exc:
        logger.warning('Failed to send failure notification: %s', exc)
        return False