class StopWorkflow(Exception):
    """Поднимается, когда Condition не выполнен — остальные узлы пропускаются."""


def execute_condition(config, context):
    from ..conditions import evaluate_conditions

    conditions = config.get('conditions') or []
    logic = (config.get('logic') or 'AND').upper()

    matched = evaluate_conditions(conditions, logic, context)
    if not matched:
        raise StopWorkflow('Условие не выполнено')

    return {'matched': True, 'logic': logic}