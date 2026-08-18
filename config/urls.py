from django.contrib import admin
from django.urls import include, path

from accounts.views import landing
from workflows.views import dashboard, webhook_receive

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', landing, name='landing'),
    path('dashboard/', dashboard, name='dashboard'),
    path('webhooks/<str:token>/', webhook_receive, name='webhook_receive'),
    path('accounts/', include('accounts.urls')),
    path('workflows/', include('workflows.urls')),
    path('executions/', include('executions.urls')),
]