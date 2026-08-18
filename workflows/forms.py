import json

from django import forms

from connections.models import Connection
from vault.models import Secret
from workflows.engine.scheduler import get_timezone_choices
from .models import Workflow, WorkflowNode, WorkflowSchedule

NODE_TYPE_LABELS = WorkflowNode.NodeType.choices
CONDITION_OPERATORS = [
    ('=', '='),
    ('!=', '!='),
    ('>', '>'),
    ('<', '<'),
    ('>=', '>='),
    ('<=', '<='),
    ('contains', 'contains'),
    ('exists', 'exists'),
]
CONDITION_LOGIC = [
    ('AND', 'AND (все условия)'),
    ('OR', 'OR (любое условие)'),
]
HTTP_METHODS = [
    ('GET', 'GET'),
    ('POST', 'POST'),
    ('PUT', 'PUT'),
    ('PATCH', 'PATCH'),
    ('DELETE', 'DELETE'),
]
ON_ERROR_CHOICES = [
    ('stop', 'Остановить сценарий'),
    ('retry', 'Повторить (retry)'),
    ('continue', 'Продолжить (пропустить шаг)'),
]

INPUT_CLASS = 'form-input'
MONO_CLASS = 'form-input mono'


class OnErrorMixin(forms.Form):
    on_error = forms.ChoiceField(
        label='При ошибке',
        choices=ON_ERROR_CHOICES,
        initial='stop',
        help_text='Что делать, если шаг завершился ошибкой',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )


