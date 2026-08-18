from django.urls import path

from . import views

urlpatterns = [
    path('', views.template_list, name='templates'),
    path('<int:template_id>/use/', views.use_template, name='use_template'),
]