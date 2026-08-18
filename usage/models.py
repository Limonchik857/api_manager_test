from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Phase 14 — Limits: план пользователя."""

    class Plan(models.TextChoices):
        FREE = 'free', 'FREE'
        PRO = 'pro', 'PRO'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.FREE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} — {self.get_plan_display()}'