"""
#201 — BudgetTarget.owner : un objectif par (user, catégorie).

Avant : OneToOneField(Category) → un seul objectif GLOBAL par catégorie. Sur une
catégorie SYSTÈME (partagée), l'objectif était unique et partagé/écrasable entre TOUS
les users (write cross-user). On ajoute `owner` + UniqueConstraint(owner, category).

Dance en 3 temps (champ non-null sur table existante) :
  1. AddField owner null=True  (temporaire, pour pouvoir backfiller)
  2. RunPython backfill         (owner = category.owner ; purge des objectifs sur cats
                                 système = ambigus/partagés, pré-launch → pas de perte réelle)
  3. AlterField owner null=False
puis OneToOne→FK + contrainte (owner, category).
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_owner(apps, schema_editor):
    BudgetTarget = apps.get_model("transactions", "BudgetTarget")
    for target in BudgetTarget.objects.select_related("category").all():
        cat_owner_id = target.category.owner_id
        if cat_owner_id is None:
            # Objectif sur une catégorie SYSTÈME : partagé entre users (le bug corrigé),
            # impossible à attribuer à un user précis → purge. Pré-launch : les users
            # re-fixeront leur objectif. (Décision : purge plutôt que réassignation.)
            target.delete()
        else:
            target.owner_id = cat_owner_id
            target.save(update_fields=["owner"])


def reverse_backfill(apps, schema_editor):
    # Irréversible proprement (les lignes purgées ne sont pas restaurées). On remet owner
    # à NULL pour permettre le rollback du schéma. ⚠️ Le retour OneToOne échouera s'il
    # existe désormais 2 objectifs (multi-user) sur une même catégorie — rollback best-effort.
    BudgetTarget = apps.get_model("transactions", "BudgetTarget")
    BudgetTarget.objects.update(owner=None)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        (
            "transactions",
            "0021_remove_subcategory_subcategory_category_name_uniq_and_more",
        ),
    ]

    operations = [
        # 1. owner temporairement nullable pour le backfill
        migrations.AddField(
            model_name="budgettarget",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="budget_targets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 2. backfill owner depuis category.owner + purge des targets système
        migrations.RunPython(backfill_owner, reverse_backfill),
        # 3. owner devient obligatoire
        migrations.AlterField(
            model_name="budgettarget",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="budget_targets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # OneToOne → FK (lève l'unique implicite sur category)
        migrations.AlterField(
            model_name="budgettarget",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="budget_targets",
                to="transactions.category",
            ),
        ),
        # Unicité scopée : un objectif par (user, catégorie)
        migrations.AddConstraint(
            model_name="budgettarget",
            constraint=models.UniqueConstraint(
                fields=["owner", "category"],
                name="budgettarget_owner_category_uniq",
            ),
        ),
    ]
