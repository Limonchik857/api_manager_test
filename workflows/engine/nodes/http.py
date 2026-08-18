import ipaddress
import re
from urllib.parse import urlparse

import requests

BLOCKED_HOSTS = {'localhost'}
PRIVATE_PATTERNS = [
    r'^10\.',
    r'^127\.',
    r'^169\.254\.',
    r'^172\.(1[6-9]|2[0-9]|3[01])\.',
    r'^192\.168\.',
]


def _is_private_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_link_local
    except ValueError:
        return False


def _is_blocked(host):
    host = host.lower().rstrip('.')
    if host in BLOCKED_HOSTS or host.endswith('.local') or host.endswith('.internal'):
        return True
    if re.match(r'^\[?[0-9a-f:]+]?$', host):
        clean = host.strip('[]')
        if _is_private_ip(clean):
            return True
    match = re.match(r'^([0-9a-fA-F:.]+)', host)
    if match and _is_private_ip(match.group(1)):
        return True
    return any(re.match(p, host) for p in PRIVATE_PATTERNS)


def validate_url(url):
    """Block requests to internal networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f'Only http/https URLs are allowed: {url}')
    host = parsed.hostname or ''
    if _is_blocked(host):
        raise ValueError(f'Access to internal address is not allowed: {host}')


def execute_http(config, context):
    from ..context import render_value

    method = (render_value(config.get('method') or 'GET', context)).upper()
    url = render_value(config.get('url') or '', context)
    if not url:
        raise ValueError('HTTP Request: URL is required')

    validate_url(url)

    headers = render_value(config.get('headers') or {}, context)
    params = render_value(config.get('query_params') or {}, context)
    body = render_value(config.get('body') or '', context)

    kwargs = {
        'headers': headers,
        'params': params,
        'timeout': 15,
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

    response = requests.request(method, url, **kwargs)

    result = {
        'status_code': response.status_code,
        'headers': dict(response.headers),
        'body': response.text,
    }
    try:
        result['json'] = response.json()
    except ValueError:
        result['json'] = None

    if response.status_code >= 400:
        raise ValueError(
            f'HTTP {response.status_code}: {response.reason or "Request failed"}'
        )

    return result