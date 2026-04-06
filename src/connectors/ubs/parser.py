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
Line 2 : IBAN:;CH9X XXXX XXXX XXXX XXXX X;          ← account identifier
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
IBAN is on line 2 — extract it, normalise (strip spaces), query CheckingAccount.iban in DB.
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
from pathlib import Path

from connectors.base import BaseConnector, TransactionDict

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
            # Skip the 9 metadata lines (8 info lines + 1 blank separator)
            # These lines are NOT part of the CSV — they use a different structure
            # (colon-delimited key:;value; pairs) so we skip them manually.
            for _ in range(METADATA_LINE_COUNT):
                f.readline()

            # Now the next line is the column header — DictReader reads it as field names
            reader = csv.DictReader(f, delimiter=";")

            # start=11: line 1-9 = metadata, line 10 = header, data starts at line 11
            for line_number, row in enumerate(reader, start=11):
                # UBS sometimes adds empty rows at the end of the file
                if not row.get("Date de transaction", "").strip():
                    continue

                try:
                    transactions.append(self._parse_row(row))
                except Exception as e:
                    print(
                        f"  [UBS] WARNING line {line_number}: {e} — row skipped: {row}"
                    )
                    skipped += 1

        print(
            f"  [UBS] Parsed {len(transactions)} transactions, {skipped} rows skipped"
        )
        return transactions

    def extract_account_identifier(self, filepath: Path) -> str | None:
        """
        Extract the normalized IBAN from the UBS file's metadata block (line 2).

        Line 2 format: "IBAN:;CH9X XXXX XXXX XXXX XXXX X;"

        Returns the IBAN without spaces: "CH9400243243693382 40P"
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
            # Format: "IBAN:;CH9X XXXX XXXX XXXX XXXX X;"
            parts = line2.strip().split(";")
            # parts[0] = "IBAN:", parts[1] = "CH9X XXXX XXXX XXXX XXXX X", parts[2] = ""
            if len(parts) >= 2 and parts[0].strip() == "IBAN:":
                return parts[1].strip().replace(" ", "")  # normalize: strip spaces
        except Exception:
            pass
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
                        # "Solde final:;7281.45;"
                        parts = line.strip().split(";")
                        if len(parts) >= 2:
                            return float(parts[1].strip())
                        break
        except Exception:
            pass
        return None

    @classmethod
    def matches_file(cls, filepath: Path) -> bool:
        """
        Return True if this file looks like a UBS CSV export.

        Strategy:
        1. Must be a .csv file
        2. Line 2 must start with "IBAN:;" — unique to UBS exports
        3. Line 10 must match our COLUMN_SIGNATURE

        Check (2) first — it's fast (reads 2 lines) and avoids loading the
        full header for non-UBS files.
        """
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                f.readline()  # line 1: skip account number
                line2 = f.readline()  # line 2: IBAN line
                # Fast check: does line 2 start with "IBAN:;"?
                if not line2.strip().startswith("IBAN:;"):
                    return False
                # Skip lines 3-9 (7 more metadata lines)
                for _ in range(7):
                    f.readline()
                # Line 10 is the column header
                header_line = f.readline().strip()
            columns = [col.strip() for col in header_line.split(";") if col.strip()]
            return columns == cls.COLUMN_SIGNATURE
        except Exception:
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

        # Merchant name: Description1 is usually the best source.
        # It's already a clean merchant name (UBS provides "FEEL EAT SARL LA CHAUX-D")
        # We collapse multiple spaces (padding artifact) and title-case it.
        merchant_name = self._clean_merchant(description1)

        # Card last four: UBS doesn't use "**** XXXX" format.
        # Description2 contains "21303625-0 12/28; Paiement carte de debit" for card tx.
        # We leave this None for now — UBS card references are contract numbers,
        # not the visible card number. TODO: match via contract number in Phase 2.
        card_last_four = None

        # import_hash: SHA1 of the fields that uniquely identify this transaction.
        # We include time because two card payments to the same merchant at the same amount
        # on the same day are realistically different events at different times.
        # No IBAN in the hash — the hash is per-row, account association is external.
        raw = f"{date_str}|{time_str}|{amount}|{description1}"
        import_hash = hashlib.sha1(raw.encode()).hexdigest()

        return TransactionDict(
            date=date_str,
            time=time_str,
            amount=amount,
            currency=currency,
            description_raw=description_raw,
            merchant_name=merchant_name,
            card_last_four=card_last_four,
            import_hash=import_hash,
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

    def _clean_merchant(self, description1: str) -> str:
        """
        Produce a clean merchant name from UBS Description1.

        UBS pads merchant names with multiple spaces:
            "FEEL EAT SARL            LA CHAUX-D"
        → collapse all consecutive spaces to one, then title-case.
        Result: "Feel Eat Sarl La Chaux-D"
        """
        import re

        # Collapse multiple consecutive spaces to a single space
        collapsed = re.sub(r" {2,}", " ", description1).strip()
        return collapsed.title()
