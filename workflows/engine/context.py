import re

_VARIABLE_RE = re.compile(r'\{\{\s*([a-zA-Z0-9_\.\-]+)\s*\}\}')
_FULL_VARIABLE_RE = re.compile(r'^\s*\{\{\s*([a-zA-Z0-9_\.\-]+)\s*\}\}\s*$')


def _resolve_path(data, path):
    current = data
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _path_exists(data, path):
    current = data
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def render_text(template, context, fallback=''):
    """Заменяет {{ a.b }} на строки контекста. Строки-шаблоны всегда строки."""
    if template is None:
        return ''
    if isinstance(template, str):
        def replace(match):
            value = _resolve_path(context, match.group(1))
            if value is None:
                return fallback
            if isinstance(value, (dict, list)):
                import json
                return json.dumps(value, ensure_ascii=False)
            return str(value)
        return _VARIABLE_RE.sub(replace, template)
    return template


def render_value(value, context):
    """Рендерит переменные с сохранением исходных типов.

    - "{{ amount }}"  -> 5000 (int, а не "5000")
    - "{{ is_active }}" -> True (bool)
    - "Сумма: {{ amount }}" -> "Сумма: 5000" (строка)
    """
    if isinstance(value, str):
        full_match = _FULL_VARIABLE_RE.match(value)
        if full_match:
            path = full_match.group(1)
            if _path_exists(context, path):
                return _resolve_path(context, path)
            return value
        return render_text(value, context)
    if isinstance(value, dict):
        return {k: render_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, context) for v in value]
    return value