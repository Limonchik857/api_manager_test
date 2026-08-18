import requests

TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'


def _resolve_bot_token(config, context):
    from ..context import render_value
    from connections.models import Connection
    from connections.services import resolve_token
    from vault.services import SecretService

    connection_id = config.get('connection_id')
    if connection_id:
        connection = Connection.objects.filter(pk=connection_id).first()
        if connection is None:
            raise ValueError('Telegram: подключение не найдено')
        return resolve_token(connection, context['_user'])

    secret_id = config.get('secret_id')
    if secret_id:
        return SecretService.get_value(context['_user'], int(secret_id))

    return render_value(config.get('bot_token') or '', context)


def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or not chat_id or not text:
        raise ValueError('Telegram: Bot Token, Chat ID и текст обязательны')
    response = requests.post(
        TELEGRAM_API.format(token=bot_token.strip()),
        json={
            'chat_id': chat_id.strip(),
            'text': text,
            'disable_web_page_preview': True,
        },
        timeout=15,
    )
    if response.status_code != 200:
        detail = ''
        try:
            detail = response.json().get('description', '')
        except ValueError:
            detail = response.text[:200]
        raise ValueError(f'Ошибка Telegram API {response.status_code}: {detail}')
    return response.json()


def execute_telegram(config, context):
    from ..context import render_value

    chat_id = render_value(config.get('chat_id') or '', context)
    message = render_value(config.get('message') or '', context)
    bot_token = _resolve_bot_token(config, context)
    if not bot_token:
        raise ValueError('Telegram: Bot Token обязателен')

    data = send_telegram_message(bot_token, chat_id, message)
    return {
        'message_id': data.get('result', {}).get('message_id'),
        'chat_id': chat_id,
    }