"""
imports/orchestrator.py — orchestration d'un import bancaire de bout en bout.

Sort de la vue la logique partagée « fichier → DB » pour qu'elle ait UN seul
chemin et plusieurs appelants :
    - la vue web (`import_confirm`) gère session / HTMX / fragments d'erreur,
      puis délègue ici ;
    - le seed de dev (#118) appelle directement ces fonctions pour importer des
      fichiers synthétiques exactement comme un vrai upload (ImportLog + tx liées
      + fichier chiffré), sans passer par HTTP.

Étapes :
    prepare_import(path, user)  → détection connecteur + résolution compte(s)
                                  + file_hash + balances  (= PreparedImport)
    run_import(prepared, …)     → parse par compte + ImportService.run
    persist_import_file(…)      → chiffre + stocke le fichier source, MAJ ImportLog

prepare_import lève les exceptions du resolver (AccountNotFound / AccountAmbiguous /
ValueError) + UnknownConnector : c'est l'appelant (vue) qui décide quoi afficher.
Le seed crée les comptes AVANT d'importer → il ne les rencontre pas.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.db.models import Count, Max, Min
from django.utils import timezone

from connectors.base import BaseConnector
from connectors.cic.parser import CICConnector
from connectors.resolver import AccountMatch, detect_connector, resolve_accounts
from imports.storage import build_import_filename, save_import_file
from transactions.models import ImportLog, Transaction
from transactions.services import ImportResult, ImportService, compute_file_hash

logger = logging.getLogger(__name__)


class UnknownConnector(Exception):
    """Aucun connecteur ne reconnaît le fichier (format non supporté)."""

    def __init__(self, filename: str):
        self.filename = filename
        super().__init__(f"Format non reconnu : {filename}")


def account_file_hash(file_hash: str, sheet_name: str | None) -> str:
    """
    Retourne un hash unique par (fichier, compte).

    Yuh/UBS : sheet_name=None → file_hash inchangé (1 compte par fichier).
    CIC     : sheet_name="Compte courant"… → sha256(file_hash:sheet_name).

    Pourquoi ? ImportLog.file_hash est UNIQUE en DB. Un fichier CIC génère N
    ImportLogs (1 par feuille) → chacun a besoin d'un hash distinct.
    """
    if sheet_name is None:
        return file_hash
    return hashlib.sha256(f"{file_hash}:{sheet_name}".encode()).hexdigest()


@dataclass
class PreparedImport:
    """Tout ce qu'il faut pour importer un fichier, résolu une seule fois.

    balances : {sheet_name|None: solde extrait} — None pour Yuh sans solde,
    une entrée par feuille pour CIC, {None: solde} pour Yuh/UBS.
    """

    connector: BaseConnector
    matches: list[AccountMatch]
    file_hash: str
    balances: dict


def _extract_balances(
    connector: BaseConnector, path: Path, matches: list[AccountMatch]
) -> dict:
    """Soldes par compte : par feuille pour CIC, solde global sinon."""
    if isinstance(connector, CICConnector):
        sheets_info = {s["sheet_name"]: s for s in connector.get_account_sheets(path)}
        return {
            m.sheet_name: sheets_info.get(m.sheet_name, {}).get("balance")
            for m in matches
        }
    return {None: connector.extract_balance(path)}


def prepare_import(
    path: Path, *, user, forced_account_id: int | None = None
) -> PreparedImport:
    """
    Détection du connecteur + résolution du/des compte(s) + file_hash + balances.

    Lève :
        UnknownConnector  : format non reconnu
        AccountNotFound / AccountAmbiguous / ValueError : voir connectors.resolver

    `user` scope la résolution (IDOR) : toujours passer request.user (vue) ou le
    user démo (seed). `forced_account_id` : compte choisi via le picker (Yuh).
    """
    connector = detect_connector(path)
    if connector is None:
        raise UnknownConnector(path.name)
    matches = resolve_accounts(
        connector, path, forced_account_id=forced_account_id, user=user
    )
    file_hash = compute_file_hash(path)
    balances = _extract_balances(connector, path, matches)
    return PreparedImport(
        connector=connector, matches=matches, file_hash=file_hash, balances=balances
    )


def run_import(
    prepared: PreparedImport,
    path: Path,
    *,
    filename: str,
    imported_by,
    dry_run: bool,
) -> list[ImportResult]:
    """
    Parse chaque compte résolu et écrit via ImportService.run().

    Même chemin pour le dry-run (dry_run=True, preview) et l'import réel
    (dry_run=False). Retourne un ImportResult par compte, dans l'ordre de
    prepared.matches (l'appelant peut zipper avec les comptes pour l'affichage).
    """
    service = ImportService()
    results: list[ImportResult] = []
    for match in prepared.matches:
        if match.sheet_name is not None:
            transactions = prepared.connector.parse_sheet(path, match.sheet_name)
        else:
            transactions = prepared.connector.parse(path)
        result = service.run(
            transactions=transactions,
            account=match.account,
            imported_by=imported_by,
            filename=filename,
            file_hash=account_file_hash(prepared.file_hash, match.sheet_name),
            balance=prepared.balances.get(match.sheet_name),
            dry_run=dry_run,
        )
        results.append(result)
    return results


def persist_import_file(
    *,
    path: Path,
    filename: str,
    matches: list[AccountMatch],
    balances: dict,
    results: list[ImportResult],
) -> None:
    """
    Chiffre et stocke le fichier d'import dans IMPORT_STORAGE_ROOT, puis met à
    jour les ImportLog avec le chemin et le nom canonique.

    Appelé après l'écriture en DB (import réel). Les erreurs de stockage sont
    loggées sans être levées : l'import est déjà committé en DB, l'utilisateur ne
    doit pas perdre ses transactions pour un problème de fichier (il peut
    réimporter depuis l'original).
    """
    log_pks = [r.log_pk for r in results if r.log_pk]
    if not log_pks:
        # Aucun ImportLog créé (toutes les runs ont échoué tôt) → pas de stockage
        logger.warning(
            "[import_storage] No log_pk found after confirm — skipping file storage."
        )
        return

    try:
        # date_min / date_max des transactions insérées dans ces logs.
        # 0 nouvelles transactions (all skipped) → None → "nodate" dans le nom.
        agg = Transaction.objects.filter(import_log_id__in=log_pks).aggregate(
            date_min=Min("date"), date_max=Max("date"), n=Count("id")
        )

        institution_slug = matches[0].account.institution.slug

        # Noms de comptes normalisés : espaces/slashs → underscores, minuscules
        account_names = [
            m.account.name.lower().replace(" ", "_").replace("/", "_") for m in matches
        ]

        # Première balance disponible (None si aucun connecteur ne l'extrait)
        raw_balance = next(iter(balances.values()), None)
        balance_dec = Decimal(str(raw_balance)) if raw_balance is not None else None

        year = agg["date_max"].year if agg["date_max"] else timezone.now().year

        stored_filename = build_import_filename(
            institution_slug=institution_slug,
            account_names=account_names,
            date_min=agg["date_min"],
            date_max=agg["date_max"],
            balance=balance_dec,
            n_transactions=agg["n"] or 0,
            original_ext=Path(filename).suffix,
        )

        stored_rel, is_enc = save_import_file(
            path, institution_slug, stored_filename, year
        )

        # Tous les ImportLogs de cet import (CIC → plusieurs logs, même fichier
        # physique → même stored_path dans chaque row).
        ImportLog.objects.filter(pk__in=log_pks).update(
            stored_filename=stored_filename,
            stored_path=str(stored_rel),
            is_encrypted=is_enc,
        )

        logger.info(
            "import_storage_saved ok file=%s dest=%s encrypted=%s",
            filename,
            stored_rel,
            is_enc,
        )

    except Exception as exc:
        # Le stockage a échoué APRÈS le commit DB. On logge sans crasher :
        # l'utilisateur a ses transactions, le fichier source n'est juste pas archivé.
        logger.error(
            "[import_storage] Failed to persist %s: %s",
            filename,
            exc,
            exc_info=True,
        )
