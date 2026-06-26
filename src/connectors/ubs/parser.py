"""
connectors/ubs/parser.py — UBS CSV parser.

File format
-----------
Encoding  : UTF-8 with BOM (open with "utf-8-sig" to strip BOM automatically)
Delimiter : semicolon (;)
Header    : line 10 (9 metadata lines + 1 blank before)
Columns   : Date de transaction ; Heure de transaction ; Date de comptabilisation ;
            Date de valeur ; Monnaie ; Débit ; Crédit ; Sous-montant ; Solde ;
            No de transaction ; Description1 ; Description2 ; Description3 ;
            Notes de bas de page

Metadata block (lines 1-8, line 9 is blank)
-------------------------------------------
Line 1 : Numéro de compte:;0243 00693382.40;
Line 2 : IBAN:;<IBAN_REDACTED>;                      ← account identifier
Line 3 : Du:;2025-12-22;
Line 4 : Au:;2026-04-01;
Line 5 : Solde initial:;0.00;
Line 6 : Solde final:;7281.45;                       ← balance here
Line 7 : Évaluation en:;CHF;
Line 8 : Nombre de transactions dans cette période:;24;

Quirks
------
- Description1 = merchant name (padded with spaces, e.g. "FEEL EAT SARL            LA CHAUX-D")
- Description2 = card info + transaction type (e.g. '"21303625-0 12/28; Paiement carte de debit"')
  Double-quoted because the value contains a semicolon — csv.DictReader handles this automatically
- Description3 = internal reference (e.g. "No de transaction: 9999091BN1236966")
- Time is present for card payments, empty for transfers (e-banking, salary...)
- Debit amounts are already negative in the file (e.g. "-5500.00")
- Both IBAN and balance can be extracted from the metadata block

Account detection
-----------------
IBAN is on line 2 — extract it, normalise (strip spaces), query Account.iban in DB.
This is deterministic: one file = one IBAN = one account.

Balance extraction
------------------
Line 6: "Solde final:;7281.45;"  → 7281.45
Extracted from the metadata block before the header.

Row filtering
-------------
ALL rows are real transactions in UBS exports.
UBS pre-filters investment orders from the transaction history.
No KEPT_ACTIVITY_TYPES needed — we import everything.
"""

import csv
import hashlib
import logging
import re
from pathlib import Path

from connectors.base import BaseConnector, TransactionDict

logger = logging.getLogger(__name__)

# Number of metadata lines before the blank separator and then the column header
# Layout: 8 metadata lines + 1 blank line = 9 lines to skip before the header row
METADATA_LINE_COUNT = 9


