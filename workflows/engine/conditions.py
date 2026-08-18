class ConditionError(ValueError):
    pass


def _resolve_operand(value, context):
    """Operand is either a variable reference (starts with {{ }}) or a literal."""
    value = (value or '').strip()
    if value.startswith('{{') and value.endswith('}}'):
        from .context import render_text
        return render_text(value, context, fallback=None)
    return value


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(left, operator, right, context):
    """Evaluate a single condition against the execution context.

    Supported operators: = != > < >= <= contains exists
    """
    operator = (operator or '=').strip()
    if operator == 'exists':
        return _resolve_operand(left, context) is not None

    left_value = _resolve_operand(left, context)
    right_value = _resolve_operand(right, context)

    if operator in ('>', '<', '>=', '<='):
        lnum = _to_number(left_value)
        rnum = _to_number(right_value)
        if lnum is None or rnum is None:
            raise ConditionError(
                f'Cannot compare "{left_value}" with "{right_value}" as numbers'
            )
        if operator == '>':
            return lnum > rnum
        if operator == '<':
            return lnum < rnum
        if operator == '>=':
            return lnum >= rnum
        return lnum <= rnum

    if operator == 'contains':
        return str(right_value) in str(left_value or '')

    if operator == '=':
        return str(left_value) == str(right_value)
    if operator == '!=':
        return str(left_value) != str(right_value)

    raise ConditionError(f'Unknown operator: {operator}')