class WorkflowForm(forms.ModelForm):
    notify_telegram_connection = forms.ModelChoiceField(
        label='Telegram-подключение для уведомлений',
        required=False,
        queryset=Connection.objects.none(),
        help_text='Куда отправлять уведомления о сбоях (подключения из раздела «Подключения»)',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )

    class Meta:
        model = Workflow
        fields = (
            'name', 'description', 'is_active',
            'default_on_error', 'notify_on_failure',
            'notify_after_consecutive', 'notify_telegram_connection',
            'notify_telegram_chat_id',
        )
        labels = {
            'name': 'Название',
            'description': 'Описание',
            'is_active': 'Активен',
            'default_on_error': 'Поведение при ошибке (по умолчанию)',
            'notify_on_failure': 'Уведомлять о сбоях',
            'notify_after_consecutive': 'Уведомлять после N ошибок подряд',
            'notify_telegram_chat_id': 'Chat ID для уведомлений',
        }
        widgets = {
            'name': forms.TextInput(
                attrs={'class': INPUT_CLASS, 'placeholder': 'Например: Мониторинг сайта'}
            ),
            'description': forms.Textarea(
                attrs={'class': INPUT_CLASS, 'rows': 3}
            ),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'default_on_error': forms.Select(attrs={'class': INPUT_CLASS}),
            'notify_on_failure': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'notify_after_consecutive': forms.NumberInput(
                attrs={'class': INPUT_CLASS, 'min': 1, 'max': 20}
            ),
            'notify_telegram_chat_id': forms.TextInput(
                attrs={'class': MONO_CLASS, 'placeholder': 'например -100123456789'}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['notify_telegram_connection'].queryset = (
                Connection.objects.filter(owner=user, connection_type='telegram')
            )


class WorkflowScheduleForm(forms.ModelForm):
    class Meta:
        model = WorkflowSchedule
        fields = (
            'schedule_type', 'interval', 'daily_time', 'cron_expression',
            'timezone', 'is_active',
        )
        labels = {
            'schedule_type': 'Частота',
            'interval': 'Интервал',
            'daily_time': 'Время (для «каждый день»)',
            'cron_expression': 'Cron-выражение',
            'timezone': 'Часовой пояс',
            'is_active': 'Расписание включено',
        }
        widgets = {
            'schedule_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'interval': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 1}),
            'daily_time': forms.TimeInput(
                attrs={'class': INPUT_CLASS, 'type': 'time'}
            ),
            'cron_expression': forms.TextInput(
                attrs={'class': MONO_CLASS, 'placeholder': '*/30 * * * *'}
            ),
            'timezone': forms.Select(choices=get_timezone_choices()),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class WebhookNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='webhook')
    name = forms.CharField(
        label='Название',
        initial='Webhook',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )


class ConditionNodeForm(OnErrorMixin):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='condition')
    name = forms.CharField(
        label='Название',
        initial='Condition',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )
    logic = forms.ChoiceField(
        label='Логика',
        choices=CONDITION_LOGIC,
        initial='AND',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    left = forms.CharField(
        label='Поле 1',
        help_text='например {{ amount }} или значение',
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )
    operator = forms.ChoiceField(
        label='Оператор',
        choices=CONDITION_OPERATORS,
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    right = forms.CharField(
        label='Значение 1',
        required=False,
        help_text='пусто для оператора exists',
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )
    left2 = forms.CharField(
        label='Поле 2 (необязательно)',
        required=False,
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )
    operator2 = forms.ChoiceField(
        label='Оператор 2',
        choices=CONDITION_OPERATORS,
        required=False,
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    right2 = forms.CharField(
        label='Значение 2',
        required=False,
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )


class HTTPNodeForm(OnErrorMixin):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='http')
    name = forms.CharField(
        label='Название',
        initial='HTTP Request',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )
    method = forms.ChoiceField(
        label='Метод',
        choices=HTTP_METHODS,
        initial='POST',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    url = forms.URLField(
        label='URL',
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )
    headers = forms.CharField(
        label='Заголовки',
        required=False,
        help_text='JSON-объект, поддерживает {{ переменные }}',
        widget=forms.Textarea(attrs={'class': MONO_CLASS, 'rows': 3}),
    )
    query_params = forms.CharField(
        label='Query параметры',
        required=False,
        help_text='JSON-объект',
        widget=forms.Textarea(attrs={'class': MONO_CLASS, 'rows': 2}),
    )
    body = forms.CharField(
        label='Тело запроса',
        required=False,
        help_text='JSON-объект или текст, поддерживает {{ переменные }}',
        widget=forms.Textarea(attrs={'class': MONO_CLASS, 'rows': 5}),
    )
    max_attempts = forms.IntegerField(
        label='Попытки (retry)',
        min_value=1,
        max_value=5,
        initial=1,
        help_text='Сколько раз повторить при временной ошибке (5xx, сеть)',
        widget=forms.NumberInput(attrs={'class': INPUT_CLASS}),
    )
    backoff_base = forms.IntegerField(
        label='Базовая задержка (сек)',
        min_value=0,
        max_value=60,
        initial=5,
        help_text='Экспоненциальный backoff: 5, 15, 45…',
        widget=forms.NumberInput(attrs={'class': INPUT_CLASS}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['on_error'].initial = 'retry'


class TelegramNodeForm(OnErrorMixin):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='telegram')
    name = forms.CharField(
        label='Название',
        initial='Telegram',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )
    connection_id = forms.ChoiceField(
        label='Подключение',
        required=False,
        help_text='Сохранённое подключение из раздела «Подключения»',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    secret_id = forms.ChoiceField(
        label='Секрет (старый формат)',
        required=False,
        help_text='Сохранённый токен — шифруется и никогда не показывается',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    new_token = forms.CharField(
        label='Или новый Bot Token',
        required=False,
        help_text='От @BotFather. Будет сохранён в зашифрованном виде',
        widget=forms.TextInput(attrs={'class': MONO_CLASS, 'placeholder': '123456:ABC...'}),
    )
    chat_id = forms.CharField(
        label='Chat ID',
        widget=forms.TextInput(attrs={'class': MONO_CLASS}),
    )
    message = forms.CharField(
        label='Сообщение',
        help_text='Поддерживает {{ переменные }}',
        widget=forms.Textarea(attrs={'class': MONO_CLASS, 'rows': 6}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            connection_choices = [('', '— выберите подключение —')]
            connection_choices += [
                (c.pk, f'{c.name} (Telegram)')
                for c in Connection.objects.filter(owner=user, connection_type='telegram')
            ]
            self.fields['connection_id'].choices = connection_choices
            secret_choices = [('', '— выберите сохранённый секрет —')]
            secret_choices += [
                (s.pk, f'{s.name} ({s.masked_value})')
                for s in Secret.objects.filter(owner=user)
            ]
            self.fields['secret_id'].choices = secret_choices


class TransformNodeForm(OnErrorMixin):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='transform')
    name = forms.CharField(
        label='Название',
        initial='JSON Transform',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )
    mapping = forms.CharField(
        label='Mapping (JSON)',
        help_text='Целевая структура с {{ переменными }}. Пример: {"name": "{{ first_name }}", "amount": "{{ price }}"}',
        widget=forms.Textarea(attrs={'class': MONO_CLASS, 'rows': 8}),
    )


def get_node_form_class(node_type):
    mapping = {
        'webhook': WebhookNodeForm,
        'condition': ConditionNodeForm,
        'http': HTTPNodeForm,
        'telegram': TelegramNodeForm,
        'transform': TransformNodeForm,
    }
    return mapping.get(node_type)


def parse_json_field(raw, field_label):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value
    except json.JSONDecodeError as exc:
        raise ValueError(f'Неверный JSON в поле «{field_label}»: {exc}')