import secrets

from django.conf import settings
from django.db import models


class WorkflowQuerySet(models.QuerySet):

    def annotate_execution_stats(self):
        from django.db.models import Count, Max
        return self.annotate(
            execution_count=Count('executions', distinct=True),
            last_run=Max('executions__started_at'),
        )


class Workflow(models.Model):
    class OnErrorPolicy(models.TextChoices):
        STOP = 'stop', 'Stop'
        RETRY = 'retry', 'Retry'
        CONTINUE = 'continue', 'Continue'

    objects = WorkflowQuerySet.as_manager()

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workflows',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    webhook_token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        default=secrets.token_urlsafe,
    )
    is_active = models.BooleanField(default=True)

    # ── Error handling (Phase 5) ─────────────────────────────
    default_on_error = models.CharField(
        max_length=10,
        choices=OnErrorPolicy.choices,
        default=OnErrorPolicy.STOP,
    )

    # ── Failure notifications (Phase 7) ──────────────────────
    notify_on_failure = models.BooleanField(default=True)
    notify_after_consecutive = models.PositiveIntegerField(default=3)
    notify_telegram_connection = models.ForeignKey(
        'connections.Connection',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    notify_telegram_chat_id = models.CharField(max_length=64, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def webhook_url(self):
        return f'{settings.SITE_URL}/webhooks/{self.webhook_token}/'

    def regenerate_webhook_token(self):
        self.webhook_token = secrets.token_urlsafe(48)
        self.save(update_fields=['webhook_token'])


class WorkflowNode(models.Model):
    class NodeType(models.TextChoices):
        WEBHOOK = 'webhook', 'Webhook'
        CONDITION = 'condition', 'Condition'
        HTTP = 'http', 'HTTP Request'
        TELEGRAM = 'telegram', 'Telegram'
        TRANSFORM = 'transform', 'JSON Transform'

    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='nodes',
    )
    node_type = models.CharField(max_length=20, choices=NodeType.choices)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    configuration = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.get_node_type_display()} — {self.name}'


class WorkflowSchedule(models.Model):
    """Phase 1 — Scheduler: периодический запуск Workflow."""

    class ScheduleType(models.TextChoices):
        MINUTES = 'minutes', 'каждые N минут'
        HOURS = 'hours', 'каждые N часов'
        DAILY = 'daily', 'каждый день в определённое время'
        DAYS = 'days', 'каждый N-й день'
        CRON = 'cron', 'cron-выражение'

    workflow = models.OneToOneField(
        Workflow,
        on_delete=models.CASCADE,
        related_name='schedule',
    )
    schedule_type = models.CharField(
        max_length=10,
        choices=ScheduleType.choices,
        default=ScheduleType.MINUTES,
    )
    interval = models.PositiveIntegerField(default=30)
    daily_time = models.TimeField(null=True, blank=True)
    cron_expression = models.CharField(max_length=100, blank=True, default='')
    timezone = models.CharField(max_length=64, default='Europe/Moscow')
    is_active = models.BooleanField(default=False)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Schedule: {self.workflow.name} ({self.get_schedule_type_display()})'


class WorkflowVersion(models.Model):
    """Phase 16 — Versioning: снапшот состояния Workflow."""

    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    version = models.PositiveIntegerField()
    name_snapshot = models.CharField(max_length=255)
    description_snapshot = models.TextField(blank=True, default='')
    nodes_snapshot = models.JSONField(default=list, blank=True)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'version'], name='unique_workflow_version'
            ),
        ]

    def __str__(self):
        return f'v{self.version} — {self.workflow.name}'