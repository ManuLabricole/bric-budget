"""
tests/admin/test_admin_smoke.py — filet de fumée sur l'admin + pages d'erreur (#167).

Pourquoi ce fichier ?
---------------------
Deux surfaces de rendu n'étaient JAMAIS exécutées par les tests :

1. **L'admin Django** — 15 `@admin.register` (dont `transactions/admin.py` avec des
   `list_display` *méthodes* : `account_link`, `category_link`, `member_list`…).
   Un `list_display` qui référence un champ renommé, ou une méthode d'affichage qui
   plante, ne lève une `AdminError`/`AttributeError` **qu'à l'ouverture de la page** —
   `check` ne le voit pas. On charge donc, en superuser, la `changelist` ET l'`add`
   de CHAQUE modèle enregistré : un rendu cassé devient un test rouge en CI.

2. **La page 404** — aucun test ne garantissait que 404 = 404.

Pattern calqué (cité) :
    - `tests/commands/test_command_smoke.py` : introspection d'un registre
      (`get_commands()`) + `@pytest.mark.parametrize` sur les items découverts, plus
      un test « le filtre attrape bien quelque chose » (garde anti faux-vert). On
      reprend l'idée sur `django.contrib.admin.site._registry`.
    - `tests/demo/test_admin_seed.py` : fixture LOCALE qui crée un superuser via
      `create_user(is_staff=True, is_superuser=True)` + `client.force_login(...)`.
      Le superuser est créé INLINE ici — on ne touche AUCUN conftest partagé.

Pourquoi `reverse("admin:…")` et pas une URL en dur ?
    Le préfixe admin est lu depuis `.env` (`ADMIN_URL`, cf. config/urls.py) → écrire
    `/admin/…` casserait dès qu'on change la variable. `reverse()` résout le bon
    chemin quel que soit le préfixe configuré.
"""

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import NoReverseMatch, reverse


def _registered_models() -> list[tuple[str, str]]:
    """Liste triée des modèles enregistrés dans l'admin, en (app_label, model_name).

    On lit `admin.site._registry` (dict {Model: ModelAdmin}) au moment de la collecte
    pytest : tous les `admin.py` sont déjà importés via `django.setup()`. Le tuple de
    chaînes (plutôt que la classe) donne des ids de paramétrage lisibles dans la sortie
    pytest (ex. `transactions-transaction`) et sert directement à `reverse()`.
    """
    return sorted(
        (model._meta.app_label, model._meta.model_name or "")
        for model in admin.site._registry
    )


# Calculé à l'import du module de test → la paramétrisation est figée à la collecte.
REGISTERED_MODELS = _registered_models()


