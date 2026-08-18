from django import forms

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
HTTP_METHODS = [
    ('GET', 'GET'),
    ('POST', 'POST'),
    ('PUT', 'PUT'),
    ('PATCH', 'PATCH'),
    ('DELETE', 'DELETE'),
]


class WorkflowForm(forms.ModelForm):
    class Meta:
        model = Workflow
        fields = ('name', 'description', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. New Order Notification'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Optional description'}),
        }


class WebhookNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='webhook')
    name = forms.CharField(
        label='Name',
        initial='Webhook',
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )


class ConditionNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='condition')
    name = forms.CharField(
        label='Name',
        initial='Condition',
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )
    left = forms.CharField(
        label='Field',
        help_text='e.g. {{ amount }} or a literal value',
        widget=forms.TextInput(attrs={'class': 'form-input mono'}),
    )
    operator = forms.ChoiceField(
        choices=CONDITION_OPERATORS,
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    right = forms.CharField(
        label='Value',
        required=False,
        help_text='Empty when using "exists"',
        widget=forms.TextInput(attrs={'class': 'form-input mono'}),
    )


class HTTPNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='http')
    name = forms.CharField(
        label='Name',
        initial='HTTP Request',
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )
    method = forms.ChoiceField(
        choices=HTTP_METHODS,
        initial='POST',
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    url = forms.URLField(
        label='URL',
        widget=forms.TextInput(attrs={'class': 'form-input mono'}),
    )
    headers = forms.CharField(
        label='Headers',
        required=False,
        help_text='JSON object, supports {{ variables }}',
        widget=forms.Textarea(attrs={'class': 'form-input mono', 'rows': 3}),
    )
    query_params = forms.CharField(
        label='Query Parameters',
        required=False,
        help_text='JSON object',
        widget=forms.Textarea(attrs={'class': 'form-input mono', 'rows': 2}),
    )
    body = forms.CharField(
        label='Body',
        required=False,
        help_text='JSON object or raw text, supports {{ variables }}',
        widget=forms.Textarea(attrs={'class': 'form-input mono', 'rows': 5}),
    )


class TelegramNodeForm(forms.Form):
    node_type = forms.CharField(widget=forms.HiddenInput, initial='telegram')
    name = forms.CharField(
        label='Name',
        initial='Telegram',
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )
    bot_token = forms.CharField(
        label='Bot Token',
        help_text='From @BotFather',
        widget=forms.TextInput(attrs={'class': 'form-input mono', 'placeholder': '123456:ABC...'}),
    )
    chat_id = forms.CharField(
        label='Chat ID',
        widget=forms.TextInput(attrs={'class': 'form-input mono'}),
    )
    message = forms.CharField(
        label='Message',
        help_text='Supports {{ variables }} from previous steps',
        widget=forms.Textarea(attrs={'class': 'form-input mono', 'rows': 6}),
    )


def get_node_form_class(node_type):
    mapping = {
        'webhook': WebhookNodeForm,
        'condition': ConditionNodeForm,
        'http': HTTPNodeForm,
        'telegram': TelegramNodeForm,
    }
    return mapping.get(node_type)