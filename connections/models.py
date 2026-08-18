from django.conf import settings
from django.db import models


class Connection(models.Model):
    """Phase 8 — Connections: переиспользуемое подключение (credentials + название)."""

    class Type(models.TextChoices):
        TELEGRAM = 'telegram', 'Telegram'
        HTTP = 'http', 'HTTP'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='connections',
    )
    name = models.CharField(max_length=255)
    connection_type = models.CharField(
        max_length=20, choices=Type.choices, default=Type.TELEGRAM
    )
    secret = models.ForeignKey(
        'vault.Secret',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'], name='unique_connection_name'
            ),
        ]

    def __str__(self):
        return self.name