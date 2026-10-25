"""
connectors/tsb/parser.py — TSB (UK) CSV parser.

Format
------
Encoding  : ASCII pur (corpus réel : 0 octet > 127), lu en utf-8-sig par sûreté
Delimiter : virgule
Header    : ligne 1
Colonnes  : Transaction date, Transaction Type, Sort Code, Account Number,
            Transaction description, Debit Amount, Credit amount, Balance

⚠️ La CASSE des en-têtes est incohérente côté TSB : « Transaction date » et
« Credit amount » en minuscules, face à « Transaction Type » et « Debit Amount »
capitalisés. Les clés sont recopiées à l'octet près — une clé « normalisée »
renverrait None en silence.

Particularités du format (établies sur 831 lignes réelles, 10 exports)
----------------------------------------------------------------------
ORDRE ANTI-CHRONOLOGIQUE
    La transaction la plus RÉCENTE est en première ligne (10/10 fichiers).
    Le solde de clôture est donc en tête, pas en queue — d'où extract_balance().

LE TYPE NE DONNE PAS LE SENS
    « Transaction Type » (DEB, DD, TFR, FPI, FPO, DC, SO, CHG, CSH, CHP) décrit
    le MOYEN de paiement, pas la direction. Sur le corpus réel, 3 lignes DEB et
    2 lignes SO sont des CRÉDITS (remboursements carte, partage de charges).
    La direction vient EXCLUSIVEMENT de la colonne remplie : Debit ou Credit,
    jamais les deux, jamais aucune (vérifié 384/384 puis 831/831).

AUCUN TYPE À FILTRER
    Contrairement à Yuh (cashback/ordres de change exclus), les 10 types TSB
    sont de vrais mouvements qui déplacent le solde — y compris CHG (intérêts
    de découvert) et les lignes de frais de change « 2.99% CD … ». La chaîne
    arithmétique des soldes le prouve : 0 rupture intra-fichier.

SOLDE NÉGATIF = DÉCOUVERT
    Le compte passe légitimement en négatif. Ne jamais clamper à 0 : ça
    masquerait le découvert et fausserait la courbe de patrimoine.

DEVISE ABSENTE — HYPOTHÈSE ASSUMÉE
    Aucune colonne de devise, aucun « GBP » ni « £ » nulle part dans les
    fichiers. On code GBP en dur : c'est un pari explicite sur le fait que TSB
    n'exporte que des comptes en livres. Un test le fige (test_currency_is_gbp)
    pour que l'hypothèse échoue bruyamment si elle cesse d'être vraie.

DATE = DATE DE COMPTABILISATION
    13 lignes du corpus portent une date carte encastrée (« … CD 0000 29APR26 »)
    antérieure de 1 à 2 jours. On garde la date de la colonne : extraire celle
    du libellé casserait la stabilité du hash pour un gain d'exactitude marginal.

CSV NON CITÉ
    TSB n'émet aucun guillemet (0 sur tout le corpus). Une description contenant
    une virgule décalerait les colonnes. csv.DictReader gère le cas standard ;
    la garde est la validation du nombre de champs par ligne.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTRAT import_hash — voir base.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Priorité 1 (identifiant bancaire) : INDISPONIBLE — TSB n'en exporte aucun.

Priorité 2 (solde courant) : ÉCARTÉE. Le solde n'identifie pas une transaction
    chez TSB : 10 collisions de solde sur 384 lignes (un aller-retour vers le
    compte d'épargne ramène le solde à une valeur déjà vue). Et l'inclure dans
    le hash le rend sensible au réordonnancement de deux transactions du même
    jour. C'est la décision déjà actée pour CIC dans base.py : « balance_after
    is used for BalanceSnapshot, NOT for the hash ».

Priorité 3 (identifiant positionnel stable) : RETENUE, motif CIC/Yuh —
    sha256("tsb|{compte}|{date}|{type}|{montant}|{libellé}|{occurrence}")

    occurrence_index = nombre de fois où (date, type, montant, libellé) a déjà
    été rencontré PLUS HAUT DANS LE MÊME FICHIER. Il ne s'active que sur les
    vrais doublons du même jour (2 lignes sur 384 dans le corpus), et c'est lui
    qui les préserve : sans lui, 13 collisions = 19 transactions perdues.

    Le montant est normalisé en Decimal à 2 décimales AVANT hachage. TSB écrit
    « 3 », « 5.5 » ou « 1565.37 » indifféremment (139 valeurs du corpus ne sont
    pas en 2 décimales) ; hacher le texte brut ferait re-hacher tout
    l'historique le jour où TSB uniformise son formatage.

    Mesuré sur les 10 exports réels (831 lignes, 687 transactions, dont 136
    présentes dans plusieurs fichiers) : 687 hashes, 0 collision, 0 instabilité.
    Variante avec line_number : 107 instabilités — l'anti-pattern déjà payé
    chez Yuh, reproduit ici en chiffres.
"""

