"""
imports/views.py — Upload et traitement de fichiers bancaires via l'interface web.

Flow complet :
    1. GET  /import/          → import_upload  → page principale (formulaire + historique)
    2. POST /import/          → import_upload  → dry-run → fragment _steps_result.html (HTMX)
    3. POST /import/confirm/  → import_confirm → import réel → HX-Redirect /import/
    4. GET  /import/<pk>/detail/ → import_log_detail → fragment right panel (HTMX)

Stockage temporaire :
    Le fichier uploadé est sauvegardé dans /tmp/ entre le dry-run (étape 2)
    et la confirmation (étape 3). Il est supprimé après confirm ou en cas d'erreur.
    La session Django stocke le chemin temp + métadonnées (pas le fichier lui-même).
"""

import hashlib
import logging
import os
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, Max, Min
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Account, CheckingAccount, Institution, SavingsAccount
from connectors.cic.parser import CICConnector
from connectors.resolver import (
    AccountAmbiguous,
    AccountNotFound,
    detect_connector,
    resolve_accounts,
)
from imports.storage import build_import_filename, save_import_file
from transactions.models import ImportLog, Transaction
from transactions.services import ImportService, compute_file_hash

logger = logging.getLogger(__name__)


def _month_label(d: date) -> str:
    """Formate un jour : '23 mars' → '23 Mar' (str.day + strftime %b).   = espace insécable."""
    return str(d.day) + " " + d.strftime("%b")


def _activity_window(period_mode: str, period_offset: int):
    """
    Calcule la fenêtre temporelle du graphique d'activité.
    Retourne (start_date, end_date, period_display, can_go_next).
    Partagé entre import_upload (GET) et _render_activity_section.
    """
    today = timezone.now().date()
    window_days = {"1m": 30, "3m": 91, "1y": 365}[period_mode]
    end_date = today - timedelta(days=period_offset * window_days)
    start_date = end_date - timedelta(days=window_days)
    period_display = (
        _month_label(start_date)
        + " – "
        + _month_label(end_date)
        + " "
        + str(end_date.year)
    )
    can_go_next = period_offset > 0
    return start_date, end_date, period_display, can_go_next


def _account_file_hash(file_hash: str, sheet_name: str | None) -> str:
    """
    Retourne un hash unique par (fichier, compte).

    Pour Yuh/UBS : sheet_name=None → file_hash inchangé (1 compte par fichier).
    Pour CIC     : sheet_name="Compte courant" etc. → hash dérivé = sha256(file_hash:sheet_name).

    Pourquoi ? ImportLog.file_hash est UNIQUE en DB. Un fichier CIC génère N ImportLogs
    (1 par feuille), chacun a besoin d'un hash distinct pour éviter l'IntegrityError.
    """
    if sheet_name is None:
        return file_hash
    return hashlib.sha256(f"{file_hash}:{sheet_name}".encode()).hexdigest()


