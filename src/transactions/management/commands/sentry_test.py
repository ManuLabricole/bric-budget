"""
transactions/management/commands/sentry_test.py — vérifier le pipeline Sentry (#259).

À lancer LÀ où SENTRY_DSN est défini (Console Railway en prod) :
    poetry run python manage.py sentry_test           # envoie un message d'erreur
    poetry run python manage.py sentry_test --raise   # lève une vraie exception

→ un event apparaît dans le dashboard Sentry ⇒ la capture d'erreurs marche de bout en
bout (DSN valide, before_send/scrub OK). Pas de route de debug en prod : on déclenche
à la demande via une commande, jamais via une URL publique. Si SENTRY_DSN est absente
(dev/CI), la commande ne fait rien et le dit.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Envoie un event de test à Sentry pour vérifier la capture d'erreurs."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument(  # type: ignore[attr-defined]
            "--raise",
            action="store_true",
            dest="do_raise",
            help="Lève une vraie exception (capture_exception) au lieu d'un message.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if not getattr(settings, "SENTRY_DSN", ""):
            self.stdout.write(
                self.style.WARNING(
                    "SENTRY_DSN absente → Sentry désactivé (dev/CI). Rien envoyé. "
                    "Lance cette commande là où SENTRY_DSN est défini (prod)."
                )
            )
            return

        import sentry_sdk

        if options.get("do_raise"):
            try:
                raise RuntimeError(
                    "Sentry test — exception volontaire (sentry_test --raise)"
                )
            except RuntimeError:
                event_id = sentry_sdk.capture_exception()
        else:
            event_id = sentry_sdk.capture_message(
                "Sentry test — message volontaire (manage.py sentry_test)",
                level="error",
            )
        sentry_sdk.flush(timeout=10)
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Event envoyé à Sentry (id={event_id}). Vérifie le dashboard."
            )
        )