import csv
import hashlib
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from connectors.base import BaseConnector, TransactionDict

logger = logging.getLogger(__name__)

# Marqueur de carte en fin de libellé : « CD 0000 », parfois suivi de la date
# d'achat au format DDMMMYY (« CD 0000 29APR26 »).
_CARD_RE = re.compile(r"\bCD\s+(\d{4})\b(?:\s+\d{2}[A-Z]{3}\d{2})?\s*$", re.IGNORECASE)


class TSBConnector(BaseConnector):
    """Parse les exports CSV de TSB (UK) en TransactionDict normalisés."""

    # Résolution de compte : TSB n'expose pas d'IBAN dans ses exports, mais le
    # couple Sort Code + Account Number est présent sur CHAQUE ligne.
    INSTITUTION_SLUG = "tsb"
    IDENTITY_FIELD: str | None = "contract_number"

    # Devise absente du fichier — hypothèse documentée en tête de module.
    CURRENCY = "GBP"

    # Signature des colonnes, recopiée à l'octet près (casse incohérente de TSB).
    COLUMN_SIGNATURE = [
        "Transaction date",
        "Transaction Type",
        "Sort Code",
        "Account Number",
        "Transaction description",
        "Debit Amount",
        "Credit amount",
        "Balance",
    ]

    # =========================================================================
    # Public API
    # =========================================================================

    @classmethod
    def matches_file(cls, filepath: Path) -> bool:
        """
        True si le fichier est un export CSV TSB.

        Égalité EXACTE de la ligne d'en-tête — même rigueur que les autres
        connecteurs. Un « contient » laisserait passer d'autres CSV bancaires
        britanniques et le premier connecteur de la liste gagnerait au hasard.
        """
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            with open(filepath, encoding="utf-8-sig", newline="") as f:
                header = f.readline()
        except OSError:
            logger.warning("[TSB] matches_file failed for %s", filepath, exc_info=True)
            return False
        return [c.strip() for c in header.strip().split(",")] == cls.COLUMN_SIGNATURE

    def parse(self, filepath: Path) -> list[TransactionDict]:
        """
        Parse un CSV TSB. Ne lève jamais : une ligne fautive est ignorée et loggée.

        `occurrence_counters` est partagé par tout le fichier — c'est lui qui
        distingue deux transactions par ailleurs identiques du même jour.
        """
        transactions: list[TransactionDict] = []
        skipped = 0
        occurrence_counters: dict = {}

        with open(filepath, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for line_number, row in enumerate(reader, start=2):
                if not (row.get("Transaction date") or "").strip():
                    continue  # ligne vide de fin de fichier
                try:
                    transactions.append(self._parse_row(row, occurrence_counters))
                except Exception as exc:
                    # Jamais le libellé dans le log : les descriptions TFR de TSB
                    # encastrent en clair le sort code et le n° du compte
                    # d'épargne du titulaire (SR-008).
                    logger.warning(
                        "[TSB] line %d skipped: %s", line_number, exc, exc_info=False
                    )
                    skipped += 1

        logger.info(
            "[TSB] Parsed %d transactions, %d rows skipped", len(transactions), skipped
        )
        return transactions

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Solde de clôture = celui de la PREMIÈRE ligne de données.

        TSB liste la transaction la plus récente en tête (ordre anti-chronologique,
        vérifié sur 10/10 fichiers). Lire la dernière ligne — le réflexe hérité
        des autres connecteurs — renverrait le solde d'OUVERTURE de la période.
        """
        try:
            with open(filepath, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    raw = (row.get("Balance") or "").strip()
                    if not raw:
                        return None
                    return float(Decimal(raw))
        except (OSError, InvalidOperation, ValueError):
            logger.warning(
                "[TSB] extract_balance failed for %s", filepath, exc_info=True
            )
        return None

    def extract_account_identifier(self, filepath: Path) -> str | None:
        """
        Identité = sort code sans tirets + numéro de compte, concaténés.

        « 00-00-00 » + « 00000000 » → « 00000000000000 ». C'est exactement la
        forme attendue dans Account.contract_number : les deux côtés doivent
        partager la même normalisation, sinon aucun match ne se produira.
        """
        try:
            with open(filepath, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    sort_code = (row.get("Sort Code") or "").replace("-", "").strip()
                    number = (row.get("Account Number") or "").strip()
                    if sort_code and number:
                        return f"{sort_code}{number}"
                    return None
        except OSError:
            logger.warning(
                "[TSB] extract_account_identifier failed for %s",
                filepath,
                exc_info=True,
            )
        return None

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _parse_row(self, row: dict, occurrence_counters: dict) -> TransactionDict:
        """Convertit une ligne CSV en TransactionDict normalisé."""
        date_str = row["Transaction date"].strip()
        tx_type = row["Transaction Type"].strip()
        description_raw = row["Transaction description"].strip()

        amount = self._parse_amount(row)
        # Chaîne canonique du montant : « 3 » et « 3.00 » doivent produire le
        # même hash (cf. CONTRAT en tête de module).
        amount_key = f"{amount:.2f}"

        display_name = self._clean_merchant(description_raw)

        group_key = (date_str, tx_type, amount_key, description_raw)
        occurrence_index = occurrence_counters.get(group_key, 0)
        occurrence_counters[group_key] = occurrence_index + 1

        account = (
            row["Sort Code"].replace("-", "").strip() + row["Account Number"].strip()
        )
        raw = (
            f"tsb|{account}|{date_str}|{tx_type}|{amount_key}"
            f"|{description_raw}|{occurrence_index}"
        )
        import_hash = hashlib.sha256(raw.encode()).hexdigest()

        return TransactionDict(
            date=date_str,
            time=None,  # TSB n'exporte pas l'heure
            amount=float(amount),
            currency=self.CURRENCY,
            description_raw=description_raw,
            display_name=display_name,
            merchant_name=display_name,
            card_last_four=self._parse_card(description_raw),
            import_hash=import_hash,
            balance_after=self._parse_balance(row),
        )

    def _parse_amount(self, row: dict) -> Decimal:
        """
        Montant signé : négatif au débit, positif au crédit.

        La direction vient de la COLONNE REMPLIE, jamais du « Transaction Type » —
        3 lignes DEB et 2 lignes SO du corpus réel sont des crédits. Les deux
        colonnes sont mutuellement exclusives (vérifié 831/831) ; si les deux
        étaient vides, la ligne n'est pas exploitable et on le dit.
        """
        debit = (row.get("Debit Amount") or "").strip()
        credit = (row.get("Credit amount") or "").strip()

        if debit:
            return -Decimal(debit)
        if credit:
            return Decimal(credit)
        raise ValueError("ni débit ni crédit renseigné")

    def _parse_balance(self, row: dict) -> float | None:
        """
        Solde APRÈS la transaction — présent sur 100 % des lignes TSB.

        Alimente les BalanceSnapshots quotidiens (comme CIC). Les valeurs
        négatives sont conservées telles quelles : c'est un découvert réel.
        """
        raw = (row.get("Balance") or "").strip()
        if not raw:
            return None
        try:
            return float(Decimal(raw))
        except InvalidOperation:
            return None

    def _clean_merchant(self, description: str) -> str:
        """
        Retire le marqueur de carte final (« CD 0000 », « CD 0000 29APR26 »).

        C'est du bruit structurel de TSB, pas une partie du nom du marchand :
        « SCOTRAIL CD 0000 » → « SCOTRAIL ». Le numéro de carte n'est pas perdu,
        il part dans card_last_four.

        REPLI, élargi : on ne garde le résultat nettoyé QUE s'il contient au
        moins une lettre. Objectif « mieux trop que trop peu » — deux libellés
        réels du corpus le prouvent :
          - « CD 1234 09FEB26 »        → nettoyé = ""     (vide)
          - « 2.99% CD 0000 23APR26 »  → nettoyé = "2.99%" (frais de change
            carte étrangère — pas vide, mais aucune lettre : ce n'est pas un
            nom de marchand, juste un taux orphelin, illisible dans l'UI)
        Un simple `cleaned or description` (ancien repli) ne rattrapait que le
        premier cas. Tester la présence d'une lettre plutôt que régler un motif
        « % » ad hoc : plus général, couvre tout futur libellé qui se réduit à
        du bruit numérique une fois le marqueur carte retiré.
        """
        cleaned = _CARD_RE.sub("", description).strip()
        has_letter = any(c.isalpha() for c in cleaned)
        return self._normalize_merchant(cleaned if has_letter else description)

    def _parse_card(self, description: str) -> str | None:
        """Les 4 derniers chiffres de la carte, depuis « CD 0000 » en fin de libellé."""
        match = _CARD_RE.search(description)
        return match.group(1) if match else None