@login_required
def import_upload(request):
    """
    GET  → page principale : KPIs sync + chart + historique + upload compact.
    POST → dry-run HTMX → fragment _steps_result.html ou _steps_error.html.
    """
    if request.method == "POST":
        return _handle_dry_run(request)

    today = timezone.now().date()

    # ── Période du graphique d'activité ──────────────────────────────────────
    # Lue depuis la session — modifiée par set_period().
    period_mode = request.session.get("import_period_mode", "1y")
    period_offset = request.session.get("import_period_offset", 0)
    filter_account_ids = list(request.session.get("import_filter_accounts_hidden", []))

    start_date, end_date, period_display, can_go_next = _activity_window(
        period_mode, period_offset
    )

    # ── Période du graphique d'activité ──────────────────────────────────────
    # Lue depuis la session — modifiée par set_period().
    period_mode = request.session.get("import_period_mode", "1y")
    period_offset = request.session.get("import_period_offset", 0)
    filter_account_ids = list(request.session.get("import_filter_account_ids", []))

    window_days = {"1m": 30, "3m": 91, "1y": 365}[period_mode]
    end_date = today - timedelta(days=period_offset * window_days)
    start_date = end_date - timedelta(days=window_days)

    # Label affiché dans la pill centrale de period_nav
    # Exemple : "23 mars – 22 avr. 2026"
    def _month_label(d):
        return str(d.day) + " " + d.strftime("%b")

    period_display = (
        _month_label(start_date)
        + " – "
        + _month_label(end_date)
        + " "
        + str(end_date.year)
    )
    can_go_next = period_offset > 0

    # ── Sync status groupé par banque ────────────────────────────────────────
    # Règles couleur :
    #   today (days==0)  → badge "ok"     → vert  (text-income)
    #   < 1 semaine      → badge "recent" → gris  (text-text-muted)
    #   ≥ 1 semaine      → badge "stale"  → orange (text-warning)
    #   jamais importé   → badge "never"  → dim   (text-text-disabled)
    active_accounts = (
        Account.objects.for_user(request.user)
        .filter(is_active=True)
        .select_related("institution")
        .order_by("institution__name", "name")
    )
    # Construire un dict bank → liste de comptes
    banks_map = defaultdict(list)
    for account in active_accounts:
        last_log = (
            ImportLog.objects.filter(account=account).order_by("-imported_at").first()
        )
        if last_log:
            days = (today - last_log.imported_at.date()).days
            if days == 0:
                badge = "ok"
            elif days < 7:
                badge = "recent"
            else:
                badge = "stale"
        else:
            days = None
            badge = "never"
        banks_map[account.institution].append(
            {"account": account, "last_log": last_log, "days": days, "badge": badge}
        )
    bank_groups = [
        {"bank": bank, "accounts": accounts} for bank, accounts in banks_map.items()
    ]

    # ── Chart — transactions groupées par date réelle sur 12 mois ───────────
    # Axe X = date de la transaction (pas date d'import).
    # Raison : l'import initial bulk (ex: 4 000 tx Yuh) crée un spike géant
    # sur la date d'import, masquant toute l'activité réelle. En utilisant
    # Transaction.date, les mouvements se répartissent sur leurs vraies dates.
    # IDOR : filtre account__members=request.user — jamais de transactions cross-user.
    tx_qs = Transaction.objects.filter(
        account__members=request.user,
        date__gt=start_date,
        date__lte=end_date,
        is_ignored=False,
    )
    # Filtre compte (blacklist) : scopé à l'user (account__members ci-dessus).
    if filter_account_ids:
        tx_qs = tx_qs.exclude(account_id__in=filter_account_ids)

    tx_by_day = list(
        tx_qs.select_related("account__institution")
        .values("date", "account__institution__name")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # Banques présentes dans la fenêtre (ordre d'apparition chronologique)
    seen_bank_names = []
    for row in tx_by_day:
        name = row["account__institution__name"]
        if name not in seen_bank_names:
            seen_bank_names.append(name)

    # ── Historique groupé par fichier (file_hash) ───────────────────────────
    # Un même fichier CIC génère N ImportLogs (1 par feuille/compte).
    # On les regroupe pour afficher une seule ligne par upload avec sous-lignes.
    all_logs = list(
        ImportLog.objects.filter(account__members=request.user)
        .select_related("account__institution", "account__checking_account")
        .order_by("-imported_at")
    )
    seen_hashes: dict[Any, dict[str, Any]] = {}
    grouped_logs: list[dict[str, Any]] = []
    for log in all_logs:
        key = log.file_hash or log.pk  # fallback si file_hash NULL (anciens imports)
        if key not in seen_hashes:
            group = {
                "filename": log.filename,
                "imported_at": log.imported_at,
                "file_hash": log.file_hash,
                "entries": [],
            }
            seen_hashes[key] = group
            grouped_logs.append(group)
        seen_hashes[key]["entries"].append(log)

    # Calculer les totaux par groupe + méthode de matching par entrée
    for group in grouped_logs:
        entries = cast(list, group["entries"])
        n_created: int = sum(e.count_created for e in entries)
        n_skipped: int = sum(e.count_skipped for e in entries)
        n_errors: int = sum(e.count_errors for e in entries)
        group["total_created"] = n_created
        group["total_skipped"] = n_skipped
        group["total_errors"] = n_errors
        # total_transactions = tout ce que le fichier contenait (new + doublons)
        group["total_transactions"] = n_created + n_skipped
        group["multi"] = len(entries) > 1
        group["bank"] = entries[0].account.institution
        # Méthode de matching par compte — détermine le badge de confiance affiché
        # iban     : matching par IBAN extrait du fichier      → fiabilité maximale
        # rib      : matching par RIB/contrat extrait du fichier → fiabilité haute
        # convention : seul compte actif de cette banque       → risque si doublon
        for entry in entries:
            acc = entry.account
            # Account.iban est le champ universel (checking + savings + futures cartes).
            # contract_number couvre CIC RIB, Finpension, assurances.
            # convention = Yuh (pas d'identifiant dans le fichier, matching par banque seule).
            if acc.iban:
                entry.match_method = "iban"
            elif acc.contract_number:
                entry.match_method = "rib"
            else:
                entry.match_method = "convention"

    # NE PAS appeler json.dumps() ici — json_script dans le template sérialise lui-même.
    # Un dict Python passé à json_script → JSON valide dans le script tag.
    # chart_data construit ici (après grouped_logs) pour pouvoir inclure import_markers.
    chart_data = {
        "banks": seen_bank_names,
        # logs : une entrée par (date, banque) — date = date réelle de la transaction.
        "logs": [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "bank": row["account__institution__name"],
                "created": row["count"],
                "total": row["count"],
            }
            for row in tx_by_day
        ],
        # import_markers : un marqueur par upload groupé dans la fenêtre 12 mois.
        # Affichés comme lignes verticales sur l'axe X du graphique.
        "import_markers": [
            {
                "date": timezone.localtime(group["imported_at"]).strftime("%Y-%m-%d"),
                "filename": group["filename"] or "?",
                "total": group["total_created"],
                "bank": group["bank"].name,
            }
            for group in grouped_logs
            if start_date < group["imported_at"].date() <= end_date
        ],
    }

    # Comptes de l'utilisateur — pour le filtre dropdown du graphique
    user_accounts = (
        Account.objects.filter(is_active=True, members=request.user)
        .select_related("institution")
        .order_by("institution__name", "name")
    )

    return render(
        request,
        "imports/upload.html",
        {
            "grouped_logs": grouped_logs,
            "bank_groups": bank_groups,
            "chart_data": chart_data,
            # Période graphique
            "period_mode": period_mode,
            "period_offset": period_offset,
            "period_display": period_display,
            "can_go_next": can_go_next,
            # Filtre comptes
            "accounts": user_accounts,
            "filter_account_ids": filter_account_ids,
        },
    )


