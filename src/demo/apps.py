"""
demo/apps.py — app de seed/démo pour le développement (#118).

Toujours installée (pour être testable : les tests tournent en DEBUG=False), mais
INERTE en prod : les points d'entrée (commandes dev_seed/dev_reset/dev_generate_fixtures
et les boutons du panel admin) sont gardés par assert_dev_environment(), et l'admin
n'est enregistré que si DEBUG. Aucun modèle persistant (SeedControl est managed=False).
"""

from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "demo"
    verbose_name = "Démo / Seed (dev)"
