from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetView
from django.shortcuts import redirect, render

from .forms import RegisterForm


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


class StudioLoginView(LoginView):
    template_name = 'accounts/login.html'


class StudioLogoutView(LogoutView):
    next_page = 'landing'


class StudioPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset.html'
    subject_template_name = 'accounts/password_reset_subject.txt'
    email_template_name = 'accounts/password_reset_email.txt'
    success_url = '/accounts/password-reset/done/'