def _handle_dry_run(request):
    """
    Traitement du fichier uploadé :
        1. Sauvegarde dans /tmp/
        2. detect_connector → format reconnu ?
        3. Duplicate check (file_hash déjà en DB ?)
        4. resolve_accounts → compte(s) en DB
        5. parse + ImportService.run(dry_run=True) pour chaque compte
        6. Stocker le chemin temp dans la session pour import_confirm
        7. Retourner _steps_result.html ou _steps_error.html

    CIC multi-feuilles : resolve_accounts retourne N AccountMatch → N dry-runs.
    La balance par feuille est extraite via get_account_sheets() (pas extract_balance).
    """
    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error(request, "Aucun fichier reçu.")

    # ── Sauvegarde temporaire ────────────────────────────────────────────────
    # delete=False : le fichier persiste après la fermeture du context manager.
    # Il sera supprimé manuellement dans import_confirm (ou en cas d'erreur ici).
    suffix = Path(uploaded.name).suffix or ".tmp"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp.close()
        tmp_path = Path(tmp.name)
    except Exception as e:
        logger.exception("import_upload: tmp file write failed")
        tmp.close()
        os.unlink(tmp.name)
        return _error(request, f"Erreur lors de la sauvegarde : {e}")

    try:
        # ── Détection du connecteur ──────────────────────────────────────────
        connector = detect_connector(tmp_path)
        if connector is None:
            os.unlink(tmp_path)
            return _error(
                request,
                f"Format non reconnu : « {uploaded.name} »",
                hint="Formats acceptés : CSV Yuh, CSV UBS, Excel CIC (.xlsx).",
            )

        connector_label = type(connector).__name__.replace("Connector", "")

        # ── Duplicate check au niveau fichier ────────────────────────────────
        # Duplicate check scopé à l'user : on ne cherche que les imports sur les
        # comptes dont l'user est membre. Si un autre user a importé le même fichier,
        # ce n'est pas "déjà importé" pour cet user — et on n'expose pas ses données.
        # Note : file_hash est unique=True globalement en DB (contrainte à assouplir
        # en Phase 3 vers unique_together=(file_hash, account)).
        file_hash = compute_file_hash(tmp_path)
        existing_log = (
            ImportLog.objects.filter(
                file_hash=file_hash,
                account__members=request.user,
            )
            .select_related("account__institution")
            .first()
        )
        if existing_log is not None:
            os.unlink(tmp_path)
            return render(
                request,
                "imports/partials/_steps_already_imported.html",
                {"filename": uploaded.name, "existing_log": existing_log},
            )

        # ── Résolution du ou des comptes ─────────────────────────────────────
        try:
            matches = resolve_accounts(connector, tmp_path, user=request.user)
        except AccountNotFound as e:
            # Compte introuvable → on garde le fichier temp en session et on
            # propose un formulaire de création inline (fragment HTMX).
            request.session["pending_import"] = {
                "filepath": str(tmp_path),
                "filename": uploaded.name,
                "file_hash": file_hash,
            }
            from accounts.institutions_config import KNOWN_INSTITUTIONS
            from accounts.models import Institution

            bank_config = KNOWN_INSTITUTIONS.get(e.bank_slug, {})
            try:
                bank = Institution.objects.get(slug=e.bank_slug)
            except Institution.DoesNotExist:
                bank = None
            # Meilleure suggestion de nom : sheet_name pour CIC, account_name_hint pour UBS
            account_name_hint = e.sheet_name or e.account_name_hint or ""
            return render(
                request,
                "imports/partials/_steps_create_account.html",
                {
                    "bank": bank,
                    "bank_slug": e.bank_slug,
                    "bank_name": bank_config.get("name", e.bank_slug.upper()),
                    "bank_bic": bank_config.get("bic", ""),
                    "iban": e.contract_number if e.bank_slug == "ubs" else "",
                    "contract_number": e.contract_number,
                    "contract_number_raw": e.contract_number_raw,
                    "sheet_name": e.sheet_name,
                    "account_name_hint": account_name_hint,
                    "currency": bank_config.get("currency", "EUR"),
                    "account_types": Account.AccountType.choices,
                },
            )
        except AccountAmbiguous as e:
            # Plusieurs comptes actifs pour cette banque, pas d'identifiant dans le fichier.
            # On garde le fichier temp en session et on propose un picker à l'utilisateur.
            request.session["pending_import"] = {
                "filepath": str(tmp_path),
                "filename": uploaded.name,
                "file_hash": file_hash,
                "bank_slug": e.bank_slug,
            }
            return render(
                request,
                "imports/partials/_steps_account_picker.html",
                {
                    "accounts": e.accounts,
                    "bank_slug": e.bank_slug,
                    "filename": uploaded.name,
                },
            )
        except Exception as e:
            logger.exception("import_upload: resolve_accounts unexpected failure")
            os.unlink(tmp_path)
            return _error(
                request,
                f"Compte introuvable : {e}",
                hint="Vérifiez que le compte est configuré dans l'admin Django.",
            )

        # ── Balance par compte ───────────────────────────────────────────────
        # Yuh + UBS : extract_balance() sur le fichier entier.
        # CIC       : balance par feuille depuis get_account_sheets().
        if isinstance(connector, CICConnector):
            sheets_info = {
                s["sheet_name"]: s for s in connector.get_account_sheets(tmp_path)
            }
            balances = {
                match.sheet_name: sheets_info.get(match.sheet_name, {}).get("balance")
                for match in matches
            }
        else:
            raw_balance = connector.extract_balance(tmp_path)
            balances = {None: raw_balance}

        # ── Dry-run par compte ───────────────────────────────────────────────
        service = ImportService()
        dry_results: list[dict[str, Any]] = []

        for match in matches:
            if match.sheet_name is not None:
                transactions = connector.parse_sheet(tmp_path, match.sheet_name)
            else:
                transactions = connector.parse(tmp_path)
            balance = balances.get(match.sheet_name)

            result = service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=uploaded.name,
                file_hash=_account_file_hash(file_hash, match.sheet_name),
                balance=balance,
                dry_run=True,
            )
            dry_results.append(
                {
                    "account": match.account,
                    "sheet_name": match.sheet_name,
                    "result": result,
                }
            )

        # ── Stockage session pour import_confirm ─────────────────────────────
        # On ne stocke que les métadonnées — pas le fichier lui-même.
        # import_confirm relit le fichier depuis tmp_path pour éviter une
        # désynchronisation si les données changent entre dry-run et confirm.
        request.session["pending_import"] = {
            "filepath": str(tmp_path),
            "filename": uploaded.name,
            "file_hash": file_hash,
        }

        total_created = sum(r["result"].count_created for r in dry_results)
        total_skipped = sum(r["result"].count_skipped for r in dry_results)

        # total_skipped est passé au template pour afficher le bouton
        # "Marquer comme synchronisé" quand total_created == 0 mais total_skipped > 0.
        # Sans ce flag, l'utilisateur ne pourrait pas créer l'ImportLog "sync" et
        # le badge du compte resterait "stale" indéfiniment.
        return render(
            request,
            "imports/partials/_steps_result.html",
            {
                "connector_label": connector_label,
                "dry_results": dry_results,
                "total_created": total_created,
                "total_skipped": total_skipped,
                "filename": uploaded.name,
            },
        )

    except Exception as e:
        logger.exception("import_upload: unexpected failure during dry-run")
        if tmp_path.exists():
            os.unlink(tmp_path)
        return _error(request, f"Erreur inattendue : {e}")


