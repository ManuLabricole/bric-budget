from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.import_upload, name="upload"),
    path("confirm/", views.import_confirm, name="confirm"),
    path("select-account/", views.import_select_account, name="select_account"),
    path(
        "account-picker/",
        views.account_picker_manual,
        name="account_picker_manual",
    ),
    path("set-period/<str:action>/", views.set_period, name="set_period"),
    path(
        "filter-account/<slug:account_ref>/",
        views.toggle_filter_account,
        name="toggle_filter_account",
    ),
    path("<int:pk>/detail/", views.import_log_detail, name="log_detail"),
    path("<int:pk>/delete/", views.import_log_delete, name="log_delete"),
]
