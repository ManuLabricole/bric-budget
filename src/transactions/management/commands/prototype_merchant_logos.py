"""
transactions/management/commands/prototype_merchant_logos.py

PROTOTYPE (#124) — mesurer avant de construire le vrai modèle Merchant/MerchantAlias.
N'écrit AUCUN champ en base, ne crée AUCUNE table : lecture seule de
Transaction.display_name, matching 100% local contre un seed JSON committé
(transactions/reference/merchant_seed.json), puis téléchargement du logo via
services.logos (Google Favicons) — donc SEUL le domaine (jamais la description
brute d'une transaction) part vers un tiers.

Le matching keyword (load_seed/MerchantSeed) vit dans services.merchant_logos —
c'est le MÊME code que celui utilisé en live par budget/views/transactions.py
pour résoudre le badge logo marchand. Cette commande n'ajoute que ce qui lui est
propre : le fuzzy tier (exploration CLI, jamais branché en live, voir NOTE) et
la boucle de téléchargement/rapport en masse.

Pipeline :
  1. Transaction.objects.values("display_name").annotate(n=Count("id")) —
     UN SEUL GROUP BY, pas de boucle Python sur les lignes individuelles.
  2. Pour chaque display_name distinct, normalize() puis :
       a. keyword tier  — services.merchant_logos.load_seed(), même règle
          d'ordre/priorité que la résolution live.
       b. fuzzy tier (rapidfuzz) — seulement si (a) n'a rien trouvé.
  3. Match + logo absent → services.logos.fetch_logo(domain, dest).
  4. Récap : matched (keyword) / matched (fuzzy) / non matché.

NOTE choix librairie fuzzy : rapidfuzz plutôt que fuzzywuzzy/thefuzz — implémentation
C++ (rapide sur 2000+ display_name distincts), licence MIT (fuzzywuzzy est GPL via
sa dépendance python-Levenshtein), API quasi identique. Scorer token_set_ratio :
insensible à l'ordre des mots et aux mots en trop, ce qui correspond au bruit
habituel autour d'un nom de marque ("LA TRONCHE DECATHLON 0030") — MAIS produit
aussi un faux positif net mesuré ici ("PARKING" → APCOA Parking, score 100 dès
qu'un mot générique est un sous-ensemble de tokens de l'autre côté). C'est
pourquoi le fuzzy reste CLI-only : services.merchant_logos.get_merchant_logo_map
(résolution live) n'utilise QUE le keyword tier.

Usage :
    python manage.py prototype_merchant_logos                    # dry-run (aucun fichier écrit)
    python manage.py prototype_merchant_logos --apply             # télécharge réellement les logos
    python manage.py prototype_merchant_logos --apply -v 2         # 1 ligne par transaction distincte
    python manage.py prototype_merchant_logos --min-count 3        # ignore le bruit à occurrence unique
    python manage.py prototype_merchant_logos --apply --apply-fuzzy --fuzzy-threshold 92
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count
from rapidfuzz import fuzz, process

from services import logos
from services.merchant_logos import MerchantSeed, load_seed, normalize
from transactions.models import Transaction

LOGO_DEST_DIR = Path(settings.BASE_DIR) / "static" / "icons" / "merchants"

DEFAULT_FUZZY_THRESHOLD = 90


def match_keyword(normalized: str, seeds: list[MerchantSeed]) -> MerchantSeed | None:
    """Premier seed dont un mot-clé apparaît (frontières de mots) — ordre = priorité."""
    for seed in seeds:
        if seed.pattern.search(normalized):
            return seed
    return None


def match_fuzzy(
    normalized: str, seeds: list[MerchantSeed], threshold: int
) -> tuple[MerchantSeed, float] | None:
    """Fallback flou (rapidfuzz) quand aucun mot-clé exact ne matche."""
    choices = [seed.name.upper() for seed in seeds]
    result = process.extractOne(
        normalized, choices, scorer=fuzz.token_set_ratio, score_cutoff=threshold
    )
    if result is None:
        return None
    _choice, score, index = result
    return seeds[index], score


class Command(BaseCommand):
    help = "[PROTOTYPE #124] Matche display_name → merchant seed + télécharge les logos manquants."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Télécharge réellement les logos (défaut : dry-run, aucun fichier écrit).",
        )
        parser.add_argument(
            "--apply-fuzzy",
            action="store_true",
            help="Télécharge aussi les logos matchés par la tier fuzzy (défaut : keyword tier only).",
        )
        parser.add_argument(
            "--fuzzy-threshold",
            type=int,
            default=DEFAULT_FUZZY_THRESHOLD,
            help=f"Score minimal rapidfuzz pour un match flou (défaut : {DEFAULT_FUZZY_THRESHOLD}).",
        )
        parser.add_argument(
            "--min-count",
            type=int,
            default=1,
            help="Ignore les display_name vus moins de N fois (défaut : 1, aucun filtre).",
        )

    def handle(self, *args, **options) -> None:
        seeds = load_seed()
        apply = options["apply"]
        apply_fuzzy = options["apply_fuzzy"]
        threshold = options["fuzzy_threshold"]
        min_count = options["min_count"]
        verbosity = options["verbosity"]

        rows = (
            Transaction.objects.filter(amount__lt=0)
            .values("display_name")
            .annotate(n=Count("id"))
            .filter(n__gte=min_count)
            .order_by("-n")
        )

        stats = {"keyword": 0, "fuzzy": 0, "unmatched": 0}
        fetched = skipped = failed = 0
        unmatched_report: list[tuple[str, int]] = []

        for row in rows:
            display_name = row["display_name"]
            count = row["n"]
            normalized = normalize(display_name)

            seed = match_keyword(normalized, seeds)
            tier = "keyword"
            score = None
            if seed is None:
                fuzzy_result = match_fuzzy(normalized, seeds, threshold)
                if fuzzy_result is not None:
                    seed, score = fuzzy_result
                    tier = "fuzzy"

            if seed is None:
                stats["unmatched"] += 1
                unmatched_report.append((display_name, count))
                if verbosity >= 2:
                    self.stdout.write(
                        f"  ❔  {display_name!r} (n={count}) — non matché"
                    )
                continue

            stats[tier] += 1
            score_suffix = f" score={score:.0f}" if score is not None else ""
            if verbosity >= 2:
                self.stdout.write(
                    f"  ✓  {display_name!r} (n={count}) → {seed.name} "
                    f"[{tier}{score_suffix}] domain={seed.domain}"
                )

            should_fetch = apply and (tier == "keyword" or apply_fuzzy)
            if not should_fetch:
                continue

            dest = LOGO_DEST_DIR / f"{seed.key}.png"
            if dest.is_file():
                skipped += 1
                continue

            result = logos.fetch_logo(seed.domain, dest)
            if result is None:
                failed += 1
                self.stderr.write(f"  ❌  logo {seed.name} ({seed.domain}) — échec")
            else:
                fetched += 1
                self.stdout.write(
                    f"  ✅  logo {seed.name} → {dest.relative_to(settings.BASE_DIR)}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {stats['keyword']} matchés (keyword), {stats['fuzzy']} matchés (fuzzy), "
                f"{stats['unmatched']} non matchés."
            )
        )
        if apply:
            self.stdout.write(
                f"   logos : {fetched} téléchargé(s), {skipped} déjà présent(s), {failed} échec(s)."
            )
        else:
            self.stdout.write(
                "   dry-run — relancer avec --apply pour télécharger les logos."
            )

        if unmatched_report:
            top_unmatched = sorted(unmatched_report, key=lambda pair: -pair[1])[:20]
            self.stdout.write("")
            self.stdout.write(
                "Top non-matchés (à ajouter au seed ou traiter à la main) :"
            )
            for name, count in top_unmatched:
                self.stdout.write(f"   {count:>4}×  {name}")
