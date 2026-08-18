from django.urls import path

from . import views

urlpatterns = [
    path('', views.workflow_list, name='workflows'),
    path('create/', views.workflow_create, name='workflow_create'),
    path('import/', views.workflow_import, name='workflow_import'),
    path('<int:workflow_id>/', views.workflow_detail, name='workflow_detail'),
    path('<int:workflow_id>/edit/', views.workflow_edit, name='workflow_edit'),
    path('<int:workflow_id>/schedule/', views.workflow_schedule_update, name='workflow_schedule_update'),
    path('<int:workflow_id>/export/', views.workflow_export, name='workflow_export'),
    path('<int:workflow_id>/versions/', views.workflow_versions, name='workflow_versions'),
    path('<int:workflow_id>/versions/<int:version_number>/restore/', views.workflow_version_restore, name='workflow_version_restore'),
    path('<int:workflow_id>/toggle/', views.workflow_toggle, name='workflow_toggle'),
    path('<int:workflow_id>/delete/', views.workflow_delete, name='workflow_delete'),
    path('<int:workflow_id>/regenerate-webhook/', views.workflow_regenerate_webhook, name='workflow_regenerate_webhook'),
    path('<int:workflow_id>/run-test/', views.workflow_run_test, name='workflow_run_test'),
    path('<int:workflow_id>/nodes/add/<str:node_type>/', views.node_add, name='node_add'),
    path('<int:workflow_id>/nodes/<int:node_id>/edit/', views.node_edit, name='node_edit'),
    path('<int:workflow_id>/nodes/<int:node_id>/delete/', views.node_delete, name='node_delete'),
    path('<int:workflow_id>/nodes/<int:node_id>/move/<str:direction>/', views.node_move, name='node_move'),
]