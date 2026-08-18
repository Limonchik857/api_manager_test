from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render

from .forms import (
    LoginForm,
    RegisterForm,
    StudioPasswordResetForm,
    StudioSetPasswordForm,
)


def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'landing.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form})


class StudioLoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm


class StudioLogoutView(auth_views.LogoutView):
    next_page = 'landing'


class StudioPasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset.html'
    form_class = StudioPasswordResetForm
    subject_template_name = 'accounts/password_reset_subject.txt'
    email_template_name = 'accounts/password_reset_email.txt'
    success_url = '/accounts/password-reset/done/'


class StudioPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    form_class = StudioSetPasswordForm
    success_url = '/accounts/password-reset/complete/'