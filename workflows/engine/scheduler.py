"""Phase 1 — Scheduler: расчёт следующего запуска и запуск due-расписаний.

Scheduler только создаёт WorkflowExecution; выполнение — за WorkflowExecutor.
"""

import zoneinfo
from datetime import datetime, timedelta

from django.utils import timezone

from croniter import croniter

COMMON_TIMEZONES = [
    'UTC',
    'Europe/Moscow',
    'Europe/Kyiv',
    'Europe/Minsk',
    'Europe/Berlin',
    'Europe/Paris',
    'Europe/London',
    'America/New_York',
    'America/Los_Angeles',
    'Asia/Almaty',
    'Asia/Yekaterinburg',
    'Asia/Novosibirsk',
    'Asia/Tokyo',
    'Asia/Dubai',
    'Australia/Sydney',
]


def get_timezone_choices():
    return [(tz, tz) for tz in COMMON_TIMEZONES]


def compute_next_run(schedule, from_dt=None):
    """Вычисляет следующий запуск в таймзоне расписания (aware datetime)."""
    from_dt = from_dt or timezone.now()
    try:
        tz = zoneinfo.ZoneInfo(schedule.timezone)
    except Exception:
        tz = zoneinfo.ZoneInfo('UTC')
    local = from_dt.astimezone(tz)

    if schedule.schedule_type == schedule.ScheduleType.MINUTES:
        return local + timedelta(minutes=max(1, schedule.interval))
    if schedule.schedule_type == schedule.ScheduleType.HOURS:
        return local + timedelta(hours=max(1, schedule.interval))
    if schedule.schedule_type == schedule.ScheduleType.DAYS:
        return local + timedelta(days=max(1, schedule.interval))
    if schedule.schedule_type == schedule.ScheduleType.DAILY:
        t = schedule.daily_time
        if t is None:
            t = schedule.daily_time.__class__(0, 0)
        next_run = local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if next_run <= local:
            next_run += timedelta(days=1)
        return next_run
    if schedule.schedule_type == schedule.ScheduleType.CRON:
        expression = (schedule.cron_expression or '').strip()
        if not expression:
            return None
        try:
            return croniter(expression, local).get_next(datetime)
        except Exception:
            return None
    return None


def run_due_schedules():
    """Запускает все активные расписания, чей next_run_at наступил.

    Вызывается Celery Beat каждую минуту (workflows.tasks.scheduler_tick).
    """
    from workflows.models import WorkflowSchedule
    from workflows.services import dispatch_execution

    now = timezone.now()
    due = list(
        WorkflowSchedule.objects.select_related('workflow').filter(
            is_active=True, next_run_at__lte=now
        )
    )
    for schedule in due:
        if not schedule.workflow.is_active:
            schedule.is_active = False
            schedule.save(update_fields=['is_active', 'updated_at'])
            continue
        try:
            dispatch_execution(schedule.workflow, {}, trigger='schedule')
        except Exception:
            continue
        schedule.last_run_at = now
        schedule.next_run_at = compute_next_run(schedule, now)
        schedule.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])
    return len(due)