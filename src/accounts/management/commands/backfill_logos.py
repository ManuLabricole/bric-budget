"""
accounts/management/commands/backfill_logos.py

One-shot dev : récupère les logos MANQUANTS de toutes les Institutions via le
micro-service services/logos.py (Google Favicons, domain → png).

Remplace update_bank_logos. Différences :
    - ne télécharge que les logos ABSENTS (svg/ ou miniature/) — idempotent ;
      --force pour re-télécharger quand même
    - même fallback de slug que le tag institution_icon_url (icon_slug sinon slug)
    - un échec ne stoppe pas le backfill des suivantes

Au fil de l'eau, c'est le post_save Institution (accounts/signals.py) qui fait
le même travail à la création/modification — cette commande sert au one-shot
initial et à la réparation.

Usage :
    python manage.py backfill_logos                      # tous les manquants
    python manage.py backfill_logos --institution yuh    # une seule
    python manage.py backfill_logos --force              # re-télécharge tout
"""

from django.core.management.base import BaseCommand

from accounts.models import Institution
from services import logos


class Command(BaseCommand):
    help = "Télécharge les logos manquants des institutions (services/logos.py)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--institution",
            type=str,
            default=None,
            help="Slug d'une institution à traiter (défaut : toutes).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-télécharge même si un logo existe déjà.",
        )
        parser.add_argument(
            "--size",
            type=int,
            default=logos.DEFAULT_SIZE,
            help=f"Taille du logo en pixels (défaut : {logos.DEFAULT_SIZE}).",
        )

    def handle(self, *args, **options):
        qs = Institution.objects.order_by("slug")
        if options["institution"]:
            qs = qs.filter(slug=options["institution"])
            if not qs.exists():
                self.stderr.write(
                    f"Institution '{options['institution']}' introuvable."
                )
                return

        base = logos.institutions_icon_base()
        fetched = skipped = failed = 0

        for inst in qs:
            if not inst.domain:
                skipped += 1
                self.stdout.write(f"  ⏭  {inst.name} — domain vide, ignoré")
                continue

            # Même fallback que institution_icon_url : icon_slug, sinon slug.
            slug = inst.icon_slug or inst.slug

            if not options["force"] and logos.has_logo(slug, base):
                skipped += 1
                continue

            dest = base / "miniature" / f"{slug}.png"
            result = logos.fetch_logo(inst.domain, dest, size=options["size"])
            if result is None:
                failed += 1
                self.stderr.write(f"  ❌  {inst.name} ({inst.domain}) — échec")
            else:
                fetched += 1
                self.stdout.write(f"  ✅  {inst.name} ({inst.domain}) → {dest.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {fetched} téléchargé(s), {skipped} ignoré(s), {failed} échec(s)."
            )
        )
