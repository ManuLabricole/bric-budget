"""
demo/admin_views.py — page « Données de démo » dans le panel admin (#118).

Donne un accès facile au seed/reset de démo depuis l'admin (l'ask #118 :
« un accès facile dans le panel admin »). Montée dans config/urls.py sous le
préfixe admin via `admin.site.admin_view` → staff requis. En plus, les actions
sont dev-guardées (refus si DEBUG=False) comme les commandes dev_seed/dev_reset :
seeder/wiper ne doivent jamais tourner en prod par mégarde.

Synchrone (le seed prend quelques secondes) — acceptable pour un outil de dev.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def seed_control(request):
    """GET : état de la démo + boutons. POST : exécute seed/reset (PRG)."""
    if request.method == "POST":
        return _handle_action(request)

    context = {
        **admin.site.each_context(request),
        "title": "Données de démo",
        "demo_debug": settings.DEBUG,
        "demo_status": _demo_status(),
    }
    return TemplateResponse(request, "admin/demo_seed.html", context)


def _handle_action(request):
    """Exécute l'action POST (seed/reset), pose un message, redirige (PRG)."""
    target = redirect(reverse("demo_seed_control"))

    # Dev-guard : même règle que dev_seed/dev_reset — jamais en prod.
    if not settings.DEBUG:
        messages.error(
            request, "Seed/Reset refusés : opération réservée au dev (DEBUG=False)."
        )
        return target

    action = request.POST.get("action")
    try:
        if action == "seed":
            from demo.seeder import seed_demo

            summary = seed_demo(flush=True)
            messages.success(
                request,
                f"Démo seedée : {summary.accounts} comptes · {summary.imports} imports "
                f"· {summary.created} transactions (user {summary.user_email}).",
            )
        elif action == "reset":
            from demo.seeder import reset_demo

            email = reset_demo()
            messages.success(
                request, f"Données de démo supprimées (user {email} conservé)."
            )
        else:
            messages.error(request, f"Action inconnue : {action!r}.")
    except Exception as exc:
        # On remonte l'erreur à l'admin plutôt que de renvoyer un 500.
        logger.exception("demo seed_control: action '%s' a échoué", action)
        messages.error(request, f"Échec de l'action « {action} » : {exc}")

    return target


def _demo_status() -> dict:
    """Compteurs démo pour l'affichage (best effort, None-safe)."""
    from django.contrib.auth import get_user_model

    from accounts.models import Account
    from transactions.models import Transaction

    email = getattr(settings, "DEMO_USER_EMAIL", None)
    user = get_user_model().objects.filter(email=email).first() if email else None
    if user is None:
        return {"exists": False, "user_email": email, "accounts": 0, "transactions": 0}
    return {
        "exists": True,
        "user_email": email,
        "accounts": Account.objects.filter(members=user).count(),
        "transactions": Transaction.objects.filter(account__members=user).count(),
    }
