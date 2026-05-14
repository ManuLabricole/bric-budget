"""
Migration de données : assigne Emmanuel (emmanuel.barriol@gmail.com) comme membre
de tous les comptes existants.

Pourquoi une migration de données séparée (pas dans 0013) ?
    Bonne pratique Django : séparer les migrations de schéma (DDL) des migrations
    de données (DML). La migration de schéma (0013) crée la table M2M. Cette
    migration (0014) la remplit. Si la data migration échoue (user inexistant
    en env de test), on peut la rejouer sans retoucher le schéma.

Comportement si l'user n'existe pas :
    On ne plante pas (try/except). Environnements de test et CI n'ont pas de seed
    utilisateur — la data migration est un no-op dans ce cas.
    En prod : l'user Emmanuel existe → tous les comptes lui sont assignés.
"""

from django.db import migrations


def add_emmanuel_to_all_accounts(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    User = apps.get_model("users", "CustomUser")
    try:
        emmanuel = User.objects.get(email="emmanuel.barriol@gmail.com")
    except User.DoesNotExist:
        # Env de test ou CI sans seed — ne rien faire
        return
    for account in Account.objects.all():
        account.members.add(emmanuel)


def remove_emmanuel_from_all_accounts(apps, schema_editor):
    """Reverse migration : vide la table M2M (pas de suppression du compte)."""
    Account = apps.get_model("accounts", "Account")
    for account in Account.objects.all():
        account.members.clear()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_account_members"),
    ]

    operations = [
        migrations.RunPython(
            add_emmanuel_to_all_accounts,
            reverse_code=remove_emmanuel_from_all_accounts,
        ),
    ]
