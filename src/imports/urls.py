from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.import_upload, name="upload"),
    path("confirm/", views.import_confirm, name="confirm"),
    path("create-account/", views.import_create_account, name="create_account"),
    path("<int:pk>/detail/", views.import_log_detail, name="log_detail"),
    path("<int:pk>/delete/", views.import_log_delete, name="log_delete"),
]
