from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # Câblage des signaux (post_save Institution → auto-fetch logo).
        from accounts import signals  # noqa: F401
