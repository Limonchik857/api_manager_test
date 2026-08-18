import json

from django import forms

from vault.models import Secret
from .models import Workflow, WorkflowNode

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

INPUT_CLASS = 'form-input'
MONO_CLASS = 'form-input mono'


class WorkflowForm(forms.ModelForm):
    class Meta:
        model = Workflow
        fields = ('name', 'description', 'is_active')
        labels = {'name': 'Название', 'description': 'Описание', 'is_active': 'Активен'}
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Например: Уведомление о заказе'}),
            'description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 3, 'placeholder': 'Необязательное описание'}),
        }


class WebhookNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='webhook')
    name = forms.CharField(
        label='Название',
        initial='Webhook',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )


class ConditionNodeForm(forms.Form):
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


class HTTPNodeForm(forms.Form):
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
        help_text='Сколько раз повторить при ошибке',
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


class TelegramNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='telegram')
    name = forms.CharField(
        label='Название',
        initial='Telegram',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS}),
    )
    secret_id = forms.ChoiceField(
        label='Секрет (Bot Token)',
        required=False,
        help_text='Сохранённый токен — шифруется и никогда не показывается',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )
    new_token = forms.CharField(
        label='Или введите новый Bot Token',
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
            choices = [('', '— выберите сохранённый секрет —')]
            choices += [(s.pk, f'{s.name} ({s.masked_value})') for s in Secret.objects.filter(owner=user)]
            self.fields['secret_id'].choices = choices


class TransformNodeForm(forms.Form):
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