class UBSConnector(BaseConnector):
    """Parses UBS CSV exports into normalized TransactionDicts."""

    # UBS CSV column header signature — used for format detection
    # Must match exactly (order + names) to avoid false positives
    COLUMN_SIGNATURE = [
        "Date de transaction",
        "Heure de transaction",
        "Date de comptabilisation",
        "Date de valeur",
        "Monnaie",
        "Débit",
        "Crédit",
        "Sous-montant",
        "Solde",
        "No de transaction",
        "Description1",
        "Description2",
        "Description3",
        "Notes de bas de page",
    ]

    # =========================================================================
    # Public API
    # =========================================================================

    def parse(self, filepath: Path) -> list[TransactionDict]:
        """
        Parse a UBS CSV file and return a list of normalized transactions.

        All data rows are imported — UBS doesn't mix non-transaction rows
        into the transaction history the way Yuh mixes FX orders and cashback.

        Each row that raises an exception is skipped with a warning.
        """
        transactions = []
        skipped = 0

        with open(filepath, encoding="utf-8-sig") as f:
            # Skip metadata lines until we find the column header.
            # UBS has two variants: checking (9 lines) and savings (8 lines).
            # We scan up to 12 lines and stop as soon as we see the header row.
            header_line = None
            for _ in range(12):
                line = f.readline()
                cols = [c.strip() for c in line.strip().split(";") if c.strip()]
                if cols == self.COLUMN_SIGNATURE:
                    header_line = line
                    break

            if header_line is None:
                return []  # format inattendu — pas de header trouvé

            # DictReader avec le header déjà lu — on passe fieldnames explicitement
            reader = csv.DictReader(
                f,
                fieldnames=[c.strip() for c in header_line.strip().split(";")],
                delimiter=";",
            )

            # start=11: line 1-9 = metadata, line 10 = header, data starts at line 11
            for line_number, row in enumerate(reader, start=11):
                # UBS sometimes adds empty rows at the end of the file
                if not row.get("Date de transaction", "").strip():
                    continue

                try:
                    transactions.append(self._parse_row(row))
                except Exception as e:
                    logger.warning(
                        "[UBS] line %d: %s — row skipped: %s", line_number, e, row
                    )
                    skipped += 1

        logger.info(
            "[UBS] Parsed %d transactions, %d rows skipped",
            len(transactions),
            skipped,
        )
        return transactions

    def extract_account_name(self, filepath: Path) -> str | None:
        """
        Extracts a human-readable account name hint from line 1 of the UBS file.

        Line 1 format: "Numéro de compte:;0243 00693382.40;"
        Returns e.g. "UBS 0243 00693382.40", or None if not parseable.

        This is only a suggestion — the user can override it in the creation form.
        """
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                line1 = f.readline()
            parts = line1.strip().split(";")
            if len(parts) >= 2 and parts[1].strip():
                return f"UBS {parts[1].strip()}"
        except Exception:
            logger.warning(
                "[UBS] extract_account_name failed for %s", filepath, exc_info=True
            )
        return None

    def extract_account_identifier(self, filepath: Path) -> str | None:
        """
        Extract the normalized IBAN from the UBS file's metadata block (line 2).

        Line 2 format: "IBAN:;CH9X XXXX XXXX XXXX XXXX X;"

        Returns the IBAN without spaces: "CH9XXXXXXXXXXXXXXXXXXX"
        This normalized form must match Account.contract_number in the DB exactly.

        Why normalize (strip spaces)?
        - The file contains spaces for readability: "CH9X XXXX XXXX XXXX XXXX X"
        - The DB stores it without spaces (set in seed_initial.py)
        - Normalizing both sides makes the .get(contract_number=identifier) lookup reliable
          regardless of how the IBAN was entered in the admin

        Returns None if line 2 doesn't match the expected format.
        """
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                f.readline()  # line 1: account number
                line2 = f.readline()  # line 2: IBAN
            parts = line2.strip().split(";")
            if len(parts) >= 2 and parts[0].strip() == "IBAN:":
                return parts[1].strip().replace(" ", "")
        except Exception:
            logger.warning(
                "[UBS] extract_account_identifier failed for %s",
                filepath,
                exc_info=True,
            )
        return None

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Extract the final account balance from the UBS file's metadata block (line 6).

        Line 6 format: "Solde final:;7281.45;"
        Returns 7281.45 as a float, or None if not found.
        """
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                for i, line in enumerate(f, start=1):
                    if i == 6:
                        parts = line.strip().split(";")
                        if len(parts) >= 2:
                            return float(parts[1].strip())
                        break
        except Exception:
            logger.warning(
                "[UBS] extract_balance failed for %s", filepath, exc_info=True
            )
        return None

    @classmethod
    def matches_file(cls, filepath: Path) -> bool:
        """
        Return True if this file looks like a UBS CSV export.

        Strategy:
        1. Must be a .csv file
        2. Line 2 must start with "IBAN:;" — unique to UBS exports
        3. COLUMN_SIGNATURE must appear somewhere in lines 3-12

        Why scan lines 3-12 instead of assuming line 10?
        UBS has two metadata formats depending on the account type:
          - Checking : 8 metadata lines + 1 blank = header on line 10
          - Savings   : 7 metadata lines + 1 blank = header on line 9
        Scanning a small window handles both without hardcoding the line number.
        """
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                f.readline()  # line 1: account number
                line2 = f.readline()  # line 2: IBAN
                if not line2.strip().startswith("IBAN:;"):
                    return False
                # Scan lines 3-12 for the column header
                for _ in range(10):
                    line = f.readline()
                    columns = [
                        col.strip() for col in line.strip().split(";") if col.strip()
                    ]
                    if columns == cls.COLUMN_SIGNATURE:
                        return True
        except Exception:
            logger.warning("[UBS] matches_file failed for %s", filepath, exc_info=True)
            return False
        return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _parse_row(self, row: dict) -> TransactionDict:
        """
        Convert one CSV row dict into a TransactionDict.

        UBS rows always have: date, optionally time, currency, debit OR credit.
        Description1 is the merchant/counterpart name (padded with spaces).
        Description2 contains card info for card payments (may be quoted by DictReader).
        """
        date_str = row["Date de transaction"].strip()
        # UBS already uses ISO 8601 (YYYY-MM-DD) — no conversion needed
        if not date_str:
            raise ValueError("Empty transaction date")

        # Time: present for card payments, empty for e-banking transfers
        # "" → None; "12:36:26" → "12:36:26" (kept as-is for the TimeField)
        time_str = row.get("Heure de transaction", "").strip() or None

        amount, currency = self._parse_amount(row)

        # Description1: raw merchant/counterpart — padded with spaces, strip them
        description1 = row.get("Description1", "").strip()
        description2 = row.get("Description2", "").strip()
        description3 = row.get("Description3", "").strip()

        # We keep the full description for audit: join non-empty parts with " | "
        description_raw = " | ".join(
            part for part in [description1, description2, description3] if part
        )

        # display_name: apply UBS-specific cleaning to description1 (first segment).
        # _clean_merchant() strips UBS structural prefixes ("Auftrag:", "Gutschrift",
        # "E-Banking") that pollute the merchant name, then normalizes whitespace.
        # We use description1 directly (not description_raw) to avoid having to
        # re-split the already-joined string.
        display_name = self._clean_merchant(description1)
        merchant_name = display_name  # pre-fill override

        # Card last four: UBS doesn't use "**** XXXX" format.
        # Description2 contains "21303625-0 12/28; Paiement carte de debit" for card tx.
        # We leave this None for now — UBS card references are contract numbers,
        # not the visible card number. TODO: match via contract number in Phase 2.
        card_last_four = None

        # import_hash — see CONTRACT in base.py.
        #
        # UBS assigns a globally unique "No de transaction" per row (e.g. "9999125BN1308361").
        # When present, it's the most stable identifier possible: guaranteed unique by the bank,
        # immune to column reordering or description changes across re-exports.
        #
        # Fallback (should never happen with modern UBS exports) : date+time+amount+descriptions.
        # The fallback uses description2 to reduce collisions on same-day same-amount transfers
        # (e.g. two salary advances with identical date/time/amount/description1).
        no_transaction = row.get("No de transaction", "").strip()
        if no_transaction:
            raw = f"ubs_tx|{no_transaction}"
        else:
            raw = f"{date_str}|{time_str}|{amount}|{description1}|{description2}"
        import_hash = hashlib.sha256(raw.encode()).hexdigest()

        return TransactionDict(
            date=date_str,
            time=time_str,
            amount=amount,
            currency=currency,
            description_raw=description_raw,
            display_name=display_name,
            merchant_name=merchant_name,
            card_last_four=card_last_four,
            import_hash=import_hash,
            # UBS provides a single closing balance in the file header (Solde final),
            # not a per-row running balance. Daily BalanceSnapshots will use that header value.
            balance_after=None,
        )

    def _parse_amount(self, row: dict) -> tuple[float, str]:
        """
        Extract (amount, currency) from UBS Débit/Crédit columns.

        Like Yuh, UBS uses two separate columns:
            Débit  → negative amount (money out)   e.g. "-5500.00"
            Crédit → positive amount (money in)    e.g. "7349.70"

        One column is empty per row. Debit is already stored negative in the file.
        Raises ValueError if both are empty or values can't be parsed.
        """
        currency = row.get("Monnaie", "").strip()
        debit = row.get("Débit", "").strip()
        credit = row.get("Crédit", "").strip()

        if debit:
            # Debit values are negative in the file: "-75.00"
            return float(debit), currency
        elif credit:
            return float(credit), currency
        else:
            raise ValueError("Both Débit and Crédit are empty")

    # Préfixes UBS structurels — jamais un nom de marchand.
    # "Auftrag:" = ordre de virement en allemand (même dans les exports FR)
    # "Gutschrift" = crédit / remboursement
    # "E-Banking" = libellé virement en ligne UBS
    # "Debit Direct" = prélèvement automatique UBS
    _UBS_PREFIX_RE = re.compile(
        r"^(?:Auftrag\s*:|Gutschrift|E-Banking|Debit Direct)\s*",
        re.IGNORECASE,
    )

    def _clean_merchant(self, description1: str) -> str:
        """
        Produce a clean merchant name from UBS Description1.

        Two passes:
          1. Strip UBS-specific structural prefixes ("Auftrag:", "Gutschrift",
             "E-Banking", "Debit Direct") — they are never merchant names.
          2. Delegate to base _normalize_merchant() for whitespace/casing.

        Example: "Gutschrift ANTEIS SA" → "ANTEIS SA"
                 "Auftrag: Loyer appartement" → "LOYER APPARTEMENT"
                 "FEEL EAT SARL            LA CHAUX-D" → "FEEL EAT SARL LA CHAUX-D"
        """
        text = self._UBS_PREFIX_RE.sub("", description1).strip()
        return self._normalize_merchant(text)
