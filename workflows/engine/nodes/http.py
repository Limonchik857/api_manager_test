import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse

import requests

from ..retry import RetrySignal

BLOCKED_HOSTS = {'localhost'}
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_RESOLVE_CACHE = {}


def _is_private_or_internal(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _is_blocked_hostname(host):
    host = host.lower().rstrip('.')
    if host in BLOCKED_HOSTS or host.endswith('.local') or host.endswith('.internal'):
        return True
    return False


def resolve_host_ips(host):
    """DNS resolve — проверяем ВСЕ возвращённые IP (A и AAAA). Кэшируется."""
    host = host.lower()
    if host in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[host]
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        _RESOLVE_CACHE[host] = None
        return None
    ips = {info[4][0] for info in infos}
    _RESOLVE_CACHE[host] = ips
    return ips


def validate_url(url):
    """SSRF protection: resolve DNS и блокировать private/internal адреса."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f'Разрешены только http/https URL: {url}')
    host = parsed.hostname or ''
    if _is_blocked_hostname(host):
        raise ValueError(f'Доступ к внутреннему адресу запрещён: {host}')

    ip_text = host.strip('[]')
    try:
        ipaddress.ip_address(ip_text)
    except ValueError:
        pass
    else:
        if _is_private_or_internal(ip_text):
            raise ValueError(f'Доступ к внутренней сети запрещён: {host}')
        return

    ips = resolve_host_ips(host)
    if ips is None:
        raise ValueError(f'Не удалось разрешить адрес: {host}')
    for ip in ips:
        if _is_private_or_internal(ip):
            raise ValueError(f'Доступ к внутренней сети запрещён: {ip}')


class MaxResponseExceeded(Exception):
    def __init__(self, size):
        super().__init__(f'Ответ слишком большой: {size} байт')
        self.size = size


def execute_http(config, context, max_response_size=None, max_redirects=None):
    from django.conf import settings

    from ..context import render_value

    if max_response_size is None:
        max_response_size = settings.MAX_RESPONSE_SIZE
    if max_redirects is None:
        max_redirects = settings.MAX_HTTP_REDIRECTS

    method = (render_value(config.get('method') or 'GET', context)).upper()
    url = render_value(config.get('url') or '', context)
    if not url:
        raise ValueError('HTTP Request: URL обязателен')

    headers = render_value(config.get('headers') or {}, context)
    params = render_value(config.get('query_params') or {}, context)
    body = render_value(config.get('body') or '', context)

    session = requests.Session()

    def request_once(current_url):
        validate_url(current_url)
        kwargs = {
            'headers': headers,
            'params': params,
            'timeout': 15,
            'allow_redirects': False,
            'stream': True,
        }
        if method in ('POST', 'PUT', 'PATCH'):
            if isinstance(body, dict):
                kwargs['json'] = body
            elif isinstance(body, str):
                kwargs['data'] = body.encode('utf-8') if body else body
                if not headers.get('Content-Type'):
                    kwargs['headers']['Content-Type'] = 'application/json'
        elif method == 'DELETE' and body:
            kwargs['data'] = body

        try:
            response = session.request(method, current_url, **kwargs)
        except requests.RequestException as exc:
            raise RetrySignal(f'Сетевая ошибка: {exc}')

        if response.status_code in REDIRECT_STATUSES:
            location = response.headers.get('Location')
            response.close()
            return response, location, None

        chunks = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                total += len(chunk)
                if total > max_response_size:
                    response.close()
                    raise MaxResponseExceeded(total)
                chunks.append(chunk)
        except requests.RequestException as exc:
            response.close()
            raise RetrySignal(f'Ошибка чтения ответа: {exc}')
        return response, None, b''.join(chunks)

    def finish(response, raw_body):
        result = {
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'body': raw_body.decode('utf-8', errors='replace') if raw_body else '',
        }
        try:
            result['json'] = response.json()
        except ValueError:
            result['json'] = None
        if response.status_code >= 500:
            raise RetrySignal(
                f'HTTP {response.status_code}: {response.reason or "Ошибка сервера"}'
            )
        if response.status_code >= 400:
            raise ValueError(
                f'HTTP {response.status_code}: {response.reason or "Запрос не выполнен"}'
            )
        return result

    current_url = url
    for _ in range(max_redirects + 1):
        response, location, raw_body = request_once(current_url)
        if location:
            current_url = urljoin(current_url, location)
            continue
        result = finish(response, raw_body)
        return result
    raise ValueError('Слишком много редиректов')