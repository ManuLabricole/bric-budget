from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.import_upload, name="upload"),
    path("<int:pk>/detail/", views.import_log_detail, name="log_detail"),
]
