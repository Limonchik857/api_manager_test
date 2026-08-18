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