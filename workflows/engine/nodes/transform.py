"""JSON Transform node.

Преобразует данные из контекста в новую структуру.
Каждое значение — шаблон с {{ переменными }}.
"""


def execute_transform(config, context):
    from ..context import render_value

    mapping = config.get('mapping') or {}
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('JSON Transform: задайте mapping')

    output = render_value(mapping, context)

    if not isinstance(output, dict):
        raise ValueError('JSON Transform: результат должен быть объектом')

    return output