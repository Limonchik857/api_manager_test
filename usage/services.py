"""Phase 13-14 — Usage и Limits: учёт запусков и ограничения по плану."""

from datetime import datetime

from django.utils import timezone

PLANS = {
    'free': {
        'workflows': 5,
        'nodes_per_workflow': 10,
        'executions_per_month': 1000,
        'schedules': 5,
    },
    'pro': {
        'workflows': 50,
        'nodes_per_workflow': 50,
        'executions_per_month': 25000,
        'schedules': 50,
    },
}


class LimitExceeded(Exception):
    pass


def get_user_profile(user):
    profile, _ = user.profile
    return profile


def get_plan(user):
    try:
        return user.profile.plan
    except Exception:
        return 'free'


def get_limits(user):
    return PLANS.get(get_plan(user), PLANS['free'])


def get_monthly_execution_count(user, now=None):
    from executions.models import WorkflowExecution
    now = now or timezone.now()
    return WorkflowExecution.objects.filter(
        workflow__owner=user,
        started_at__year=now.year,
        started_at__month=now.month,
    ).count()


def workflows_count(user):
    return user.workflows.count()


def active_schedules_count(user):
    from workflows.models import WorkflowSchedule
    return WorkflowSchedule.objects.filter(
        workflow__owner=user, is_active=True
    ).count()


def connections_count(user):
    return user.connections.count()


def get_usage_summary(user, now=None):
    now = now or timezone.now()
    limits = get_limits(user)
    executions = get_monthly_execution_count(user, now)
    return {
        'plan': get_plan(user),
        'executions': executions,
        'executions_limit': limits['executions_per_month'],
        'workflows_count': workflows_count(user),
        'workflows_limit': limits['workflows'],
        'active_schedules': active_schedules_count(user),
        'connections_count': connections_count(user),
        'limits': limits,
    }


def enforce_limits(user):
    """Проверяет лимиты перед созданием Workflow / Node / Execution."""
    limits = get_limits(user)

    if workflows_count(user) >= limits['workflows']:
        raise LimitExceeded(
            f'Достигнут лимит плана {get_plan(user).upper()}: '
            f'не более {limits["workflows"]} сценариев'
        )

    if active_schedules_count(user) >= limits['schedules']:
        raise LimitExceeded(
            f'Достигнут лимит плана {get_plan(user).upper()}: '
            f'не более {limits["schedules"]} активных расписаний'
        )


def enforce_node_limit(user, workflow):
    limits = get_limits(user)
    if workflow.nodes.count() >= limits['nodes_per_workflow']:
        raise LimitExceeded(
            f'Достигнут лимит плана {get_plan(user).upper()}: '
            f'не более {limits["nodes_per_workflow"]} шагов в сценарии'
        )


def enforce_execution_limit(user, now=None):
    limits = get_limits(user)
    if get_monthly_execution_count(user, now) >= limits['executions_per_month']:
        raise LimitExceeded('Вы достигли месячного лимита запусков')