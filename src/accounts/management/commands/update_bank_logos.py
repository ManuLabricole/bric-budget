# accounts/management/commands/update_bank_logos.py
#
# Télécharge les logos des banques depuis Google Favicons API et les stocke
# dans static/icons/banks/miniature/<icon_slug>.png
#
# Usage :
#   make update-bank-logos               → toutes les banques avec un domain
#   python manage.py update_bank_logos   → idem
#
# Prérequis : Bank.domain doit être renseigné en admin ou via le seed.
# API : https://www.google.com/s2/favicons?domain=<domain>&sz=128
#   - Gratuit, sans clé API
#   - Retourne toujours une image (parfois un globe générique si pas trouvé)
#   - sz=128 : taille 128x128px

import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import Institution


class Command(BaseCommand):
    help = (
        "Télécharge les logos banques depuis Google Favicons et les stocke localement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bank",
            type=str,
            default=None,
            help="Slug de la banque à mettre à jour (ex: yuh). Défaut : toutes.",
        )
        parser.add_argument(
            "--size",
            type=int,
            default=128,
            help="Taille du logo en pixels (défaut : 128).",
        )

    def handle(self, *args, **options):
        target_slug = options["bank"]
        size = options["size"]

        icon_dir = Path(settings.BASE_DIR) / "static" / "icons" / "banks" / "miniature"
        icon_dir.mkdir(parents=True, exist_ok=True)

        banks = Institution.objects.all()
        if target_slug:
            banks = banks.filter(slug=target_slug)
            if not banks.exists():
                self.stderr.write(f"Banque '{target_slug}' introuvable.")
                return

        for bank in banks:
            if not bank.domain:
                self.stdout.write(f"  ⏭  {bank.name} — domain vide, ignoré")
                continue

            if not bank.icon_slug:
                self.stdout.write(f"  ⏭  {bank.name} — icon_slug vide, ignoré")
                continue

            # Validation : bank.domain doit ressembler à un domaine (lettres/chiffres/.-)
            # → empêche injection de path ou scheme arbitraire dans l'URL construite.
            import re

            if not re.fullmatch(r"[a-z0-9.-]+", bank.domain or ""):
                self.stderr.write(
                    f"  ❌  {bank.name} — domain invalide : {bank.domain!r}"
                )
                continue
            url = f"https://www.google.com/s2/favicons?domain={bank.domain}&sz={size}"
            dest = icon_dir / f"{bank.icon_slug}.png"

            try:
                # nosec B310 : URL avec scheme https hardcodé + domain validé regex ci-dessus.
                urllib.request.urlretrieve(url, dest)  # nosec B310
                size_kb = dest.stat().st_size // 1024
                self.stdout.write(
                    f"  ✅  {bank.name} ({bank.domain}) → {dest.name} ({size_kb}kb)"
                )
            except Exception as e:
                self.stderr.write(f"  ❌  {bank.name} — erreur : {e}")

        self.stdout.write(self.style.SUCCESS("Logos mis à jour."))
