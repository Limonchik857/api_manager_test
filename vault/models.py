from django.conf import settings
from django.db import models


class Secret(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='secrets',
    )
    name = models.CharField(max_length=255)
    encrypted_value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'],
                name='unique_secret_name_per_owner',
            )
        ]

    def __str__(self):
        return self.name

    @property
    def masked_value(self):
        from .services import SecretService
        try:
            return SecretService.mask(SecretService.decrypt(self.encrypted_value))
        except Exception:
            return '********'