@login_required
@require_POST
def import_confirm(request):
    """
    Exécute l'import réel à partir des données stockées en session par _handle_dry_run.

    Re-lit le fichier temporaire, re-détecte le connecteur et re-parse les transactions.
    On re-fait tout plutôt que de stocker les TransactionDicts en session (trop volumineux).

    Après succès : HX-Redirect vers /import/ → la page se recharge avec l'historique mis à jour.
    """
    pending = request.session.get("pending_import")
    if not pending:
        return _error(request, "Session expirée ou import déjà confirmé. Recommencez.")

    tmp_path = Path(pending["filepath"])
    filename = pending["filename"]
    file_hash = pending["file_hash"]

    if not tmp_path.exists():
        del request.session["pending_import"]
        return _error(request, "Fichier temporaire introuvable. Recommencez l'import.")

    try:
        connector = detect_connector(tmp_path)
        if connector is None:
            raise ValueError("Connecteur non détecté (fichier corrompu ?)")

        matches = resolve_accounts(connector, tmp_path, user=request.user)

        if isinstance(connector, CICConnector):
            sheets_info = {
                s["sheet_name"]: s for s in connector.get_account_sheets(tmp_path)
            }
            balances = {
                match.sheet_name: sheets_info.get(match.sheet_name, {}).get("balance")
                for match in matches
            }
        else:
            raw_balance = connector.extract_balance(tmp_path)
            balances = {None: raw_balance}

        service = ImportService()

        # Accumuler les résultats pour récupérer les log_pk après la boucle.
        # On en a besoin pour retrouver les transactions insérées (date_min/max)
        # et déclencher le stockage permanent du fichier source.
        service_results = []

        for match in matches:
            if match.sheet_name is not None:
                transactions = connector.parse_sheet(tmp_path, match.sheet_name)
            else:
                transactions = connector.parse(tmp_path)
            balance = balances.get(match.sheet_name)
            result = service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=filename,
                file_hash=_account_file_hash(file_hash, match.sheet_name),
                balance=balance,
                dry_run=False,
            )
            service_results.append(result)

        # Audit log : import réussi — événement métier critique pour traçabilité prod.
        total_created = sum(r.count_created for r in service_results)
        total_skipped = sum(r.count_skipped for r in service_results)
        logger.info(
            "import_confirm: filename=%s connector=%s accounts=%d "
            "created=%d skipped=%d by user=%s",
            filename,
            type(connector).__name__,
            len(matches),
            total_created,
            total_skipped,
            request.user.id,
        )

        # ── Stockage permanent du fichier source ─────────────────────────────
        # On stocke le fichier AVANT le finally (qui supprime tmp_path) et
        # uniquement si au moins un ImportLog a été créé (log_pk non None).
        # Pour les imports "0 nouvelles transactions" (all skipped), on stocke
        # quand même : l'utilisateur a confirmé la synchronisation.
        _persist_import_file(
            tmp_path=tmp_path,
            filename=filename,
            matches=matches,
            balances=balances,
            connector=connector,
            service_results=service_results,
        )

    except Exception as e:
        logger.exception("import_confirm: import failed")
        return _error(request, f"Erreur lors de l'import : {e}")

    finally:
        # Nettoyage : supprimer le fichier temp et la clé session dans tous les cas.
        # Si _persist_import_file a déjà lu le fichier (copy+encrypt), il existe
        # toujours ici — on le supprime. Si une exception a eu lieu avant, pareil.
        if tmp_path.exists():
            os.unlink(tmp_path)
        request.session.pop("pending_import", None)

    # HX-Redirect : HTMX redirige le navigateur vers /import/ (rechargement complet).
    # On n'utilise pas HttpResponseRedirect car la requête est HTMX — la réponse
    # doit être 200 avec le header HX-Redirect, pas un 302 classique.
    response = HttpResponse()
    response["HX-Redirect"] = reverse("imports:upload")
    return response


