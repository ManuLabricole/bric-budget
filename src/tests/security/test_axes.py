import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_login_lockout_after_5_failures(client, django_user_model):
    django_user_model.objects.create_user(email="lockout@test.com", password="correct")
    url = reverse("login")
    for _ in range(5):
        client.post(url, {"username": "lockout@test.com", "password": "wrong"})
    response = client.post(url, {"username": "lockout@test.com", "password": "wrong"})
    assert response.status_code == 429  # axes retourne 429 Too Many Requests


@pytest.mark.django_db
def test_login_succeeds_before_lockout(client, django_user_model):
    django_user_model.objects.create_user(email="ok@test.com", password="correct")
    url = reverse("login")
    for _ in range(4):
        client.post(url, {"username": "ok@test.com", "password": "wrong"})
    response = client.post(url, {"username": "ok@test.com", "password": "correct"})
    assert response.status_code == 302
