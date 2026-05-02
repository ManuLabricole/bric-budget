"""
transactions/management/commands/reset_categories.py

Remet toutes les catégories à zéro selon un critère simple :
    amount > 0  →  Revenus   (slug: revenus)
    amount < 0  →  Inconnu   (slug: inconnu)
    amount == 0 →  Inconnu   (rare, même traitement)

Pourquoi cette commande existe :
    Avant une session de classification manuelle (Phase 2G), on veut
    repartir d'un état propre et déterministe plutôt que d'un mix
    de règles partiellement appliquées.
    Aussi utile après un import CSV d'un nouveau compte.

Ce que la commande fait :
    - category    → revenus ou inconnu selon le signe de amount_chf
    - subcategory → NULL  (reset complet)
    - categorization_source → DEFAULT ("default")

    Elle ne touche PAS aux transactions "ignore" (is_ignored=True).

Usage :
    python src/manage.py reset_categories          # reset réel
    python src/manage.py reset_categories --dry-run  # affiche le compte, n'écrit rien
    make reset-categories
"""

from django.core.management.base import BaseCommand

from transactions.models import Category, Transaction


class Command(BaseCommand):
    help = "Remet toutes les catégories à zéro : positif → Revenus, négatif → Inconnu"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le nombre de transactions concernées sans modifier la DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # ── 1. Charger les deux catégories cibles ─────────────────────────
        # On récupère par slug (clé métier stable) plutôt que par ID (technique).
        # Si l'une des deux est absente, la commande refuse de continuer.
        try:
            cat_revenus = Category.objects.get(slug="revenus")
            cat_inconnu = Category.objects.get(slug="inconnu")
        except Category.DoesNotExist as exc:
            self.stderr.write(
                self.style.ERROR(
                    f"Catégorie introuvable : {exc}. Avez-vous lancé `make seed` ?"
                )
            )
            return

        # ── 2. Construire les deux querysets ──────────────────────────────
        # On utilise amount_chf (montant normalisé en CHF) pour le signe,
        # pas amount (qui peut être en EUR ou GBP selon le compte).
        # is_ignored=True → on ne touche pas aux transactions délibérément exclues.
        base_qs = Transaction.objects.filter(is_ignored=False)
        qs_revenus = base_qs.filter(amount_chf__gt=0)
        qs_inconnu = base_qs.filter(amount_chf__lte=0)

        count_revenus = qs_revenus.count()
        count_inconnu = qs_inconnu.count()
        total = count_revenus + count_inconnu

        self.stdout.write(
            f"  Transactions à reclassifier : {total}\n"
            f"    → Revenus (amount > 0) : {count_revenus}\n"
            f"    → Inconnu (amount ≤ 0) : {count_inconnu}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n  [dry-run] Aucune modification effectuée.")
            )
            return

        # ── 3. Mise à jour en masse ───────────────────────────────────────
        # bulk_update sur queryset = un seul UPDATE SQL par lot, pas de boucle Python.
        # On met à jour 3 champs : category, subcategory (→ NULL), categorization_source.
        # subcategory=None → NULL en SQL car le champ est nullable (blank=True, null=True).
        updated_revenus = qs_revenus.update(
            category=cat_revenus,
            subcategory=None,
            categorization_source=Transaction.CategorizationSource.DEFAULT,
        )
        updated_inconnu = qs_inconnu.update(
            category=cat_inconnu,
            subcategory=None,
            categorization_source=Transaction.CategorizationSource.DEFAULT,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Reset terminé : {updated_revenus + updated_inconnu} transactions mises à jour.\n"
                f"    ✓ {updated_revenus} → Revenus\n"
                f"    ✓ {updated_inconnu} → Inconnu"
            )
        )