def _persist_import_file(
    tmp_path, filename, matches, balances, connector, service_results
):
    """
    Chiffre et stocke le fichier d'import dans IMPORT_STORAGE_ROOT, puis
    met à jour les ImportLog avec le chemin et le nom canonique.

    Appelé uniquement depuis import_confirm, après l'écriture en DB.

    On l'extrait dans une fonction séparée pour :
        - garder import_confirm lisible
        - permettre de l'appeler silencieusement (les erreurs de stockage ne
          doivent pas faire échouer un import déjà committé en DB)

    Si le stockage échoue (ex: clé absente, disque plein), on logge l'erreur
    mais on ne lève pas d'exception — l'import est déjà en DB, l'utilisateur
    ne doit pas perdre ses données pour un problème de fichier.
    """
    log_pks = [r.log_pk for r in service_results if r.log_pk]
    if not log_pks:
        # Aucun ImportLog créé (toutes les runs ont échoué tôt) → pas de stockage
        logger.warning(
            "[import_storage] No log_pk found after confirm — skipping file storage."
        )
        return

    try:
        # Récupérer date_min / date_max des transactions insérées dans ces logs.
        # Si 0 nouvelles transactions (all skipped), date_min/date_max seront None
        # → build_import_filename utilisera "nodate" dans le nom.
        agg = Transaction.objects.filter(import_log_id__in=log_pks).aggregate(
            date_min=Min("date"), date_max=Max("date"), n=Count("id")
        )

        bank_slug = matches[0].account.institution.slug

        # Noms de comptes normalisés : espaces → underscores, minuscules
        account_names = [
            m.account.name.lower().replace(" ", "_").replace("/", "_") for m in matches
        ]

        # Première balance disponible (None si aucun connecteur ne l'extrait)
        raw_balance = next(iter(balances.values()), None)
        balance_dec = Decimal(str(raw_balance)) if raw_balance is not None else None

        year = agg["date_max"].year if agg["date_max"] else timezone.now().year

        stored_filename = build_import_filename(
            bank_slug=bank_slug,
            account_names=account_names,
            date_min=agg["date_min"],
            date_max=agg["date_max"],
            balance=balance_dec,
            n_transactions=agg["n"] or 0,
            original_ext=Path(filename).suffix,
        )

        stored_rel, is_enc = save_import_file(
            tmp_path, bank_slug, stored_filename, year
        )

        # Mettre à jour tous les ImportLogs de cet import (CIC → plusieurs logs,
        # même fichier physique → même stored_path dans chaque row).
        ImportLog.objects.filter(pk__in=log_pks).update(
            stored_filename=stored_filename,
            stored_path=str(stored_rel),
            is_encrypted=is_enc,
        )

        logger.info(
            "[import_storage] Saved %s → %s (encrypted=%s)",
            filename,
            stored_rel,
            is_enc,
        )

    except Exception as exc:
        # Le stockage a échoué APRÈS que l'import a été committé en DB.
        # On logge sans crasher : l'utilisateur a ses transactions, le fichier
        # source n'est juste pas archivé. Il peut réimporter depuis l'original.
        logger.error(
            "[import_storage] Failed to persist %s: %s",
            filename,
            exc,
            exc_info=True,
        )


@login_required
def import_log_detail(request, pk):
    """
    Fragment HTMX — chargé dans #panel-content quand on clique sur une ligne.
    """
    log = get_object_or_404(
        ImportLog.objects.select_related("account__institution", "imported_by").filter(
            account__members=request.user
        ),
        pk=pk,
    )
    return render(request, "imports/partials/_import_detail.html", {"log": log})


