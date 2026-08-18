from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from usage.services import get_usage_summary
from .forms import ConnectionForm
from .models import Connection
from .services import create_connection


@login_required
def connection_list(request):
    connections = request.user.connections.prefetch_related('secret')
    return render(request, 'connections/list.html', {
        'connections': connections,
        'usage': get_usage_summary(request.user),
    })


@login_required
def connection_create(request):
    if request.method == 'POST':
        form = ConnectionForm(request.POST)
        if form.is_valid():
            connection = create_connection(
                request.user,
                form.cleaned_data['name'],
                form.cleaned_data['connection_type'],
                form.cleaned_data['token'],
            )
            messages.success(request, f'Подключение «{connection.name}» создано')
            return redirect('connections')
    else:
        form = ConnectionForm()
    return render(request, 'connections/create.html', {'form': form})


@require_POST
@login_required
def connection_delete(request, connection_id):
    connection = get_object_or_404(Connection, pk=connection_id, owner=request.user)
    name = connection.name
    connection.delete()
    messages.success(request, f'Подключение «{name}» удалено')
    return redirect('connections')