"""
imports/views.py — Upload et traitement de fichiers bancaires via l'interface web.

Deux vues principales :

    import_upload(request)
        GET  → formulaire d'upload (drag & drop)
        POST → dry-run via resolver + ImportService → retourne un fragment HTMX
               avec le résumé "N transactions à créer, compte détecté : Yuh CHF"
               + bouton "Confirmer l'import"

    import_confirm(request)
        POST → ré-exécute l'import avec COMMIT=True → retourne fragment résultat final

Le fichier uploadé est temporairement stocké dans /tmp pendant la session dry-run.
Il est supprimé après confirmation ou abandon (timeout session).

Phase 2F Session 1 : stub uniquement — vues à implémenter en Session 2.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def import_upload(request):
    """
    Page principale d'import.

    GET  → affiche le formulaire upload.
    POST → dry-run (non implémenté — Phase 2F Session 2).
    """
    return render(request, "imports/upload.html")
