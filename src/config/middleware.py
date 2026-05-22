"""
config/middleware.py — Middlewares custom BricBudget.

PermissionsPolicyMiddleware : injecte le header Permissions-Policy sur chaque réponse.
Django SecurityMiddleware ne gère pas ce header nativement — on l'ajoute ici.
La valeur est lue depuis settings.PERMISSIONS_POLICY (défini uniquement en prod).
"""

from django.conf import settings


class PermissionsPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = getattr(settings, "PERMISSIONS_POLICY", None)

    def __call__(self, request):
        response = self.get_response(request)
        if self.policy:
            response["Permissions-Policy"] = self.policy
        return response
