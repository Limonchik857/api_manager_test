class StopWorkflow(Exception):
    """Raised when a Condition evaluates to False — remaining nodes are skipped."""


def execute_condition(config, context):
    from ..conditions import evaluate_condition

    conditions = config.get('conditions') or []
    if not conditions:
        raise ValueError('Condition: no conditions configured')

    for condition in conditions:
        result = evaluate_condition(
            condition.get('left', ''),
            condition.get('operator', '='),
            condition.get('right', ''),
            context,
        )
        if not result:
            raise StopWorkflow(
                f'Condition failed: {condition.get("left", "")} '
                f'{condition.get("operator", "=")} {condition.get("right", "")}'
            )

    return {'matched': True}