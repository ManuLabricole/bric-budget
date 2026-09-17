"""
transactions/management/commands/prototype_merchant_logos.py

PROTOTYPE (#124) — outil de découverte, pas de pipeline de production. Lecture
seule de Transaction.display_name, matching 100% local contre le seed JSON
committé (transactions/reference/merchant_seed.json). N'écrit AUCUN fichier,
AUCUN champ en base : sert à repérer quels display_name distincts manquent
encore d'une entrée seed, pour l'étoffer à la main.

La résolution du logo lui-même (à quelle URL pointer une fois un marchand
matché) vit dans services.merchant_logos — ce n'est PAS le rôle de cette
commande. Depuis le passage à Brandfetch (Logo API, hotlink navigateur live,
#124), il n'y a plus rien à télécharger/cacher côté serveur pour le tier
seed : la commande ne fait plus que matcher + rapporter, elle ne fetch plus
aucun logo (l'ancienne version téléchargeait via Google Favicons — obsolète,
supprimée avec le passage à Brandfetch).

Pipeline :
  1. Transaction.objects.values("display_name").annotate(n=Count("id")) —
     UN SEUL GROUP BY, pas de boucle Python sur les lignes individuelles.
  2. Pour chaque display_name distinct, normalize() puis :
       a. keyword tier  — services.merchant_logos.load_seed(), même règle
          d'ordre/priorité que la résolution live.
       b. fuzzy tier (rapidfuzz) — seulement si (a) n'a rien trouvé.
  3. Récap : matched (keyword) / matched (fuzzy) / non matché + top non-matchés.

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
    python manage.py prototype_merchant_logos                    # top non-matchés
    python manage.py prototype_merchant_logos -v 2                # 1 ligne par display_name distinct
    python manage.py prototype_merchant_logos --min-count 3       # ignore le bruit à occurrence unique
    python manage.py prototype_merchant_logos --fuzzy-threshold 92
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count
from rapidfuzz import fuzz, process

from services.merchant_logos import MerchantSeed, load_seed, normalize
from transactions.models import Transaction

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
    help = "[PROTOTYPE #124] Matche display_name → merchant seed, rapporte les non-matchés."

    def add_arguments(self, parser: CommandParser) -> None:
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

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓  {stats['keyword']} matchés (keyword), {stats['fuzzy']} matchés (fuzzy), "
                f"{stats['unmatched']} non matchés."
            )
        )

        if unmatched_report:
            top_unmatched = sorted(unmatched_report, key=lambda pair: -pair[1])[:20]
            self.stdout.write("")
            self.stdout.write(
                "Top non-matchés (à ajouter au seed ou traiter à la main) :"
            )
            for name, count in top_unmatched:
                self.stdout.write(f"   {count:>4}×  {name}")
