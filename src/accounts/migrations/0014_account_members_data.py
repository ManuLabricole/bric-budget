"""
Migration de données : assigne tous les utilisateurs actifs comme membres
de tous les comptes existants.

Pourquoi une migration de données séparée (pas dans 0013) ?
    Bonne pratique Django : séparer les migrations de schéma (DDL) des migrations
    de données (DML). La migration de schéma (0013) crée la table M2M. Cette
    migration (0014) la remplit. Si la data migration échoue, on peut la rejouer
    sans retoucher le schéma.

Stratégie — assign TOUS les utilisateurs actifs (pas d'email hardcodé) :
    Phase 1 (mono-user) : l'unique user obtient tous les comptes. ✓
    CI / tests          : aucun user → no-op. ✓
    Futur multi-user    : chaque user membre de tous les comptes existants au
                          moment de la migration — à ajuster si nécessaire.

    L'ancienne version ciblait "emmanuel.barriol@gmail.com" (hardcodé).
    Problem : si l'user n'existe pas en prod pour une raison quelconque,
    tous les comptes restent sans membre → for_user() retourne 0 résultat
    et toutes les données deviennent inaccessibles silencieusement.
"""

from django.db import migrations


def assign_all_users_to_all_accounts(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    User = apps.get_model("users", "CustomUser")
    users = list(User.objects.filter(is_active=True))
    if not users:
        # Env de test ou CI sans seed — ne rien faire
        return
    for account in Account.objects.all():
        account.members.set(users)


def remove_all_users_from_all_accounts(apps, schema_editor):
    """Reverse migration : vide la table M2M (pas de suppression des comptes)."""
    Account = apps.get_model("accounts", "Account")
    for account in Account.objects.all():
        account.members.clear()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_account_members"),
    ]

    operations = [
        migrations.RunPython(
            assign_all_users_to_all_accounts,
            reverse_code=remove_all_users_from_all_accounts,
        ),
    ]
