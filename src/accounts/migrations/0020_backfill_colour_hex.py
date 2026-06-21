"""
Data-migration #134 — backfille Account.colour_hex et Institution.colour_hex.

Les comptes/institutions créés AVANT la feature ont colour_hex="". On leur alloue
une couleur stable maintenant, selon la même règle que create_account :

- Comptes : domaine d'allocation = PAR USER (un compte joint = membre de plusieurs
  users compte dans chaque domaine). On parcourt par user, ordre pk (stable et
  reproductible), et on ne touche que les colour_hex vides (idempotent).
- Institutions : domaine global (elles sont seedées/partagées), ordre pk.

`allocate_color` est une fonction PURE (services.colors) sans accès DB → on peut
l'importer directement dans la migration sans risque sur le state historique.
Reverse = remet colour_hex="" (annule proprement le backfill).
"""

from __future__ import annotations

from django.db import migrations

from services.colors import allocate_color


def backfill(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    Institution = apps.get_model("accounts", "Institution")
    User = apps.get_model(*_user_model_label(apps))

    # --- Institutions : domaine global -----------------------------------------
    used_inst = [
        c
        for c in Institution.objects.exclude(colour_hex="").values_list(
            "colour_hex", flat=True
        )
        if c
    ]
    for inst in Institution.objects.filter(colour_hex="").order_by("pk"):
        inst.colour_hex = allocate_color(used_inst)
        inst.save(update_fields=["colour_hex"])
        used_inst.append(inst.colour_hex)

    # --- Comptes : domaine PAR USER --------------------------------------------
    # Pré-charge les couleurs déjà posées par user (comptes non vides), puis alloue
    # pour les comptes vides en parcourant chaque user. Un compte joint est traité
    # une fois par user dont il est membre, ce qui le « réserve » dans chaque domaine.
    used_by_user: dict[int, list[str]] = {}
    for user in User.objects.all().order_by("pk"):
        used_by_user[user.pk] = [
            c
            for c in Account.objects.filter(members=user)
            .exclude(colour_hex="")
            .values_list("colour_hex", flat=True)
            if c
        ]

    # Comptes vides, ordre pk stable. On résout les couleurs déjà prises dans CHAQUE
    # domaine user dont le compte est membre, on alloue une couleur libre partout.
    for account in Account.objects.filter(colour_hex="").order_by("pk"):
        member_ids = list(account.members.values_list("pk", flat=True))
        used: list[str] = []
        for uid in member_ids:
            used.extend(used_by_user.get(uid, []))
        colour = allocate_color(used)
        account.colour_hex = colour
        account.save(update_fields=["colour_hex"])
        # Réserve la teinte dans le domaine de chaque user membre.
        for uid in member_ids:
            used_by_user.setdefault(uid, []).append(colour)


def reverse(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    Institution = apps.get_model("accounts", "Institution")
    Account.objects.update(colour_hex="")
    Institution.objects.update(colour_hex="")


def _user_model_label(apps):
    """('app_label', 'ModelName') du AUTH_USER_MODEL, pour apps.get_model."""
    from django.conf import settings

    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    return app_label, model_name


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_account_institution_colour_hex"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
