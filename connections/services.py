from django.db.models import Count

from vault.services import SecretService, SecretError


class ConnectionError(Exception):
    pass


def create_connection(owner, name, connection_type, token):
    """Создаёт подключение: токен шифруется и сохраняется как Secret."""
    secret = SecretService.set_secret(
        owner, f'connection-{connection_type}-{name.lower()[:40]}', token
    )
    from .models import Connection
    return Connection.objects.create(
        owner=owner, name=name, connection_type=connection_type, secret=secret
    )


def resolve_token(connection, user):
    """Возвращает расшифрованный токен подключения (с проверкой владельца)."""
    if connection.owner_id != user.pk:
        raise ConnectionError('Connection not found')
    if connection.secret is None:
        raise ConnectionError(f'Подключение «{connection.name}» не содержит credentials')
    try:
        return SecretService.decrypt(connection.secret.encrypted_value)
    except SecretError as exc:
        raise ConnectionError(str(exc))


def get_user_connection(user, connection_id):
    from .models import Connection
    return Connection.objects.filter(pk=connection_id, owner=user).first()


def get_connections_for_user(user, connection_type=None):
    from .models import Connection
    qs = Connection.objects.filter(owner=user)
    if connection_type:
        qs = qs.filter(connection_type=connection_type)
    return qs


def connections_count(user):
    from .models import Connection
    return Connection.objects.filter(owner=user).count()


def matches_connection(owner, connection_type, name):
    """Ищет подключение по типу и имени (для import/export)."""
    from .models import Connection
    return Connection.objects.filter(
        owner=owner, connection_type=connection_type, name=name
    ).first()


def get_connection_usage_counts():
    from django.db.models import Count
    return Connection.objects.annotate(workflow_count=Count('workflow')).values_list(
        'pk', 'name', 'workflow_count'
    )