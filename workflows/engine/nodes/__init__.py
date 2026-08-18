from . import http, telegram, condition, webhook

NODE_HANDLERS = {
    'webhook': webhook.execute_webhook,
    'condition': condition.execute_condition,
    'http': http.execute_http,
    'telegram': telegram.execute_telegram,
}


def get_handler(node_type):
    handler = NODE_HANDLERS.get(node_type)
    if handler is None:
        raise ValueError(f'Unknown node type: {node_type}')
    return handler