"""
accounts/migrations/0011_account_iban.py

Ajoute Account.iban — identifiant IBAN universel au niveau du compte parent.

Pourquoi ?
    UBS exporte des relevés d'épargne (SavingsAccount) qui contiennent un IBAN
    en ligne 2. En stockant l'IBAN sur Account directement, le resolver peut faire
    Account.objects.get(iban=identifier) sans connaître le sous-type (checking/savings).
    CheckingAccount.iban reste intact pour rétrocompatibilité.

Data migration :
    Copie CheckingAccount.iban → Account.iban pour tous les comptes existants.
    Idempotente : ne touche que les rows où Account.iban IS NULL et CheckingAccount.iban
    est renseigné.
"""

from django.db import migrations, models


def copy_iban_to_account(apps, schema_editor):
    """
    Copie CheckingAccount.iban vers Account.iban pour les comptes existants.

    On passe par apps.get_model() (pas l'import direct de la classe) pour avoir
    les versions "figées" des modèles au moment de cette migration — règle Django.
    """
    CheckingAccount = apps.get_model("accounts", "CheckingAccount")
    for ca in CheckingAccount.objects.select_related("account").all():
        if ca.iban and not ca.account.iban:
            ca.account.iban = ca.iban
            ca.account.save(update_fields=["iban"])


def noop(apps, schema_editor):
    """Reverse : on ne supprime pas les données copiées (opération non destructive)."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_checkingaccount_iban_optional"),
    ]

    operations = [
        # 1. Ajout du champ
        migrations.AddField(
            model_name="account",
            name="iban",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=34,
                null=True,
                unique=True,
            ),
        ),
        # 2. Data migration : CheckingAccount.iban → Account.iban
        migrations.RunPython(copy_iban_to_account, reverse_code=noop),
    ]
