"""
imports/management/commands/dev_parse.py — inspecter et comparer les parsers.

Usage :
    python manage.py dev_parse <fichier|dossier> [...]        rapport détaillé
    python manage.py dev_parse <f1> <f2> ... --compare        tableau comparatif
    python manage.py dev_parse <fichier> --sample 20          plus d'exemples
    python manage.py dev_parse <fichier> --pick longest       quels exemples
    python manage.py dev_parse <fichier> --grep 'GBP|USD'     filtrer les exemples

À quoi elle sert, et ce qu'elle n'est pas
------------------------------------------
Les commandes `import_*` comptent des lignes écrites en base : Created / Skipped
/ Errors. Elles n'affichent JAMAIS une transaction — on ne voit ni le libellé
nettoyé, ni le marchand, ni le hash. Elles exigent en plus un compte configuré
en base : impossible de s'en servir pour développer un connecteur neuf.

Celle-ci s'arrête à `connector.parse()`. Aucune base, aucun réseau, aucune
écriture. Elle sert à VOIR ce que le parser produit et à COMPARER les banques
entre elles — la question « mon nettoyage de libellé est-il bon ? » n'a pas de
réponse binaire, elle a une distribution.

⚠️ Elle n'est pas un test. Un test garde un invariant ; celle-ci explore. Quand
elle révèle un défaut, on écrit le test qui l'empêche de revenir.

Elle imprime des libellés bancaires bruts → réservée au DEBUG (garde dev).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.resolver import CONNECTORS, detect_connector
from imports.inspection import ParseProfile, hash_drift, mask_identifier, profile
from transactions.management._dev_guard import assert_dev_environment

# Extensions candidates quand on parcourt un dossier. Les .enc sont les archives
# CHIFFRÉES produites par l'import : ce sont des sorties, pas des entrées.
SCANNED_SUFFIXES = {".csv", ".xlsx"}


class Command(BaseCommand):
    help = (
        "Inspecte la sortie des parsers (qualité d'extraction, hash) et compare "
        "les banques entre elles. Lecture seule : ni base, ni réseau."
    )

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="Fichiers et/ou dossiers.")
        parser.add_argument(
            "--sample", type=int, default=8, help="Lignes d'exemple (0 = aucune)."
        )
        parser.add_argument(
            "--pick",
            choices=["uncleaned", "longest", "head"],
            default="uncleaned",
            help=(
                "Quelles lignes montrer. « uncleaned » (défaut) = celles dont le "
                "display_name est resté identique au brut : les plus instructives."
            ),
        )
        parser.add_argument(
            "--grep", default=None, help="Filtre regex sur le libellé brut."
        )
        parser.add_argument(
            "--compare",
            action="store_true",
            help="Tableau comparatif entre tous les fichiers donnés.",
        )
        parser.add_argument(
            "--full", action="store_true", help="Ne pas abréger les colonnes."
        )

    # =========================================================================

    def handle(self, *args, **options):
        assert_dev_environment("dev_parse", allow_force=False)

        files = self._collect(options["paths"])
        if not files:
            raise CommandError("Aucun fichier à inspecter.")

        parsed = [self._parse_one(path) for path in files]
        recognised = [p for p in parsed if p[1] is not None]

        for path, connector, transactions, elapsed in parsed:
            if connector is None:
                self._report_unknown(path)
            elif not options["compare"]:
                self._report_file(path, connector, transactions, elapsed, options)

        if options["compare"] and recognised:
            self._report_comparison(recognised)

    # =========================================================================
    # Collecte et parsing
    # =========================================================================

    def _collect(self, paths: list[str]) -> list[Path]:
        found: list[Path] = []
        for raw in paths:
            path = Path(raw)
            if path.is_file():
                found.append(path)
            elif path.is_dir():
                found.extend(
                    sorted(
                        p
                        for p in path.rglob("*")
                        if p.is_file()
                        and p.suffix.lower() in SCANNED_SUFFIXES
                        and not p.name.startswith(".")
                    )
                )
            else:
                raise CommandError(f"Introuvable : {path}")
        return found

    def _parse_one(self, path: Path):
        """(chemin, connecteur|None, transactions, durée). Ne lève jamais."""
        connector = detect_connector(path)
        if connector is None:
            return (path, None, [], 0.0)
        started = time.monotonic()
        try:
            transactions = connector.parse(path)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"{path.name}: parse a levé — {exc}"))
            transactions = []
        return (path, connector, transactions, time.monotonic() - started)

    # =========================================================================
    # Rapport : fichier non reconnu (le mode « j'écris un connecteur »)
    # =========================================================================

    def _report_unknown(self, path: Path) -> None:
        """
        Aucun connecteur ne reconnaît le fichier → on montre de quoi en écrire un.

        C'est le cas de départ d'une nouvelle banque : plutôt qu'un « format non
        reconnu » sec, on affiche l'en-tête et quelques lignes, seuls éléments
        dont on a besoin pour rédiger matches_file() et la signature de colonnes.
        """
        self.stdout.write(self.style.WARNING(f"\n▸ {path.name}"))
        self.stdout.write(
            "  connecteur : AUCUN — matches_file() a répondu False : "
            + ", ".join(type(c).__name__.replace("Connector", "") for c in CONNECTORS)
        )
        if path.suffix.lower() != ".csv":
            return
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                lines = [next(f, "").rstrip("\r\n") for _ in range(4)]
        except OSError as exc:
            self.stdout.write(f"  illisible : {exc}")
            return

        self.stdout.write("  aperçu brut :")
        for i, line in enumerate(lines):
            if line:
                self.stdout.write(f"    {i + 1} │ {line[:150]}")
        header = lines[0].split(",")
        self.stdout.write(f"  → {len(header)} colonnes détectées (séparateur « , »)")

    # =========================================================================
    # Rapport : un fichier reconnu
    # =========================================================================

    def _report_file(self, path, connector, transactions, elapsed, options) -> None:
        name = type(connector).__name__
        prof = profile(path.name, name, transactions)

        self.stdout.write(self.style.SUCCESS(f"\n▸ {path.name}"))
        self.stdout.write(
            f"  {name}   institution={connector.INSTITUTION_SLUG}   "
            f"identity_field={connector.IDENTITY_FIELD}   parse {elapsed:.2f}s"
        )

        identifier = connector.extract_account_identifier(path)
        self.stdout.write(
            f"  identité  {mask_identifier(identifier)}     "
            f"solde extrait {connector.extract_balance(path)}"
        )

        if options["sample"]:
            self._render_sample(transactions, options)
        self._render_quality(prof)
        self._render_hash(prof)

        if prof.contract_issues:
            self.stdout.write(
                self.style.ERROR("  CONTRAT TransactionDict — anomalies :")
            )
            for issue in prof.contract_issues:
                self.stdout.write(self.style.ERROR(f"    {issue}"))

    def _render_sample(self, transactions, options) -> None:
        rows = transactions
        if options["grep"]:
            pattern = re.compile(options["grep"], re.IGNORECASE)
            rows = [tx for tx in rows if pattern.search(tx["description_raw"])]

        if options["pick"] == "uncleaned":
            picked = [
                tx for tx in rows if tx["display_name"] == tx["description_raw"]
            ] or rows
        elif options["pick"] == "longest":
            picked = sorted(rows, key=lambda tx: -len(tx["display_name"]))
        else:
            picked = rows

        picked = picked[: options["sample"]]
        if not picked:
            return

        width = 200 if options["full"] else 42
        self.stdout.write("")
        self.stdout.write(
            f"  ÉCHANTILLON  (--pick {options['pick']})"
            "        brut  →  display_name        [carte]"
        )
        for tx in picked:
            same = "=" if tx["merchant_name"] == tx["display_name"] else "≠"
            self.stdout.write(
                f"    {tx['date']}  {tx['amount']:>10.2f}  "
                f"{tx['description_raw'][:width]:<{width}} → "
                f"{tx['display_name'][:width]:<{width}} {same} "
                f"{tx['card_last_four'] or '—'}"
            )

    def _render_quality(self, p: ParseProfile) -> None:
        def line(label: str, r, flag: str = "") -> None:
            self.stdout.write(f"    {label:<34} {r.count:>6}  {r.pct:>5.1f} %  {flag}")

        self.stdout.write("")
        self.stdout.write(
            f"  QUALITÉ D'EXTRACTION      ({p.n_transactions} transactions)"
        )
        line("display_name vide", p.display_empty, "⚠" if p.display_empty.count else "")
        line(
            "display_name == description_raw",
            p.display_equals_raw,
            "← nettoyage sans effet" if p.display_equals_raw.pct > 50 else "",
        )
        line("display_name > 60 caractères", p.display_too_long)
        line("card_last_four", p.with_card)
        line("time", p.with_time)
        line("balance_after", p.with_balance)
        line("merchant_name != display_name", p.merchant_differs)
        self.stdout.write(
            f"    {'longueur display':<34} "
            f"moy {p.len_mean:.1f}   p95 {p.len_p95}   max {p.len_max}"
        )
        self.stdout.write(
            f"    {'canonicalisation':<34} "
            f"{p.distinct_raw} bruts → {p.distinct_display} distincts "
            f"({p.canonicalisation_pct:+.1f} %)"
        )
        self.stdout.write(f"    {'devises':<34} {p.currencies}")
        self.stdout.write(f"    {'période':<34} {p.date_min} → {p.date_max}")

    def _render_hash(self, p: ParseProfile) -> None:
        flag = (
            self.style.SUCCESS("✓") if not p.hash_collisions else self.style.ERROR("✗")
        )
        self.stdout.write(
            f"    {'hash':<34} {p.hash_distinct} distincts / {p.n_transactions}   "
            f"collisions {p.hash_collisions} {flag}"
        )

    # =========================================================================
    # Rapport : comparaison
    # =========================================================================

    def _report_comparison(self, recognised) -> None:
        """
        Tableau comparatif — et, si deux fichiers partagent le même connecteur,
        contrôle de dérive de hash entre eux.
        """
        profiles = [
            profile(path.name, type(connector).__name__, transactions)
            for path, connector, transactions, _ in recognised
        ]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"COMPARAISON — {len(profiles)} fichiers"))
        headers = [p.connector.replace("Connector", "") for p in profiles]
        self.stdout.write(f"  {'':<32}" + "".join(f"{h:>16}" for h in headers))

        def row(label, values):
            self.stdout.write(f"  {label:<32}" + "".join(f"{v:>16}" for v in values))

        row("fichier", [p.label[:15] for p in profiles])
        row("transactions", [p.n_transactions for p in profiles])
        row("display == raw", [f"{p.display_equals_raw.pct:.1f} %" for p in profiles])
        row("display vide", [f"{p.display_empty.pct:.1f} %" for p in profiles])
        row("longueur moy", [f"{p.len_mean:.1f}" for p in profiles])
        row("canonicalisation", [f"{p.canonicalisation_pct:+.1f} %" for p in profiles])
        row("card_last_four", [f"{p.with_card.pct:.1f} %" for p in profiles])
        row("time", [f"{p.with_time.pct:.1f} %" for p in profiles])
        row("balance_after", [f"{p.with_balance.pct:.1f} %" for p in profiles])
        row("hash collisions", [p.hash_collisions for p in profiles])

        self._report_drift(recognised)

    def _report_drift(self, recognised) -> None:
        """Stabilité du hash entre deux exports du même connecteur qui se recouvrent."""
        by_connector: dict[str, list] = {}
        for path, connector, transactions, _ in recognised:
            by_connector.setdefault(type(connector).__name__, []).append(
                (path, transactions)
            )

        for name, entries in by_connector.items():
            if len(entries) < 2:
                continue
            self.stdout.write("")
            self.stdout.write(f"  DÉRIVE DE HASH — {name}")
            for i in range(len(entries) - 1):
                (path_a, tx_a), (path_b, tx_b) = entries[i], entries[i + 1]
                drift = hash_drift(tx_a, tx_b)
                if not drift.common:
                    self.stdout.write(
                        f"    {path_a.name} ∩ {path_b.name} : aucun recouvrement"
                    )
                    continue
                mark = "✓" if drift.is_stable else "✗"
                self.stdout.write(
                    f"    {path_a.name} ∩ {path_b.name} : {drift.common} communes, "
                    f"{drift.same_hash} même hash {mark}   "
                    f"(propres : {drift.only_a} / {drift.only_b})"
                )
                for date, label, ha, hb in drift.diverging:
                    self.stdout.write(
                        self.style.ERROR(f"      {date} {label} : {ha}… ≠ {hb}…")
                    )
