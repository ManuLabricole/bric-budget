"""
tests/factories/users.py — Factory pour le modèle utilisateur (CustomUser).

Pourquoi une factory plutôt que User.objects.create_user(...) recopié partout ?
------------------------------------------------------------------------------
Avant #194, chaque conftest recréait son user à la main avec un email codé en dur
(`usera@budget.ch`, `test@bricbudget.ch`, `patrimoine@test.ch`...). factory_boy
centralise la construction : un test déclare `user = UserFactory()` (email auto-séquencé,
donc unique) ou `UserFactory(email="...")` quand l'email exact compte (tests d'auth).
"""

import factory
from django.contrib.auth import get_user_model


class UserFactory(factory.django.DjangoModelFactory):
    """
    CustomUser minimal — email-based login (pas de username).

    On passe par le manager `create_user(email, password)` (et non l'`objects.create`
    par défaut de factory_boy) parce que c'est exactement ce que faisaient les fixtures
    historiques : `create_user` NORMALISE l'email, HASHE le mot de passe (set_password)
    et SAUVEGARDE en une fois. Un mot de passe stocké en clair casserait
    `client.login(password=...)`. D'où l'override de `_create`.

    Pas de `django_get_or_create` : il court-circuiterait `_create` (factory_boy
    appelle `manager.get_or_create`), donc le mot de passe NE serait PAS hashé.
    L'unicité est déjà garantie par la Sequence sur l'email ; les fixtures qui veulent
    un email précis le passent explicitement (même contrat que les anciennes fixtures,
    qui n'avaient pas de get_or_create non plus).
    """

    class Meta:
        model = get_user_model()

    email = factory.Sequence(lambda n: f"user{n}@budget.ch")
    password = "pass"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Construit via create_user → email normalisé + mot de passe hashé + save."""
        manager = cls._get_manager(model_class)
        password = kwargs.pop("password", None)
        return manager.create_user(*args, password=password, **kwargs)
