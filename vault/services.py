from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

from .models import Secret


class SecretError(Exception):
    pass


class SecretService:

    @staticmethod
    def _get_fernet():
        key = settings.SECRET_ENCRYPTION_KEY
        if not key:
            raise SecretError(
                'SECRET_ENCRYPTION_KEY is not configured — set it in .env'
            )
        try:
            return Fernet(key.encode())
        except Exception as exc:
            raise SecretError(f'Invalid SECRET_ENCRYPTION_KEY: {exc}')

    @classmethod
    def encrypt(cls, plaintext):
        return cls._get_fernet().encrypt(plaintext.encode('utf-8')).decode('utf-8')

    @classmethod
    def decrypt(cls, encrypted_value):
        try:
            return cls._get_fernet().decrypt(
                encrypted_value.encode('utf-8')
            ).decode('utf-8')
        except InvalidToken:
            raise SecretError('Unable to decrypt secret: corrupted value')

    @classmethod
    def set_secret(cls, user, name, value):
        secret = Secret.objects.filter(owner=user, name=name).first()
        if secret is None:
            secret = Secret(owner=user, name=name)
        secret.encrypted_value = cls.encrypt(value)
        secret.save()
        return secret

    @classmethod
    def get_value(cls, user, secret_id):
        secret = Secret.objects.filter(pk=secret_id, owner=user).first()
        if secret is None:
            raise SecretError('Secret not found')
        return cls.decrypt(secret.encrypted_value)

    @classmethod
    def mask(cls, value, visible=6, hidden=18):
        """Маскирует секрет: видимы первые символы и последние 3."""
        if len(value) <= visible + 4:
            return '*' * min(len(value), hidden)
        return f'{value[:visible]}{"*" * hidden}{value[-3:]}'