@pytest.fixture
def admin_client(db) -> Client:
    """Client authentifié en superuser — accès complet à l'admin.

    Créé INLINE (pas de conftest partagé, owned par une autre issue de la vague).
    `db` car create_user + la session de login touchent la base.
    """
    superuser = get_user_model().objects.create_user(
        email="admin-smoke@bric.test",
        password="pw-Strong-123",  # noqa: S106 (mot de passe de test, pas un secret prod)
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(superuser)
    return client


@pytest.mark.django_db
def test_registry_is_populated():
    """Garde anti faux-vert : si le registre est vide (ou mal introspecté), les tests
    paramétrés ne tourneraient sur RIEN et passeraient en silence. On verrouille la
    présence des modèles cœur avant de faire confiance aux paramétrages."""
    assert ("transactions", "transaction") in REGISTERED_MODELS
    assert ("accounts", "account") in REGISTERED_MODELS
    # Au moins une douzaine de modèles enregistrés (15 attendus) — détecte une chute brutale.
    assert len(REGISTERED_MODELS) >= 12


@pytest.mark.django_db
@pytest.mark.parametrize(
    "app_label,model_name",
    REGISTERED_MODELS,
    ids=[f"{app}-{model}" for app, model in REGISTERED_MODELS],
)
def test_changelist_loads(admin_client, app_label, model_name):
    """GET de la changelist de chaque modèle → 200.

    C'est ICI qu'un `list_display` cassé tombe : la changelist rend chaque colonne
    (y compris les méthodes `account_link`/`category_link`/`member_list`). Sur un
    modèle owned, `OwnedAdminMixin.get_queryset` bascule sur `unscoped()` → la liste
    rend même sans donnée scopée (la base de test est vide, c'est suffisant : Django
    construit et rend l'en-tête + la structure, ce qui résout déjà tous les champs).
    """
    url = reverse(f"admin:{app_label}_{model_name}_changelist")
    response = admin_client.get(url)
    assert response.status_code == 200, (
        f"changelist {app_label}.{model_name} a renvoyé {response.status_code} "
        f"(list_display cassé ? méthode d'affichage en erreur ?)"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "app_label,model_name",
    REGISTERED_MODELS,
    ids=[f"{app}-{model}" for app, model in REGISTERED_MODELS],
)
def test_add_loads(admin_client, app_label, model_name):
    """GET du formulaire d'ajout de chaque modèle → 200 (ou 403 si l'ajout est
    volontairement interdit).

    Charge le ModelForm de l'admin : un `fields`/`fieldsets` qui pointe un champ
    inexistant, un `prepopulated_fields`/`raw_id_fields` mal câblé, ou un widget
    custom cassé fautent ici (500/erreur de template).

    Cas 403 — accepté à dessein : certains admins surchargent `has_add_permission`
    pour retourner False (ex. les modèles de `django-axes` : AccessLog/AccessAttempt/
    AccessFailureLog sont en lecture seule). La route `_add` existe quand même, donc
    `reverse` réussit, mais le GET renvoie 403. C'est le comportement attendu (ajout
    désactivé), pas un rendu cassé → on l'accepte au même titre que 200.

    Cas NoReverseMatch — si un admin ne déclare aucune route `_add`, on skip
    proprement plutôt que de rougir à tort.
    """
    try:
        url = reverse(f"admin:{app_label}_{model_name}_add")
    except NoReverseMatch:
        pytest.skip(f"{app_label}.{model_name} n'expose pas de vue d'ajout")
    response = admin_client.get(url)
    # 200 = formulaire rendu ; 403 = ajout interdit par has_add_permission (légitime).
    # Tout autre code (notamment 500) trahit un ModelForm/fieldset cassé.
    assert response.status_code in (200, 403), (
        f"add {app_label}.{model_name} a renvoyé {response.status_code} "
        f"(ModelForm cassé ? champ/fieldset inexistant ?)"
    )


@pytest.mark.django_db
def test_unknown_url_returns_404(client):
    """Une URL qui ne matche aucun pattern → 404 (et pas un 500/302 silencieux).

    `client` = fixture pytest-django (Django test Client) ; DEBUG est True dans la
    config de test → Django sert sa page 404 technique, mais le STATUT reste 404,
    qui est tout ce qu'on garde ici."""
    response = client.get("/url-inexistante-xyz-167/")
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver", "localhost"])
def test_404_uses_custom_template(client):
    """En prod (DEBUG=False), une 404 doit rendre NOTRE 404.html, pas la page
    technique Django.

    Django sélectionne automatiquement le `404.html` à la racine de
    TEMPLATES['DIRS'] dès que DEBUG=False — c'est pourquoi on n'a PAS besoin de
    handler404 custom. On vérifie le statut ET un marqueur propre à notre template
    (le code d'erreur stylé + le bouton de retour) pour prouver que c'est bien le
    nôtre qui est servi."""
    response = client.get("/url-inexistante-xyz-167/")
    assert response.status_code == 404
    body = response.content.decode()
    assert "ERREUR 404" in body
    assert "Retour à l'accueil" in body


def test_500_template_renders_standalone():
    """Le 500.html doit pouvoir être rendu SANS contexte ni context processors.

    Le handler500 par défaut de Django rend ce template avec un contexte vide (on
    gère déjà une exception → tout ce qui pourrait re-planter est évité). On
    reproduit cette contrainte : `render_to_string(..., {})` sans request. S'il
    contenait un {% url %}, un {% static %} ou une variable de contexte, ce rendu
    lèverait — c'est la garde qui empêche un 500.html lui-même cassé en prod."""
    html = render_to_string("500.html", {})
    assert "ERREUR 500" in html
    assert "Retour à l'accueil" in html
