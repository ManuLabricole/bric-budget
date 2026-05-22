from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.import_upload, name="upload"),
    path("confirm/", views.import_confirm, name="confirm"),
    path("create-account/", views.import_create_account, name="create_account"),
    path("select-account/", views.import_select_account, name="select_account"),
    path("set-period/<str:action>/", views.set_period, name="set_period"),
    path(
        "filter-account/<int:account_id>/",
        views.toggle_filter_account,
        name="toggle_filter_account",
    ),
    path("<int:pk>/detail/", views.import_log_detail, name="log_detail"),
    path("<int:pk>/delete/", views.import_log_delete, name="log_delete"),
]
