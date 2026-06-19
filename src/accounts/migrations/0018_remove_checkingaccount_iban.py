"""
accounts/migrations/0018_remove_checkingaccount_iban.py

Consolidation IBAN (#82) — suppression du champ legacy CheckingAccount.iban.

Account.iban est désormais la source de vérité unique (champ universel checking +
savings, utilisé par le resolver d'import + identité décidée le 2026-06-10). La 0011
avait introduit Account.iban et recopié CheckingAccount.iban → Account.iban. La PR C
avait réintroduit une double-écriture, supprimée ici en repointant tous les writers.

Ordre des opérations :
    1. Filet de sécurité (RunPython réversible, SR-004) : recopie tout
       CheckingAccount.iban résiduel vers Account.iban là où Account.iban IS NULL,
       au cas où des rows auraient été écrites sur CheckingAccount seul depuis la 0011
       (la double-écriture de la PR C, ou des seeds qui n'écrivaient que CheckingAccount).
    2. RemoveField CheckingAccount.iban.

Reverse : Django recrée le champ (RemoveField est auto-réversible) ; le RunPython a
un reverse qui recopie Account.iban → CheckingAccount.iban pour les comptes courants,
de sorte qu'un rollback restaure une donnée cohérente sur le champ legacy.
"""

from django.db import migrations, models


def backfill_account_iban(apps, schema_editor):
    """
    Filet de sécurité : CheckingAccount.iban → Account.iban là où Account.iban IS NULL.

    Idempotente. apps.get_model() pour la version figée des modèles (règle Django).
    """
    CheckingAccount = apps.get_model("accounts", "CheckingAccount")
    for ca in CheckingAccount.objects.select_related("account").all():
        if ca.iban and not ca.account.iban:
            ca.account.iban = ca.iban
            ca.account.save(update_fields=["iban"])


def restore_checkingaccount_iban(apps, schema_editor):
    """
    Reverse : Account.iban → CheckingAccount.iban pour les comptes courants.

    Exécuté APRÈS que RemoveField a (en reverse = AddField) recréé la colonne.
    Restaure une donnée cohérente sur le champ legacy en cas de rollback.
    """
    CheckingAccount = apps.get_model("accounts", "CheckingAccount")
    for ca in CheckingAccount.objects.select_related("account").all():
        if ca.account.iban and not ca.iban:
            ca.iban = ca.account.iban
            ca.save(update_fields=["iban"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_institution_category"),
    ]

    operations = [
        # 1. Filet de sécurité avant suppression (reverse = restauration legacy).
        migrations.RunPython(
            backfill_account_iban, reverse_code=restore_checkingaccount_iban
        ),
        # 2. Suppression du champ legacy. RemoveField est auto-réversible :
        #    le reverse re-AddField la colonne (avec ses contraintes d'origine),
        #    et le RunPython ci-dessus la re-remplit ensuite.
        migrations.RemoveField(
            model_name="checkingaccount",
            name="iban",
        ),
    ]
