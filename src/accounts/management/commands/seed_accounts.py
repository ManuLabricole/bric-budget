"""
accounts/management/commands/seed_accounts.py

Crée (ou met à jour) les comptes bancaires réels d'un utilisateur depuis un
fichier JSON, et les rattache à lui. Idempotente : rejouable à volonté.

Usage :
    python manage.py seed_accounts                    # user = "user_email" du fichier
    python manage.py seed_accounts --dry-run          # n'écrit rien, montre le plan
    python manage.py seed_accounts --user me@ex.com   # force le user cible
    python manage.py seed_accounts --file autre.json  # autre fichier de comptes

Pourquoi cette commande DÉLÈGUE à accounts.services
----------------------------------------------------
La version précédente réimplémentait la création (`Account.objects.create` +
`CheckingAccount.objects.create`) alors que `services.create.create_account()`
existait déjà — le point d'entrée du wizard UI (#73). Cette duplication avait
dérivé et perdu des choses en route :

    · `account.members.add(user)`  → OUBLIÉ : le compte n'appartenait à personne,
      donc INVISIBLE partout (`for_user()` filtre sur members — SR-001).
    · `full_clean()`               → absent : les invariants modèle (pension ⇒ CHF,
      IBAN unique, longueurs) n'étaient pas vérifiés.
    · `transaction.atomic()`       → absent : un échec laissait un Account sans
      son *Details.
    · `allocate_color()`           → absent : compte sans couleur stable dans les
      charts patrimoine (#134).
    · `iban=""` → None             → partiel : le 2e compte sans IBAN violait la
      contrainte d'unicité.

D'où la règle suivie ici : le seed ORCHESTRE (lire, valider, décider), les
services ÉCRIVENT. Créer un compte par le seed et par l'UI emprunte exactement
le même chemin, donc corriger l'un corrige l'autre.

Tout-ou-rien
------------
La totalité des vérifications tourne AVANT la première écriture, et l'écriture
est enveloppée dans `transaction.atomic()` (SR-003). Un fichier avec un problème
sur un seul compte ne produit pas une base à moitié seedée ; la commande liste
TOUS les problèmes d'un coup pour qu'ils se corrigent en une passe.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Account, Institution
from accounts.seed_config import (
    AccountSpec,
    SeedConfig,
    SeedConfigError,
    load_seed_config,
)
from accounts.services.create import create_account
from accounts.services.update import update_account

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Crée ou met à jour les comptes bancaires depuis un fichier JSON "
        "et les rattache à un utilisateur (idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=None,
            help="Fichier de comptes. Défaut : settings.SEED_ACCOUNTS_FILE.",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Email du user cible. Défaut : « user_email » du fichier.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le plan sans rien écrire en base.",
        )

    # =========================================================================
    # Point d'entrée
    # =========================================================================

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        path = Path(options["file"] or settings.SEED_ACCOUNTS_FILE)

        self._assert_not_tracked_by_git(path)

        try:
            config = load_seed_config(path)
        except SeedConfigError as exc:
            raise CommandError(str(exc)) from exc

        user = self._resolve_user(options["user"] or config.user_email)

        self.stdout.write(f"Fichier : {path}")
        self.stdout.write(f"User    : {user.email}")
        self.stdout.write("")

        plan = self._build_plan(config, user)

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode dry-run — rien n'est écrit."))
            return

        created, updated = self._apply(plan, user)
        self._report(created, updated, plan, user, path)

    # =========================================================================
    # Garde-fous
    # =========================================================================

    def _assert_not_tracked_by_git(self, path: Path) -> None:
        """
        Refuse de tourner si le fichier de comptes est suivi par git (SR-008).

        Le fichier contient des IBAN réels. `.gitignore` le couvre, mais un
        `git add -f` un soir de fatigue suffit à le committer — et un secret
        poussé une fois reste dans l'historique. Ce garde-fou coûte trois lignes.

        git absent ou hors dépôt → on n'empêche rien (la commande doit tourner
        dans un conteneur sans git).
        """
        try:
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(path)],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return  # pas de git ici : rien à vérifier

        if result.returncode == 0:
            raise CommandError(
                f"{path} est SUIVI PAR GIT — il contient des IBAN réels (SR-008).\n"
                f"Retire-le de l'index avant de continuer :\n"
                f"    git rm --cached {path}\n"
                f"Puis vérifie qu'il est bien ignoré : git check-ignore -v {path}"
            )

    def _resolve_user(self, email: str):
        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        if user is None:
            known = ", ".join(user_model.objects.values_list("email", flat=True)[:10])
            raise CommandError(
                f"Utilisateur « {email} » introuvable.\n"
                f"Users existants : {known or '(aucun)'}\n"
                "Crée-le avec : python manage.py create_user"
            )
        return user

    # =========================================================================
    # Plan — tout est décidé (et vérifié) avant la moindre écriture
    # =========================================================================

    def _build_plan(
        self, config: SeedConfig, user
    ) -> list[tuple[str, AccountSpec, object]]:
        """
        Retourne [(action, spec, existing_account_or_None)] et échoue si un
        problème bloquant est détecté.

        Les problèmes sont TOUS collectés avant d'être levés ensemble : corriger
        un fichier de comptes une erreur à la force la main est pénible, et
        chaque aller-retour coûte un run.
        """
        institutions = {i.slug: i for i in Institution.objects.all()}
        plan: list[tuple[str, AccountSpec, object]] = []
        problems: list[str] = []

        for spec in config.accounts:
            if not spec.has_identity:
                plan.append(("skip", spec, None))
                continue

            if spec.institution not in institutions:
                problems.append(
                    f"« {spec.name} » : institution « {spec.institution} » absente "
                    "en base. Lance d'abord : python manage.py seed_institutions"
                )
                continue

            existing = self._find_existing(spec, institutions[spec.institution])

            if existing is None:
                plan.append(("create", spec, None))
            elif existing.members.filter(pk=user.pk).exists():
                plan.append(("update", spec, existing))
            elif existing.members.exists():
                owners = ", ".join(m.email for m in existing.members.all())
                problems.append(
                    f"« {spec.name} » : son identifiant est DÉJÀ porté par le compte "
                    f"« {existing.name} » (#{existing.pk}) qui appartient à {owners}. "
                    "Le seed ne rattache pas le compte d'un autre utilisateur. "
                    f"Supprime ce compte, ou retire {user.email} de ce seed."
                )
            else:
                # Compte orphelin (aucun membre) portant déjà cette identité :
                # on l'adopte plutôt que d'en créer un doublon, qui rendrait la
                # résolution à l'import ambiguë (deux comptes, même n° de contrat).
                plan.append(("adopt", spec, existing))

        if problems:
            raise CommandError(
                "Seed impossible — "
                + f"{len(problems)} problème(s), rien n'a été écrit :\n  · "
                + "\n  · ".join(problems)
            )

        self._print_plan(plan)
        return plan

    def _find_existing(self, spec: AccountSpec, institution: Institution):
        """
        Cherche un compte portant déjà cette identité, SANS filtre utilisateur.

        La recherche est volontairement globale : son but est justement de
        DÉTECTER qu'un identifiant est déjà pris par quelqu'un d'autre. Le
        rattachement, lui, reste fail-closed — `_build_plan` refuse tout compte
        appartenant à un autre utilisateur.
        """
        if spec.iban:
            # Account.iban est unique globalement → au plus un résultat.
            found = Account.objects.filter(iban=spec.iban).first()
            if found is not None:
                return found

        if spec.contract_number:
            return Account.objects.filter(
                institution=institution, contract_number=spec.contract_number
            ).first()

        return None

    def _print_plan(self, plan) -> None:
        labels = {
            "create": (self.style.SUCCESS, "créer "),
            "update": (self.style.WARNING, "màj   "),
            "adopt": (self.style.WARNING, "adopte"),
            "skip": (self.style.NOTICE, "ignore"),
        }
        for action, spec, _existing in plan:
            style, label = labels[action]
            suffix = (
                "  (ni IBAN ni n° de contrat — à compléter dans le fichier)"
                if action == "skip"
                else ""
            )
            self.stdout.write(
                style(f"  {label}  {spec.institution:<7} {spec.name}{suffix}")
            )
        self.stdout.write("")

    # =========================================================================
    # Écriture — atomique (SR-003)
    # =========================================================================

    def _apply(self, plan, user) -> tuple[int, int]:
        created = updated = 0
        try:
            with transaction.atomic():
                for action, spec, existing in plan:
                    if action == "skip":
                        continue
                    if action == "create":
                        self._create(spec, user)
                        created += 1
                    else:
                        self._update(spec, existing, user)
                        updated += 1
        except ValidationError as exc:
            # Remontée telle quelle : les messages des services sont déjà écrits
            # pour l'utilisateur final (« Renseigne l'IBAN ou le n° de contrat »).
            raise CommandError(
                "Écriture refusée, rien n'a été enregistré : " + "; ".join(exc.messages)
            ) from exc
        return created, updated

    def _type_fields(self, spec: AccountSpec) -> dict:
        """
        Champs propres au type, déjà castés (contrat de create_account/builders).

        L'IBAN est passé pour les DEUX types : il vit sur `Account.iban` (source
        unique #82), pas sur le sous-modèle — UBS exporte des relevés d'épargne
        qui portent leur propre IBAN, et c'est lui qui résout le compte.
        Le BIC n'existe que sur CheckingAccount : l'envoyer pour une épargne
        serait ignoré en silence, donc on ne l'envoie pas.
        """
        fields: dict = {"iban": spec.iban}
        if spec.account_type == Account.AccountType.CHECKING:
            fields["bic"] = spec.bic
        else:
            fields["interest_rate"] = spec.interest_rate
            fields["account_reference"] = spec.account_reference
        return fields

    def _create(self, spec: AccountSpec, user) -> None:
        account = create_account(
            user=user,
            institution=Institution.objects.get(slug=spec.institution),
            account_type=spec.account_type,
            name=spec.name,
            currency=spec.currency,
            contract_number=spec.contract_number,
            **self._type_fields(spec),
        )
        self._sync_is_active(account, spec)

    def _update(self, spec: AccountSpec, account: Account, user) -> None:
        update_account(
            account=account,
            name=spec.name,
            currency=spec.currency,
            contract_number=spec.contract_number,
            **self._type_fields(spec),
        )
        # Idempotent : add() sur un membre déjà présent est un no-op. C'est aussi
        # ce qui « adopte » un compte orphelin trouvé par _find_existing.
        account.members.add(user)
        self._sync_is_active(account, spec)

    def _sync_is_active(self, account: Account, spec: AccountSpec) -> None:
        """
        `is_active` n'est pas un paramètre des services (l'UI passe par
        archive_account) → on l'aligne ici, et seulement s'il diffère.
        """
        if account.is_active != spec.is_active:
            account.is_active = spec.is_active
            account.save(update_fields=["is_active"])

    # =========================================================================
    # Rapport
    # =========================================================================

    def _report(self, created: int, updated: int, plan, user, path: Path) -> None:
        skipped = sum(1 for action, _, _ in plan if action == "skip")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ {created} compte(s) créé(s), {updated} mis à jour"
                + (f", {skipped} ignoré(s)" if skipped else "")
            )
        )
        logger.info(
            "seed_accounts ok created=%d updated=%d skipped=%d",
            created,
            updated,
            skipped,
        )

        self._warn_incomplete(user, path)

    def _warn_incomplete(self, user, path: Path) -> None:
        """
        Signale les comptes épargne sans taux — corrigeables dans le FICHIER.

        Scopé `for_user` (SR-001) : sans ce filtre, le rapport listerait les
        comptes d'autres utilisateurs présents en base (démo, tests), ce qui est
        à la fois une fuite et un bruit inutile.

        On renvoie vers le fichier de seed, pas vers l'admin : le fichier est
        désormais la source de vérité, et une correction faite dans l'admin
        serait écrasée au prochain run.
        """
        incomplete = [
            f"{a.institution.name} — {a.name}"
            for a in Account.objects.for_user(user)
            .filter(account_type=Account.AccountType.SAVINGS)
            .select_related("institution", "savings_account")
            if getattr(a, "savings_account", None) and not a.savings_account.is_complete
        ]
        if not incomplete:
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("⚠  Taux d'intérêt à renseigner :"))
        for line in incomplete:
            self.stdout.write(self.style.WARNING(f"   • {line}"))
        self.stdout.write(
            self.style.WARNING(
                f'   → ajoute "interest_rate" dans {path}, puis relance la commande.'
            )
        )
