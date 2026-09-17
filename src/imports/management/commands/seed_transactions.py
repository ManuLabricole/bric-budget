"""
imports/management/commands/seed_transactions.py

Importe en masse des relevés bancaires depuis un dossier, en empruntant
EXACTEMENT le chemin du bouton « Importer » de l'interface web.

Usage :
    python manage.py seed_transactions                      # dry-run (défaut)
    python manage.py seed_transactions --commit             # écrit en base
    python manage.py seed_transactions --dir <dossier>
    python manage.py seed_transactions --file <fichier> --commit
    python manage.py seed_transactions --force-account <id> # lève une ambiguïté

Pourquoi cette commande, alors que import_yuh/import_ubs/import_cic existent
--------------------------------------------------------------------------
Parce que ces commandes-là constituent un SECOND chemin d'import, parallèle à
celui de l'interface — et il a déjà dérivé : elles n'archivent pas le fichier
source chiffré, ce que le bouton web fait systématiquement. Deux chemins pour
une même opération, c'est deux comportements à maintenir et un qui prend du
retard sur l'autre.

Cette commande n'introduit donc aucune logique d'import : elle appelle le même
triplet que `imports.views.import_confirm` et que le seed de démo (#118) —

    prepare_import()      détection du connecteur + résolution du compte + hash
    run_import()          parse + écriture via ImportService
    persist_import_file() archivage chiffré du fichier source + MAJ ImportLog

— ce qui en fait le TROISIÈME appelant d'un chemin unique, et non un troisième
chemin. Corriger un import corrige les trois usages d'un coup.

Rejouable
---------
`ImportService.run()` refuse un fichier dont le `file_hash` a déjà été importé
sur ce compte : relancer la commande sur un dossier déjà traité ne crée aucun
doublon et n'écrit rien. Chaque fichier est sa propre unité de travail — un
fichier en échec n'empêche pas les suivants, et il suffit de relancer après
correction.

Dry-run par défaut
------------------
Comme `import_all`. Un import de masse touche des centaines de transactions
réelles : on regarde d'abord ce qui se passerait, on écrit ensuite.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from connectors.resolver import AccountAmbiguous, AccountNotFound
from imports.orchestrator import (
    UnknownConnector,
    persist_import_file,
    prepare_import,
    run_import,
)

logger = logging.getLogger(__name__)

# Dossier de dépôt par défaut — celui que la doc d'import et `import_all`
# désignent déjà comme la zone où l'on pose ses exports bancaires.
DEFAULT_RAW_DIR = Path("assets/private/data/raw")


def _mask(identifier: str) -> str:
    """
    Tronque un IBAN/RIB avant affichage (SR-008).

    Les messages d'erreur du resolver portent l'identifiant lu dans le fichier.
    Un import de masse en imprimerait des dizaines, dans un terminal puis dans
    un copier-coller de log — on n'en montre que de quoi reconnaître le compte.
    """
    if not identifier:
        return "(aucun)"
    return identifier[:6] + "…" + identifier[-4:] if len(identifier) > 10 else "…"


class Command(BaseCommand):
    help = (
        "Importe tous les relevés d'un dossier via le chemin standard "
        "(identique au bouton Importer). Dry-run par défaut."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(DEFAULT_RAW_DIR),
            help=f"Dossier à parcourir, récursivement. Défaut : {DEFAULT_RAW_DIR}",
        )
        parser.add_argument(
            "--file",
            default=None,
            help="Importer un seul fichier (ignore --dir).",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Email du user cible. Défaut : settings.PERSO_SEED_USER_EMAIL.",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Écrit réellement en base. Sans ce drapeau : simulation.",
        )
        parser.add_argument(
            "--force-account",
            type=int,
            default=None,
            help=(
                "ID du compte à utiliser quand le fichier ne porte aucun "
                "identifiant (Yuh). Équivaut au sélecteur de compte de l'UI."
            ),
        )

    # =========================================================================
    # Point d'entrée
    # =========================================================================

    def handle(self, *args, **options):
        commit = options["commit"]
        user = self._resolve_user(options["user"] or settings.PERSO_SEED_USER_EMAIL)
        files = self._collect_files(options)

        self.stdout.write(f"User    : {user.email}")
        self.stdout.write(f"Fichiers: {len(files)}")
        self.stdout.write(
            self.style.SUCCESS("Mode    : ÉCRITURE")
            if commit
            else self.style.WARNING(
                "Mode    : simulation (ajoute --commit pour écrire)"
            )
        )
        self.stdout.write("")

        totals = {"created": 0, "skipped": 0, "files_ok": 0, "files_ko": 0}
        for path in files:
            self._process(path, user, commit, options["force_account"], totals)

        self._summary(totals, commit)

    def _resolve_user(self, email: str):
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(
                f"Utilisateur « {email} » introuvable. "
                "Passe --user, ou renseigne PERSO_SEED_USER_EMAIL dans .env."
            )
        return user

    def _collect_files(self, options) -> list[Path]:
        """Fichiers à traiter, triés — un ordre stable rend les runs comparables."""
        if options["file"]:
            path = Path(options["file"])
            if not path.is_file():
                raise CommandError(f"Fichier introuvable : {path}")
            return [path]

        directory = Path(options["dir"])
        if not directory.is_dir():
            raise CommandError(f"Dossier introuvable : {directory}")

        # rglob : les exports sont rangés par banque, parfois par année.
        # Les fichiers cachés (.DS_Store) et les archives chiffrées (.enc) sont
        # écartés : ces dernières sont la SORTIE de l'archivage, pas une entrée.
        return sorted(
            p
            for p in directory.rglob("*")
            if p.is_file() and not p.name.startswith(".") and p.suffix != ".enc"
        )

    # =========================================================================
    # Un fichier
    # =========================================================================

    def _process(self, path: Path, user, commit: bool, forced_id, totals) -> None:
        label = path.name
        try:
            prepared = self._prepare(path, user, forced_id)
        except _Skip as skip:
            totals["files_ko"] += 1
            self.stdout.write(self.style.WARNING(f"  ⏭  {label}"))
            self.stdout.write(self.style.WARNING(f"      {skip}"))
            return

        results = run_import(
            prepared,
            path,
            filename=path.name,
            imported_by=user,
            dry_run=not commit,
        )

        # persist_import_file archive le fichier SOURCE (chiffré) et complète les
        # ImportLog. Uniquement en écriture réelle : en simulation il n'y a aucun
        # log à compléter, et archiver un fichier non importé serait mensonger.
        if commit:
            persist_import_file(
                path=path,
                filename=path.name,
                matches=prepared.matches,
                balances=prepared.balances,
                results=results,
            )

        self._report_file(label, prepared, results, totals)

    def _prepare(self, path: Path, user, forced_id):
        """
        prepare_import + traduction des refus du resolver en messages actionnables.

        Lève _Skip (interne) plutôt que de laisser remonter : un fichier
        impossible à rattacher ne doit pas interrompre le lot.
        """
        try:
            return prepare_import(path, user=user, forced_account_id=forced_id)

        except UnknownConnector:
            raise _Skip("format non reconnu par les connecteurs disponibles") from None

        except AccountNotFound as exc:
            raise _Skip(
                f"aucun compte pour l'identifiant {_mask(exc.contract_number)} "
                f"({exc.institution_slug})"
                + (f", feuille « {exc.sheet_name} »" if exc.sheet_name else "")
                + " — ajoute-le dans assets/private/accounts.json puis relance "
                "seed_accounts"
            ) from None

        except AccountAmbiguous as exc:
            # Le fichier ne porte aucun identifiant (Yuh). L'UI montre un
            # sélecteur ; en ligne de commande on ne devine que s'il n'y a
            # qu'un seul candidat — et on le DIT, plutôt que de le taire.
            if len(exc.accounts) == 1:
                only = exc.accounts[0]
                self.stdout.write(
                    self.style.NOTICE(
                        f"      compte déduit : « {only.name} » "
                        f"(seul compte {exc.institution_slug} actif)"
                    )
                )
                return prepare_import(path, user=user, forced_account_id=only.pk)

            candidates = ", ".join(f"#{a.pk} {a.name}" for a in exc.accounts)
            raise _Skip(
                f"{len(exc.accounts)} comptes {exc.institution_slug} possibles "
                f"({candidates}) — relance avec --file {path} "
                "--force-account <id>"
            ) from None

        except ValueError as exc:
            raise _Skip(f"fichier illisible : {exc}") from None

    # =========================================================================
    # Rapport
    # =========================================================================

    def _report_file(self, label: str, prepared, results, totals) -> None:
        totals["files_ok"] += 1
        self.stdout.write(f"  📄 {label}")

        for match, result in zip(prepared.matches, results, strict=True):
            totals["created"] += result.count_created
            totals["skipped"] += result.count_skipped

            # count_errors est posé par la garde anti-doublon fichier : c'est le
            # cas NORMAL d'un seed rejoué, pas une anomalie → ton neutre.
            if result.error_detail:
                for detail in result.error_detail:
                    self.stdout.write(
                        self.style.NOTICE(f"      {match.account.name} — {detail}")
                    )
                continue

            self.stdout.write(
                f"      {match.account.name} : "
                f"{result.count_created} nouvelle(s), "
                f"{result.count_skipped} déjà connue(s)"
            )

    def _summary(self, totals, commit: bool) -> None:
        self.stdout.write("")
        line = (
            f"{totals['files_ok']} fichier(s) traité(s), "
            f"{totals['files_ko']} ignoré(s) — "
            f"{totals['created']} transaction(s) "
            f"{'importées' if commit else 'à importer'}, "
            f"{totals['skipped']} déjà en base"
        )
        self.stdout.write(self.style.SUCCESS(f"✓ {line}"))
        logger.info("seed_transactions %s commit=%s", line, commit)

        if not commit and totals["created"]:
            self.stdout.write(
                self.style.WARNING("→ relance avec --commit pour écrire en base.")
            )


class _Skip(Exception):
    """Fichier non importable — motif destiné à l'utilisateur, jamais une panne."""
