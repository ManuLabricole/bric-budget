"""
imports/inspection.py — mesures de qualité sur la sortie d'un parser.

Fonctions PURES : elles reçoivent une liste de TransactionDict et renvoient des
mesures. Aucun accès base, aucun réseau, aucun rendu terminal — c'est ce qui les
rend testables, et c'est là que porte la couverture. Le rendu ANSI vit dans la
commande `dev_parse`, qui n'a aucune logique.

À quoi ça sert
--------------
Les tests de `tests/connectors/` gardent des invariants BINAIRES sur des fixtures
de 3 à 8 lignes : le hash est unique, la date est ISO, le débit est négatif. Ils
ne disent rien de la QUALITÉ du texte extrait sur des milliers de lignes réelles :
un `display_name` qui vaut « 7,69 GBP SPINNING JENNY T » passe tous les tests et
reste un mauvais nom de marchand.

Ce module mesure des DISTRIBUTIONS, pas des booléens. Il sert à explorer et à
comparer ; quand il révèle un défaut, on écrit le test qui l'empêche de revenir.
Il ne remplace jamais un test.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from connectors.base import TransactionDict

# Longueur au-delà de laquelle un display_name cesse d'être lisible dans l'UI.
# La colonne DB accepte 300 caractères ; le seuil ici est ergonomique, pas technique.
LONG_NAME_THRESHOLD = 60


def mask_identifier(value: str | None) -> str:
    """
    Tronque un identifiant avant affichage (SR-008).

    Les libellés bancaires réels encastrent des numéros de compte — ceux de TSB
    exposent le sort code et le compte d'épargne du titulaire en clair. Tout ce
    qui sort de ce module peut finir dans un copier-coller ou un ticket.
    """
    if not value:
        return "—"
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "…"


@dataclass(frozen=True)
class Ratio:
    """Un compte et sa part du total — pour n'écrire la division qu'une fois."""

    count: int
    total: int

    @property
    def pct(self) -> float:
        return 100.0 * self.count / self.total if self.total else 0.0


@dataclass(frozen=True)
class ParseProfile:
    """Portrait chiffré de ce qu'un parser a produit sur un fichier."""

    label: str
    connector: str
    n_transactions: int

    # Qualité du nettoyage de libellé
    display_empty: Ratio
    display_equals_raw: Ratio
    display_too_long: Ratio
    len_mean: float
    len_p95: int
    len_max: int
    distinct_raw: int
    distinct_display: int
    merchant_differs: Ratio

    # Champs optionnels du contrat TransactionDict
    with_card: Ratio
    with_time: Ratio
    with_balance: Ratio

    currencies: dict[str, int]
    date_min: str
    date_max: str

    # Intégrité du hash
    hash_distinct: int
    hash_collisions: int

    # Manquements au contrat (clés absentes, types inattendus)
    contract_issues: list[str] = field(default_factory=list)

    @property
    def canonicalisation_pct(self) -> float:
        """
        Réduction du nombre de libellés distincts par le nettoyage.

        C'est LA mesure qui dit si un connecteur canonicalise vraiment : 458
        libellés bruts ramenés à 143 noms distincts (-69 %) signifie que le
        parser reconnaît les marchands récurrents. 0 % signifie qu'il recopie.
        """
        if not self.distinct_raw:
            return 0.0
        return 100.0 * (1 - self.distinct_display / self.distinct_raw)


def _percentile(values: list[int], p: float) -> int:
    """Percentile par rang le plus proche — suffisant pour un ordre de grandeur."""
    if not values:
        return 0
    ordered = sorted(values)
    index = min(int(p * len(ordered)), len(ordered) - 1)
    return ordered[index]


# Clés du TypedDict TransactionDict qui acceptent None (toutes les autres non).
_NULLABLE = {"time", "card_last_four", "balance_after"}
_REQUIRED = {
    "date",
    "time",
    "amount",
    "currency",
    "description_raw",
    "display_name",
    "merchant_name",
    "card_last_four",
    "import_hash",
    "balance_after",
}


