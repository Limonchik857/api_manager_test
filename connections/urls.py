from django.urls import path

from . import views

urlpatterns = [
    path('', views.connection_list, name='connections'),
    path('create/', views.connection_create, name='connection_create'),
    path('<int:connection_id>/delete/', views.connection_delete, name='connection_delete'),
]