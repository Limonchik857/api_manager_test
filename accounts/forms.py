from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.contrib.auth.models import User

INPUT_CLASS = 'form-input'


class StudioPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'class': INPUT_CLASS, 'placeholder': 'you@example.com'}),
    )


class StudioSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = 'Новый пароль'
        self.fields['new_password2'].label = 'Повторите новый пароль'
        self.fields['new_password1'].widget.attrs.update({'class': INPUT_CLASS})
        self.fields['new_password2'].widget.attrs.update({'class': INPUT_CLASS})


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=False,
        label='Email',
        widget=forms.EmailInput(attrs={'class': INPUT_CLASS, 'placeholder': 'you@example.com'}),
    )

    class Meta:
        model = User
        fields = ('username', 'email')
        labels = {'username': 'Логин'}
        widgets = {
            'username': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Например: alex'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].label = 'Пароль'
        self.fields['password2'].label = 'Повторите пароль'
        self.fields['password1'].widget.attrs.update({'class': INPUT_CLASS, 'placeholder': 'Минимум 8 символов'})
        self.fields['password2'].widget.attrs.update({'class': INPUT_CLASS, 'placeholder': 'Ещё раз'})


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Логин',
        widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'autofocus': True, 'placeholder': 'Ваш логин'}),
    )
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Ваш пароль'}),
    )