"""
imports/views.py — Upload et traitement de fichiers bancaires via l'interface web.

Vues :

    import_upload(request)   — Page principale : formulaire + liste des imports passés
    import_log_detail(request, pk) — Fragment HTMX : détail d'un ImportLog (right panel)

Phase 2F Session 1 : vues stub — logique upload à implémenter en Session 2.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from transactions.models import ImportLog


@login_required
def import_upload(request):
    """
    GET → affiche le formulaire upload + liste des imports passés.

    Les imports sont triés par date décroissante : le plus récent en tête.
    select_related("account__bank") évite N+1 : chaque row de la liste
    affiche account.name et account.bank.name — 2 FK traversées → 1 seule query.
    """
    logs = ImportLog.objects.select_related("account__bank").order_by("-imported_at")
    return render(request, "imports/upload.html", {"logs": logs})


@login_required
def import_log_detail(request, pk):
    """
    Fragment HTMX — chargé dans #panel-content quand on clique sur une ligne.

    get_object_or_404 : retourne 404 si le log n'existe pas (URL tapée à la main).
    select_related("account__bank", "imported_by") : évite 2 queries supplémentaires
    pour afficher le nom de la banque et de l'utilisateur dans le panel détail.
    """
    log = get_object_or_404(
        ImportLog.objects.select_related("account__bank", "imported_by"), pk=pk
    )
    return render(request, "imports/partials/_import_detail.html", {"log": log})
