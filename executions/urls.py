from django.urls import path

from . import views

urlpatterns = [
    path('', views.execution_list, name='executions'),
    path('<int:execution_id>/', views.execution_detail, name='execution_detail'),
]