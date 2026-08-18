import json

from django.conf import settings


def truncate_data(value, limit=None, label='данные'):
    """Обрезает JSON-данные до лимита. Возвращает (данные, truncated_flag)."""
    if limit is None:
        limit = settings.MAX_EXECUTION_OUTPUT

    serialized = json.dumps(value, ensure_ascii=False, default=str)
    size = len(serialized.encode('utf-8'))
    if size <= limit:
        return value, False

    kept = serialized.encode('utf-8')[:limit]
    note = {
        '__truncated__': True,
        'original_size_bytes': size,
        'saved_size_bytes': len(kept),
        'note': f'{label} обрезаны: было {size} байт, сохранено {len(kept)} байт',
    }
    try:
        truncated = json.loads(kept.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        truncated = {'__truncated__': True, 'raw_preview': kept.decode('utf-8', errors='replace')}
    return {'truncated_note': note, **truncated}, True