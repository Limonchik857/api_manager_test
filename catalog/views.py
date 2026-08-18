from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from usage.services import LimitExceeded
from .models import WorkflowTemplate
from .services import create_workflow_from_template


@login_required
def template_list(request):
    templates = WorkflowTemplate.objects.filter(is_active=True)
    return render(request, 'catalog/list.html', {'templates': templates})


@require_POST
@login_required
def use_template(request, template_id):
    template = get_object_or_404(WorkflowTemplate, pk=template_id, is_active=True)
    try:
        workflow = create_workflow_from_template(request.user, template)
    except LimitExceeded as exc:
        messages.error(request, str(exc))
        return redirect('templates')
    messages.success(
        request,
        f'Сценарий «{workflow.name}» создан из шаблона. '
        f'Подключите Telegram и настройте расписание.',
    )
    return redirect('workflow_edit', workflow_id=workflow.pk)