"""
Data migration — backfill Category.owner / SubCategory.owner (issue #137).

Règle de reprise des données existantes :
    - is_system=True  → owner reste NULL (catégorie partagée). C'est déjà l'état
      par défaut après l'AddField (0016), donc rien à faire pour ces lignes.
    - is_system=False → catégorie PERSO créée avant l'arrivée du champ owner.
      Elle DOIT appartenir à un user réel, sinon .for_user() la rendrait visible
      par tout le monde (owner NULL = partagée). On l'attribue au super-utilisateur
      (en prod : Emmanuel). À défaut de superuser, au premier user créé.

Pourquoi le superuser et pas un email hardcodé ?
    Hardcoder "emmanuel@..." rendrait la migration dépendante d'une donnée prod
    précise et casserait en CI / sur une base fraîche. Le superuser est le bon
    proxy stable d'« Emmanuel » sur cette base mono-utilisateur.

Fail-safe : base sans aucun user (ex. CI vierge) → no-op, on laisse owner NULL
plutôt que de faire planter le deploy. reverse = remettre owner NULL partout
(on ne peut pas distinguer après coup les perso backfillées des perso futures,
mais la reverse ne sert qu'au rollback immédiat de cette migration).
"""

from django.db import migrations


def backfill_owner(apps, schema_editor):
    Category = apps.get_model("transactions", "Category")
    SubCategory = apps.get_model("transactions", "SubCategory")
    User = apps.get_model("users", "CustomUser")

    # Super-utilisateur d'abord (Emmanuel en prod), sinon le premier user créé.
    owner = User.objects.filter(is_superuser=True).order_by("pk").first()
    if owner is None:
        owner = User.objects.order_by("pk").first()
    if owner is None:
        # Base sans user (CI vierge) : aucune perso à attribuer → no-op.
        return

    # Seules les catégories PERSO existantes sont réattribuées ; les système
    # restent owner NULL (partagées).
    Category.objects.filter(is_system=False, owner__isnull=True).update(owner=owner)
    SubCategory.objects.filter(is_system=False, owner__isnull=True).update(owner=owner)


def reverse_backfill(apps, schema_editor):
    # Rollback : on retire l'owner posé par cette migration. On ne peut pas savoir
    # a posteriori lesquelles étaient déjà perso vs système, mais avant 0016 le
    # champ n'existait pas — remettre NULL est l'état cohérent pré-migration.
    Category = apps.get_model("transactions", "Category")
    SubCategory = apps.get_model("transactions", "SubCategory")
    Category.objects.filter(is_system=False).update(owner=None)
    SubCategory.objects.filter(is_system=False).update(owner=None)


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0016_category_subcategory_owner"),
    ]

    operations = [
        # reverse_code explicite (SR-004) : la migration est réversible.
        migrations.RunPython(backfill_owner, reverse_code=reverse_backfill),
    ]