@login_required
@require_POST
def import_log_delete(request, pk):
    """
    Supprime un ImportLog et toutes ses transactions associées.

    Les transactions liées ont import_log=log (FK settée depuis la migration 0006).
    Les anciennes transactions (import_log=NULL) ne sont pas touchées.

    Flow :
        POST /import/<pk>/delete/
        → Transaction.objects.filter(import_log=log).delete()
        → log.delete()
        → HX-Redirect /import/
    """
    log = get_object_or_404(
        ImportLog.objects.filter(account__members=request.user), pk=pk
    )

    tx_count = log.transactions.count()
    log.transactions.all().delete()
    log.delete()
    logger.info(
        "import_log_delete: log_pk=%s filename=%s tx_deleted=%d by user=%s",
        pk,
        log.filename,
        tx_count,
        request.user.id,
    )

    response = HttpResponse()
    response["HX-Redirect"] = reverse("imports:upload")
    # On passe le count dans un header custom pour un futur toast si besoin
    response["X-Deleted-Count"] = str(tx_count)
    return response


@login_required
@require_POST
def import_create_account(request):
    """
    Crée un Account + CheckingAccount/SavingsAccount depuis le formulaire inline
    affiché quand resolve_accounts() ne trouve pas le compte.

    Après création, relance le dry-run automatiquement (le fichier temp est
    toujours en session) et retourne _steps_result.html comme si de rien n'était.
    """
    bank_slug = request.POST.get("bank_slug", "")
    account_name = request.POST.get("account_name", "").strip()
    account_type = request.POST.get("account_type", "")
    iban = request.POST.get("iban", "").replace(" ", "").upper()
    bic = request.POST.get("bic", "").replace(" ", "").upper()
    contract_number = request.POST.get("contract_number", "")
    currency = request.POST.get("currency", "")

    # Validations minimales
    if not account_name:
        return _error(request, "Le nom du compte est obligatoire.")
    if not iban and not contract_number:
        return _error(
            request,
            "Un identifiant est obligatoire.",
            hint="Renseignez l'IBAN ou le numéro de contrat (RIB pour CIC).",
        )
    if account_type not in dict(Account.AccountType.choices):
        return _error(request, "Type de compte invalide.")

    # La banque doit exister en DB (créée via seed_banks)
    try:
        bank = Institution.objects.get(slug=bank_slug)
    except Institution.DoesNotExist:
        return _error(
            request,
            f"Banque « {bank_slug} » introuvable.",
            hint="Lancez d'abord : python manage.py seed_banks",
        )

    # Créer l'Account + spécialisation dans une transaction atomique
    try:
        with db_transaction.atomic():
            account = Account.objects.create(
                institution=bank,
                name=account_name,
                account_type=account_type,
                currency=currency,
                contract_number=contract_number,
                is_active=True,
            )
            account.members.add(request.user)  # for_user() sinon invisible
            if account_type == Account.AccountType.CHECKING:
                CheckingAccount.objects.create(account=account, iban=iban, bic=bic)
            else:
                SavingsAccount.objects.create(account=account, interest_rate=0)
        # Audit log : compte créé pendant l'import (mutation métier critique).
        logger.info(
            "import_create_account: id=%s bank=%s type=%s by user=%s",
            account.id,
            bank.slug,
            account_type,
            request.user.id,
        )
    except Exception as e:
        logger.exception("import_create_account: account creation failed")
        return _error(request, f"Erreur lors de la création du compte : {e}")

    # Compte créé — relancer le dry-run avec le fichier toujours en session
    # On réutilise _handle_dry_run en simulant un POST avec le fichier déjà uploadé.
    # Mais le fichier est en session (pas re-uploadé) → on relance resolve + dry-run
    # directement depuis ici.
    pending = request.session.get("pending_import")
    if not pending:
        return _error(request, "Session expirée. Recommencez l'import.")

    tmp_path = Path(pending["filepath"])
    if not tmp_path.exists():
        del request.session["pending_import"]
        return _error(request, "Fichier temporaire introuvable. Recommencez l'import.")

    # Relancer le dry-run complet (même logique que _handle_dry_run)
    try:
        connector = detect_connector(tmp_path)
        if connector is None:
            return _error(
                request, "Format de fichier non reconnu. Recommencez l'import."
            )
        matches = resolve_accounts(connector, tmp_path, user=request.user)

        if isinstance(connector, CICConnector):
            sheets_info = {
                s["sheet_name"]: s for s in connector.get_account_sheets(tmp_path)
            }
            balances = {
                match.sheet_name: sheets_info.get(match.sheet_name, {}).get("balance")
                for match in matches
            }
        else:
            raw_balance = connector.extract_balance(tmp_path)
            balances = {None: raw_balance}

        service = ImportService()
        dry_results: list[dict[str, Any]] = []
        file_hash = pending["file_hash"]
        filename = pending["filename"]
        connector_label = type(connector).__name__.replace("Connector", "")

        for match in matches:
            if match.sheet_name is not None:
                transactions = connector.parse_sheet(tmp_path, match.sheet_name)
            else:
                transactions = connector.parse(tmp_path)
            balance = balances.get(match.sheet_name)
            result = service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=filename,
                file_hash=file_hash,
                balance=balance,
                dry_run=True,
            )
            dry_results.append(
                {
                    "account": match.account,
                    "sheet_name": match.sheet_name,
                    "result": result,
                }
            )

        total_created = sum(r["result"].count_created for r in dry_results)
        total_skipped = sum(r["result"].count_skipped for r in dry_results)

        return render(
            request,
            "imports/partials/_steps_result.html",
            {
                "connector_label": connector_label,
                "dry_results": dry_results,
                "total_created": total_created,
                "total_skipped": total_skipped,
                "filename": filename,
            },
        )
    except AccountNotFound as e:
        # Un autre compte est encore manquant (CIC multi-feuilles)
        from accounts.institutions_config import KNOWN_INSTITUTIONS

        bank_config = KNOWN_INSTITUTIONS.get(e.bank_slug, {})
        try:
            bank_obj = Institution.objects.get(slug=e.bank_slug)
        except Institution.DoesNotExist:
            bank_obj = None
        return render(
            request,
            "imports/partials/_steps_create_account.html",
            {
                "bank": bank_obj,
                "bank_slug": e.bank_slug,
                "bank_name": bank_config.get("name", e.bank_slug.upper()),
                "bank_bic": bank_config.get("bic", ""),
                "iban": e.contract_number if e.bank_slug == "ubs" else "",
                "contract_number": e.contract_number,
                "contract_number_raw": e.contract_number_raw,
                "sheet_name": e.sheet_name,
                "currency": bank_config.get("currency", "EUR"),
                "account_types": Account.AccountType.choices,
            },
        )
    except Exception as e:
        logger.exception("imports: dry-run re-trigger failed")
        return _error(request, f"Erreur lors du dry-run : {e}")


