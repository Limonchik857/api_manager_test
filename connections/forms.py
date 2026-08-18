from django import forms

from .models import Connection


class ConnectionForm(forms.ModelForm):
    token = forms.CharField(
        label='Токен / API Key',
        help_text='Будет зашифрован и никогда не будет показан снова',
        widget=forms.TextInput(attrs={'class': 'form-input mono'}),
    )

    class Meta:
        model = Connection
        fields = ('name', 'connection_type')
        labels = {'name': 'Название', 'connection_type': 'Тип'}
        widgets = {
            'name': forms.TextInput(
                attrs={'class': 'form-input', 'placeholder': 'Например: Мой Telegram бот'}
            ),
            'connection_type': forms.Select(attrs={'class': 'form-input'}),
        }