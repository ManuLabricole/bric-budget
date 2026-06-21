"""
Data migration — backfill CategorizationRule.owner (issue #145).

Règle de reprise des données existantes :
    L'app a vécu en mono-utilisateur jusqu'ici → TOUTES les règles existantes
    appartiennent de fait à Emmanuel. Sans owner, elles seraient owner NULL =
    « système / partagé » après l'AddField (0019), donc visibles et modifiables
    par n'importe quel futur user via .for_user() → c'est précisément le trou
    IDOR qu'on ferme. On les attribue donc au super-utilisateur (Emmanuel en
    prod), à défaut au premier user créé.

Pourquoi le superuser et pas un email hardcodé ?
    Hardcoder "emmanuel@..." rendrait la migration dépendante d'une donnée prod
    précise et casserait en CI / sur une base fraîche. Le superuser est le bon
    proxy stable d'« Emmanuel » sur cette base mono-utilisateur (même raisonnement
    que 0017_backfill_category_owner).

Différence avec Category : il n'y a PAS de notion de règle « système » à préserver
ici (≠ catégories is_system). Toutes les règles existantes sont des préférences
perso → toutes réattribuées à l'owner. Une seed de règles système, si elle arrive
un jour, posera owner=NULL explicitement et restera donc partagée.

Fail-safe : base sans aucun user (ex. CI vierge) → no-op, on laisse owner NULL
plutôt que de faire planter le deploy. reverse = remettre owner NULL partout
(rollback immédiat de cette migration).
"""

from django.db import migrations


def backfill_owner(apps, schema_editor):
    Rule = apps.get_model("transactions", "CategorizationRule")
    User = apps.get_model("users", "CustomUser")

    # Super-utilisateur d'abord (Emmanuel en prod), sinon le premier user créé.
    owner = User.objects.filter(is_superuser=True).order_by("pk").first()
    if owner is None:
        owner = User.objects.order_by("pk").first()
    if owner is None:
        # Base sans user (CI vierge) : aucune règle à attribuer → no-op.
        return

    Rule.objects.filter(owner__isnull=True).update(owner=owner)


def reverse_backfill(apps, schema_editor):
    # Rollback : on retire l'owner posé par cette migration. Avant 0019 le champ
    # n'existait pas — remettre NULL est l'état cohérent pré-migration.
    Rule = apps.get_model("transactions", "CategorizationRule")
    Rule.objects.update(owner=None)


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0019_categorizationrule_owner"),
    ]

    operations = [
        # reverse_code explicite (SR-004) : la migration est réversible.
        migrations.RunPython(backfill_owner, reverse_code=reverse_backfill),
    ]
