import requests

TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'


def execute_telegram(config, context):
    from ..context import render_value
    from vault.services import SecretService, SecretError

    secret_id = config.get('secret_id')
    chat_id = render_value(config.get('chat_id') or '', context)
    message = render_value(config.get('message') or '', context)

    if secret_id:
        bot_token = SecretService.get_value(context['_user'], int(secret_id))
    else:
        bot_token = render_value(config.get('bot_token') or '', context)

    if not bot_token:
        raise ValueError('Telegram: Bot Token обязателен')
    if not chat_id:
        raise ValueError('Telegram: Chat ID обязателен')
    if not message:
        raise ValueError('Telegram: текст сообщения обязателен')

    response = requests.post(
        TELEGRAM_API.format(token=bot_token.strip()),
        json={
            'chat_id': chat_id.strip(),
            'text': message,
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

    data = response.json()
    return {
        'message_id': data.get('result', {}).get('message_id'),
        'chat_id': chat_id,
    }