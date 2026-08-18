"""
Django settings for API Automation Studio.
Все чувствительные значения приходят из environment (.env для локальной разработки).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ('1', 'true', 'yes', 'on')


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-change-me')
DEBUG = env_bool('DEBUG', True)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '*').split(',') if h.strip()]

# Ключ шифрования секретов (Fernet). Обязателен в production.
SECRET_ENCRYPTION_KEY = os.environ.get('SECRET_ENCRYPTION_KEY', '')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'vault',
    'workflows',
    'executions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Для rate limiting webhook (локальный кэш; в production — Redis).
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'automation-studio',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'landing'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Базовый URL для построения абсолютных webhook-URL в интерфейсе.
SITE_URL = os.environ.get('SITE_URL', 'http://127.0.0.1:8000')

# ── Лимиты безопасности ──────────────────────────────────────

# Максимальный размер webhook payload (байт).
MAX_WEBHOOK_PAYLOAD = env_int('MAX_WEBHOOK_PAYLOAD', 1024 * 1024)

# Максимальный размер ответа внешнего API в HTTP Node (байт).
MAX_RESPONSE_SIZE = env_int('MAX_RESPONSE_SIZE', 1024 * 1024)

# Максимальный объём сохраняемых данных в логах (байт).
MAX_EXECUTION_INPUT = env_int('MAX_EXECUTION_INPUT', 512 * 1024)
MAX_EXECUTION_OUTPUT = env_int('MAX_EXECUTION_OUTPUT', 512 * 1024)
MAX_NODE_OUTPUT = env_int('MAX_NODE_OUTPUT', 512 * 1024)

# Rate limit webhook: запросов в минуту на один Workflow.
WEBHOOK_RATE_LIMIT_PER_MINUTE = env_int('WEBHOOK_RATE_LIMIT_PER_MINUTE', 100)

# Лимит редиректов в HTTP Node.
MAX_HTTP_REDIRECTS = env_int('MAX_HTTP_REDIRECTS', 5)