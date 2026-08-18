from django.db import models


class WorkflowTemplate(models.Model):
    """Phase 15 — Templates: готовые сценарии для копирования."""

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=64, blank=True, default='')
    definition = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name