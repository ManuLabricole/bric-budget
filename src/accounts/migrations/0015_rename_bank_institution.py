"""Rename Bank → Institution + Account.bank → Account.institution.

Écrite à la main : makemigrations détecte les renames en mode interactif
(« Did you rename...? [y/N] »), non disponible ici. RenameModel et RenameField
préservent les données (renommage de table/colonne, aucune perte).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_account_members_data"),
        # Le rename doit s'exécuter APRÈS les data-migrations transactions qui
        # filtrent sur account__bank__slug (0009 CIC, 0010 UBS) — sinon, sur une
        # DB fraîche, le graphe placerait le rename avant et leur état historique
        # verrait déjà `institution` → FieldError 'bank__slug'.
        ("transactions", "0010_rehash_ubs_transactions"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Bank",
            new_name="Institution",
        ),
        migrations.RenameField(
            model_name="account",
            old_name="bank",
            new_name="institution",
        ),
        migrations.AlterModelOptions(
            name="institution",
            options={
                "ordering": ["name"],
                "verbose_name": "institution",
                "verbose_name_plural": "institutions",
            },
        ),
        migrations.AlterModelOptions(
            name="account",
            options={
                "ordering": ["institution__name", "name"],
                "verbose_name": "account",
                "verbose_name_plural": "accounts",
            },
        ),
    ]
