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

import os
import tempfile
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from connectors.cic.parser import CICConnector
from connectors.resolver import detect_connector, resolve_accounts
from transactions.models import ImportLog
from transactions.services import ImportService, compute_file_hash


@login_required
def import_upload(request):
    """
    GET  → formulaire upload + historique des imports passés.
    POST → dry-run : détecte le connecteur, résout le compte, calcule les counts
           sans écrire en DB → retourne le fragment _steps_result.html (HTMX).
    """
    if request.method == "POST":
        return _handle_dry_run(request)

    logs = ImportLog.objects.select_related("account__bank").order_by("-imported_at")
    return render(request, "imports/upload.html", {"logs": logs})


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
        # ImportLog.file_hash est unique en DB → inutile d'aller plus loin.
        file_hash = compute_file_hash(tmp_path)
        if ImportLog.objects.filter(file_hash=file_hash).exists():
            os.unlink(tmp_path)
            return _error(
                request,
                "Ce fichier a déjà été importé.",
                hint="Le contenu correspond à un import existant dans l'historique.",
            )

        # ── Résolution du ou des comptes ─────────────────────────────────────
        try:
            matches = resolve_accounts(connector, tmp_path)
        except Exception as e:
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
        dry_results = []

        for match in matches:
            transactions = connector.parse(tmp_path, **match.parse_kwargs)
            balance = balances.get(match.sheet_name)

            result = service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=uploaded.name,
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

        matches = resolve_accounts(connector, tmp_path)

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

        for match in matches:
            transactions = connector.parse(tmp_path, **match.parse_kwargs)
            balance = balances.get(match.sheet_name)
            service.run(
                transactions=transactions,
                account=match.account,
                imported_by=request.user,
                filename=filename,
                file_hash=file_hash,
                balance=balance,
                dry_run=False,
            )

    except Exception as e:
        return _error(request, f"Erreur lors de l'import : {e}")

    finally:
        # Nettoyage : supprimer le fichier temp et la clé session dans tous les cas
        if tmp_path.exists():
            os.unlink(tmp_path)
        request.session.pop("pending_import", None)

    # HX-Redirect : HTMX redirige le navigateur vers /import/ (rechargement complet).
    # On n'utilise pas HttpResponseRedirect car la requête est HTMX — la réponse
    # doit être 200 avec le header HX-Redirect, pas un 302 classique.
    response = HttpResponse()
    response["HX-Redirect"] = reverse("imports:upload")
    return response


@login_required
def import_log_detail(request, pk):
    """
    Fragment HTMX — chargé dans #panel-content quand on clique sur une ligne.
    """
    log = get_object_or_404(
        ImportLog.objects.select_related("account__bank", "imported_by"), pk=pk
    )
    return render(request, "imports/partials/_import_detail.html", {"log": log})


def _error(request, message, hint=None):
    """Retourne le fragment erreur (réutilisable dans toutes les étapes)."""
    return render(
        request,
        "imports/partials/_steps_error.html",
        {"error": message, "hint": hint},
    )
