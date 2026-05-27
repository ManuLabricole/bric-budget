from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("comptes/nouveau/", views.account_new, name="account_new"),
]
