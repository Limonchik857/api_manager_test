class ConditionError(ValueError):
    pass


def _resolve_operand(value, context):
    """Операнд — переменная ({{ x }}) или литерал."""
    value = (value or '').strip()
    if value.startswith('{{') and value.endswith('}}'):
        from .context import render_value
        return render_value(value, context)
    return value


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(left_value, right_value, operator):
    if operator == 'exists':
        return left_value is not None

    if operator in ('>', '<', '>=', '<='):
        lnum = _to_number(left_value)
        rnum = _to_number(right_value)
        if lnum is None or rnum is None:
            raise ConditionError(
                f'Нельзя сравнить "{left_value}" и "{right_value}" как числа'
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

    raise ConditionError(f'Неизвестный оператор: {operator}')


def evaluate_conditions(conditions, logic, context):
    """AND/OR-логика для списка условий."""
    if not conditions:
        raise ConditionError('Condition: не заданы условия')

    results = []
    for condition in conditions:
        results.append(_compare(
            _resolve_operand(condition.get('left', ''), context),
            _resolve_operand(condition.get('right', ''), context),
            condition.get('operator', '='),
        ))

    if logic == 'OR':
        return any(results)
    return all(results)