def _contract_issues(transactions: list[TransactionDict]) -> list[str]:
    """
    Vérifie le contrat TransactionDict sur l'ensemble parsé.

    ImportService lit ces clés en accès direct : une clé manquante ou un None
    interdit y lève une exception attrapée en `count_errors` — la ligne est
    perdue avec un simple warning. Mieux vaut le voir ici.
    """
    issues: list[str] = []
    for index, tx in enumerate(transactions):
        missing = _REQUIRED - set(tx)
        if missing:
            issues.append(f"ligne {index}: clés absentes {sorted(missing)}")
        for key in _REQUIRED - _NULLABLE:
            if key in tx and tx[key] is None:  # type: ignore[literal-required]
                issues.append(f"ligne {index}: « {key} » vaut None (interdit)")
        if len(issues) >= 10:
            issues.append("… (troncature à 10)")
            break
    return issues


def profile(
    label: str, connector: str, transactions: list[TransactionDict]
) -> ParseProfile:
    """Calcule le portrait d'un fichier parsé. Ne lève jamais sur une liste vide."""
    n = len(transactions)
    ratio = lambda count: Ratio(count, n)  # noqa: E731 — lisibilité locale

    displays = [tx.get("display_name") or "" for tx in transactions]
    raws = [tx.get("description_raw") or "" for tx in transactions]
    lengths = [len(d) for d in displays]
    dates = sorted(tx["date"] for tx in transactions) if n else []
    hashes = [tx.get("import_hash") for tx in transactions]

    return ParseProfile(
        label=label,
        connector=connector,
        n_transactions=n,
        display_empty=ratio(sum(1 for d in displays if not d.strip())),
        display_equals_raw=ratio(sum(1 for d, r in zip(displays, raws) if d == r)),
        display_too_long=ratio(
            sum(1 for length in lengths if length > LONG_NAME_THRESHOLD)
        ),
        len_mean=(sum(lengths) / n if n else 0.0),
        len_p95=_percentile(lengths, 0.95),
        len_max=max(lengths, default=0),
        distinct_raw=len(set(raws)),
        distinct_display=len(set(displays)),
        merchant_differs=ratio(
            sum(
                1
                for tx in transactions
                if tx.get("merchant_name") != tx.get("display_name")
            )
        ),
        with_card=ratio(sum(1 for tx in transactions if tx.get("card_last_four"))),
        with_time=ratio(sum(1 for tx in transactions if tx.get("time"))),
        with_balance=ratio(
            sum(1 for tx in transactions if tx.get("balance_after") is not None)
        ),
        currencies=dict(Counter(tx.get("currency", "?") for tx in transactions)),
        date_min=dates[0] if dates else "—",
        date_max=dates[-1] if dates else "—",
        hash_distinct=len(set(hashes)),
        hash_collisions=n - len(set(hashes)),
        contract_issues=_contract_issues(transactions),
    )


@dataclass(frozen=True)
class DriftReport:
    """
    Comparaison de deux parses du MÊME compte, pour détecter la dérive de hash.

    C'est le contrôle que `test_hash_stability.py` ne fait qu'en synthétique :
    deux exports RÉELS qui se chevauchent doivent produire le même hash pour
    les transactions communes. Une divergence = un doublon à la réimportation.
    """

    common: int
    same_hash: int
    diverging: list[tuple[str, str, str, str]]  # (date, libellé, hash_a, hash_b)
    only_a: int
    only_b: int

    @property
    def is_stable(self) -> bool:
        return not self.diverging


def hash_drift(a: list[TransactionDict], b: list[TransactionDict]) -> DriftReport:
    """
    Apparie deux parses sur leur identité MÉTIER, puis compare leurs hash.

    L'appariement se fait sur (date, montant, libellé, solde) — délibérément PAS
    sur import_hash, puisque c'est précisément lui qu'on met à l'épreuve. Le
    solde entre dans la clé parce qu'il est le seul discriminant entre deux
    transactions par ailleurs identiques du même jour.
    """

    def key(tx: TransactionDict):
        return (
            tx["date"],
            tx["amount"],
            tx["description_raw"],
            tx.get("balance_after"),
        )

    index_a = {key(tx): tx for tx in a}
    index_b = {key(tx): tx for tx in b}
    common = index_a.keys() & index_b.keys()

    diverging = [
        (
            k[0],
            str(k[2])[:40],
            index_a[k]["import_hash"][:12],
            index_b[k]["import_hash"][:12],
        )
        for k in sorted(common)
        if index_a[k]["import_hash"] != index_b[k]["import_hash"]
    ]

    return DriftReport(
        common=len(common),
        same_hash=len(common) - len(diverging),
        diverging=diverging[:10],
        only_a=len(index_a.keys() - common),
        only_b=len(index_b.keys() - common),
    )