@login_required
@require_POST
def import_select_account(request):
    """
    Reçoit le choix de l'utilisateur depuis _steps_account_picker.html.

    Contexte : levée par AccountAmbiguous (Yuh avec plusieurs comptes actifs).
    L'utilisateur a cliqué sur un compte → POST avec account_id.

    Sécurité : on vérifie que l'account_id correspond bien à la banque en session
    (bank_slug stocké lors du catch AccountAmbiguous dans _handle_dry_run).
    Cela empêche de "forcer" un compte d'une autre banque via un POST forgé.

    Après sélection : relance le dry-run complet avec forced_account_id.
    """
    pending = request.session.get("pending_import")
    if not pending:
        return _error(request, "Session expirée. Recommencez l'import.")

    account_id = request.POST.get("account_id", "").strip()
    if not account_id:
        return _error(request, "Aucun compte sélectionné.")

    bank_slug = pending.get("bank_slug", "")
    tmp_path = Path(pending["filepath"])
    filename = pending["filename"]
    file_hash = pending["file_hash"]

    if not tmp_path.exists():
        del request.session["pending_import"]
        return _error(request, "Fichier temporaire introuvable. Recommencez l'import.")

    # Vérification : le compte doit appartenir à la banque attendue ET à l'user.
    # members=request.user empêche un user de forger un POST avec l'account_id
    # d'un autre user (IDOR). institution__slug en session empêche de changer de banque.
    try:
        account = (
            Account.objects.for_user(request.user)
            .select_related("institution")
            .get(
                pk=account_id,
                institution__slug=bank_slug,
                is_active=True,
            )
        )
    except Account.DoesNotExist:
        return _error(
            request,
            "Compte invalide ou inactif.",
            hint="Sélectionnez un compte de la liste.",
        )

    # Relancer le dry-run avec le compte forcé
    try:
        connector = detect_connector(tmp_path)
        if connector is None:
            raise ValueError("Connecteur non détecté.")

        matches = resolve_accounts(
            connector, tmp_path, forced_account_id=account.pk, user=request.user
        )

        raw_balance = connector.extract_balance(tmp_path)
        balances: dict[str | None, float | None] = {None: raw_balance}

        service = ImportService()
        dry_results: list[dict[str, Any]] = []
        connector_label = type(connector).__name__.replace("Connector", "")

        for match in matches:
            transactions = connector.parse(tmp_path)
            balance = balances.get(match.sheet_name)
            result = service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=filename,
                file_hash=_account_file_hash(file_hash, match.sheet_name),
                balance=balance,
                dry_run=True,
            )
            dry_results.append(
                {
                    "account": match.account,
                    "sheet_name": match.sheet_name,
                    "result": result,
                }
            )

        total_created = sum(r["result"].count_created for r in dry_results)
        total_skipped = sum(r["result"].count_skipped for r in dry_results)

        return render(
            request,
            "imports/partials/_steps_result.html",
            {
                "connector_label": connector_label,
                "dry_results": dry_results,
                "total_created": total_created,
                "total_skipped": total_skipped,
                "filename": filename,
            },
        )
    except Exception as e:
        logger.exception("imports: dry-run re-trigger failed")
        return _error(request, f"Erreur lors du dry-run : {e}")


