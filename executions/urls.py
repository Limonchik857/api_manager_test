from django.urls import path

from . import views

urlpatterns = [
    path('', views.execution_list, name='executions'),
    path('<int:execution_id>/', views.execution_detail, name='execution_detail'),
    path('<int:execution_id>/replay/', views.execution_replay, name='execution_replay'),
    path(
        '<int:execution_id>/retry-from/<int:node_execution_id>/',
        views.execution_retry_from_node,
        name='execution_retry_from_node',
    ),
]