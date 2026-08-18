import re

_VARIABLE_RE = re.compile(r'\{\{\s*([a-zA-Z0-9_\.\-]+)\s*\}\}')


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


def render_text(template, context, fallback=''):
    """Replace {{ a.b }} variables in a string using the execution context."""
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
    """Recursively render variables inside strings, dicts and lists."""
    if isinstance(value, str):
        return render_text(value, context)
    if isinstance(value, dict):
        return {k: render_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, context) for v in value]
    return value