@login_required
def set_period(request, action):
    """
    Met à jour la période et l'offset du graphique d'activité dans la session.

    Si requête HTMX → retourne le partial _activity_section.html (swap sans rechargement).
    Sinon → redirect vers la page d'import (accès direct à l'URL).

    action : "1m" | "3m" | "1y"  → change la période, remet l'offset à 0
             "prev"               → recule d'une fenêtre (offset++)
             "next"               → avance d'une fenêtre (offset--), min 0
    """
    period_mode = request.session.get("import_period_mode", "1y")
    offset = request.session.get("import_period_offset", 0)

    if action in ("1m", "3m", "1y"):
        period_mode = action
        offset = 0
    elif action == "prev":
        offset += 1
    elif action == "next":
        offset = max(0, offset - 1)

    request.session["import_period_mode"] = period_mode
    request.session["import_period_offset"] = offset

    if request.headers.get("HX-Request"):
        return _render_activity_section(request, period_mode, offset, filter_open=False)
    return redirect("imports:upload")


@login_required
def toggle_filter_account(request, account_ref):
    """
    Active/désactive un compte dans le filtre du graphique d'activité.
    account_ref="all"/"0" → réinitialise (aucun masqué = tout visible).
    account_ref="none"    → masque tous les comptes.
    account_ref="<int>"   → toggle le compte spécifique.
    IDOR : le filtrage en DB reste scopé à request.user dans import_upload.

    Blacklist : import_filter_accounts_hidden = IDs des comptes EXCLUS.
    Si requête HTMX → retourne le partial avec filter_open=True (dropdown reste ouvert).
    Sinon → redirect.
    """
    hidden = list(request.session.get("import_filter_accounts_hidden", []))

    if account_ref in ("all", "0"):
        hidden = []
    elif account_ref == "none":
        hidden = list(
            Account.objects.filter(is_active=True, members=request.user).values_list(
                "id", flat=True
            )
        )
    else:
        try:
            account_id = int(account_ref)
        except (ValueError, TypeError):
            account_id = None
        if account_id is not None:
            if account_id in hidden:
                hidden = [i for i in hidden if i != account_id]
            else:
                hidden = hidden + [account_id]

    request.session["import_filter_accounts_hidden"] = hidden

    if request.headers.get("HX-Request"):
        period_mode = request.session.get("import_period_mode", "1y")
        offset = request.session.get("import_period_offset", 0)
        return _render_activity_section(request, period_mode, offset, filter_open=True)
    return redirect("imports:upload")


def _render_activity_section(request, period_mode, period_offset, filter_open=False):
    """
    Construit le contexte du graphique d'activité et retourne le partial
    _activity_section.html (utilisé pour les swaps HTMX depuis set_period
    et toggle_filter_account).
    """
    filter_account_ids = list(request.session.get("import_filter_accounts_hidden", []))

    start_date, end_date, period_display, can_go_next = _activity_window(
        period_mode, period_offset
    )

    tx_qs = Transaction.objects.filter(
        account__members=request.user,
        date__gt=start_date,
        date__lte=end_date,
        is_ignored=False,
    )
    if filter_account_ids:
        tx_qs = tx_qs.exclude(account_id__in=filter_account_ids)

    tx_by_day = list(
        tx_qs.select_related("account__institution")
        .values("date", "account__institution__name")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    seen_bank_names = []
    for row in tx_by_day:
        name = row["account__institution__name"]
        if name not in seen_bank_names:
            seen_bank_names.append(name)

    user_accounts = (
        Account.objects.filter(is_active=True, members=request.user)
        .select_related("institution")
        .order_by("institution__name", "name")
    )

    # Marqueurs d'import dans la fenêtre — mêmes règles IDOR que le chemin full-page.
    import_logs = list(
        ImportLog.objects.filter(
            account__members=request.user,
            imported_at__date__gt=start_date,
            imported_at__date__lte=end_date,
        )
        .select_related("account__institution")
        .order_by("imported_at")
    )
    # Dédupliquer par file_hash (un fichier CIC = N ImportLogs, 1 seul marqueur)
    seen_hashes_m: dict = {}
    import_markers = []
    for log in import_logs:
        key = log.file_hash or log.pk
        if key not in seen_hashes_m:
            seen_hashes_m[key] = True
            import_markers.append(
                {
                    "date": timezone.localtime(log.imported_at).strftime("%Y-%m-%d"),
                    "filename": log.filename or "?",
                    "total": log.count_created,
                    "bank": log.account.institution.name,
                }
            )

    chart_data = {
        "banks": seen_bank_names,
        "logs": [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "bank": row["account__institution__name"],
                "created": row["count"],
                "total": row["count"],
            }
            for row in tx_by_day
        ],
        "import_markers": import_markers,
    }

    return render(
        request,
        "imports/partials/_activity_section.html",
        {
            "chart_data": chart_data,
            "period_mode": period_mode,
            "period_offset": period_offset,
            "period_display": period_display,
            "can_go_next": can_go_next,
            "accounts": user_accounts,
            "filter_account_ids": filter_account_ids,
            "filter_open": filter_open,
        },
    )


def _error(request, message, hint=None, admin_url=None, admin_label=None):
    """Retourne le fragment erreur (réutilisable dans toutes les étapes)."""
    return render(
        request,
        "imports/partials/_steps_error.html",
        {
            "error": message,
            "hint": hint,
            "admin_url": admin_url,
            "admin_label": admin_label,
        },
    )
