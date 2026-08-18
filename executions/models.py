from django.db import models


class WorkflowExecution(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'QUEUED'
        RUNNING = 'running', 'RUNNING'
        RETRYING = 'retrying', 'RETRYING'
        SUCCESS = 'success', 'SUCCESS'
        FAILED = 'failed', 'FAILED'
        CANCELLED = 'cancelled', 'CANCELLED'

    class Trigger(models.TextChoices):
        WEBHOOK = 'webhook', 'webhook'
        TEST = 'test', 'test'
        SCHEDULE = 'schedule', 'schedule'
        REPLAY = 'replay', 'replay'
        MANUAL = 'manual', 'manual'

    workflow = models.ForeignKey(
        'workflows.Workflow',
        on_delete=models.CASCADE,
        related_name='executions',
    )
    trigger = models.CharField(
        max_length=10,
        choices=Trigger.choices,
        default=Trigger.WEBHOOK,
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED
    )
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Execution #{self.pk} — {self.workflow.name}'


class NodeExecution(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', 'RUNNING'
        RETRYING = 'retrying', 'RETRYING'
        SUCCESS = 'success', 'SUCCESS'
        FAILED = 'failed', 'FAILED'
        SKIPPED = 'skipped', 'SKIPPED'

    execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name='node_executions',
    )
    node = models.ForeignKey(
        'workflows.WorkflowNode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executions',
    )
    node_name = models.CharField(max_length=255, default='')
    status = models.CharField(max_length=10, choices=Status.choices)
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)
    attempt_number = models.PositiveIntegerField(default=1)
    max_attempts = models.PositiveIntegerField(default=1)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['started_at', 'id']

    def __str__(self):
        return f'{self.node_name} — {self.get_status_display()}'