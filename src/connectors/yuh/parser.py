"""
connectors/yuh/parser.py — Yuh CSV parser.

File format
-----------
Encoding  : UTF-8 with BOM (open with "utf-8-sig" to strip BOM automatically)
Delimiter : semicolon (;)
Header    : 1 row
Columns   : DATE ; ACTIVITY TYPE ; ACTIVITY NAME ; DEBIT ; DEBIT CURRENCY ;
            CREDIT ; CREDIT CURRENCY ; CARD NUMBER ; LOCALITY ; RECIPIENT ;
            SENDER ; FEES/COMMISSION ; BUY/SELL ; QUANTITY ; ASSET ; PRICE PER UNIT

Quirks
------
- Text values are triple-quoted: [[[Transfert de ANTEIS SA]]]  → strip all quotes
- No IBAN or account number anywhere in the file
- No time column (date only, format DD/MM/YYYY)
- Balance not in file — only available in filename (see extract_balance)
- CARD NUMBER format: "**** 1150"  → last_four = "1150"

Row filtering
-------------
SKIP (not real budget transactions):
    REWARD_RECEIVED   Yuh cashback points — no CHF amount, pollutes the transaction list

KEEP everything else:
    CARD_TRANSACTION_OUT      card payment (debit)
    PAYMENT_TRANSACTION_IN    incoming transfer (credit)
    PAYMENT_TRANSACTION_OUT   outgoing transfer (debit)
    BANK_AUTO_ORDER_EXECUTED  automatic FX conversion — real money movement, keep
    BANK_ORDER_EXECUTED       manual FX order — real money movement, keep
    SAVINGS_PLAN_*            savings plan movements — keep
    Any future activity type  → kept by default (blacklist = future-proof)

Balance extraction
------------------
Filename format: "Activités_2026_03_17 - 33,344.CSV"
The balance is the number between " - " and ".CSV", with commas removed.
Example: "Activités_2026_03_17 - 33,344.CSV" → 33344.0

Account detection
-----------------
Yuh files have no identifier. Detection works by recognising the unique column
signature of Yuh exports. If a single Yuh checking account exists in the DB,
we assign it. Error if 0 or more than 1.
"""

import csv
import hashlib
import re
from pathlib import Path

from connectors.base import BaseConnector, TransactionDict


class YuhConnector(BaseConnector):
    """Parses Yuh CSV exports into normalized TransactionDicts."""

    # Yuh CSV column header signature — used for format detection
    # These 16 columns in this exact order = definitely a Yuh file
    COLUMN_SIGNATURE = [
        "DATE",
        "ACTIVITY TYPE",
        "ACTIVITY NAME",
        "DEBIT",
        "DEBIT CURRENCY",
        "CREDIT",
        "CREDIT CURRENCY",
        "CARD NUMBER",
        "LOCALITY",
        "RECIPIENT",
        "SENDER",
        "FEES/COMMISSION",
        "BUY/SELL",
        "QUANTITY",
        "ASSET",
        "PRICE PER UNIT",
    ]

    # Activity types to SKIP — everything else is imported.
    # Blacklist is safer than whitelist: future Yuh activity types are kept by default.
    # Only REWARD_RECEIVED is excluded because it has no CHF amount (cashback points only).
    SKIPPED_ACTIVITY_TYPES = {
        "REWARD_RECEIVED",
    }

    # =========================================================================
    # Public API
    # =========================================================================

    def parse(self, filepath: Path) -> list[TransactionDict]:
        """
        Parse a Yuh CSV file and return a list of normalized transactions.

        Only rows whose ACTIVITY TYPE is in KEPT_ACTIVITY_TYPES are included.
        Each row that raises an exception is skipped with a printed warning
        so one bad row never aborts the whole import.
        """
        transactions = []
        skipped = 0

        # occurrence_index: counts how many times we've already seen each
        # (date, activity_type, amount, description) group in this file.
        # Used in the hash instead of line_number — stable across partial exports.
        #
        # Example: two identical parking payments on the same day always get
        # occurrence_index 0 and 1 regardless of where the file starts.
        # With line_number they'd shift if the file started later → duplicate import.
        occurrence_counters: dict[tuple, int] = {}

        with open(filepath, encoding="utf-8-sig") as f:
            # utf-8-sig: strips the BOM character automatically
            # Without it, the first column header would be "﻿DATE" instead of "DATE"
            reader = csv.DictReader(f, delimiter=";")

            for line_number, row in enumerate(
                reader, start=2
            ):  # start=2: line 1 = header, kept for warning messages
                activity_type = row.get("ACTIVITY TYPE", "").strip()

                # Skip only REWARD_RECEIVED — everything else is a real money movement
                if activity_type in self.SKIPPED_ACTIVITY_TYPES:
                    skipped += 1
                    continue

                try:
                    transactions.append(
                        self._parse_row(row, line_number, occurrence_counters)
                    )
                except Exception as e:
                    # Never abort on a bad row — log and continue
                    print(
                        f"  [Yuh] WARNING line {line_number}: {e} — row skipped: {row}"
                    )
                    skipped += 1

        print(
            f"  [Yuh] Parsed {len(transactions)} transactions, {skipped} rows skipped"
        )
        return transactions

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Extract the account balance from the filename.

        Pattern: "Activités_2026_03_17 - 33,344.CSV"
        → everything after " - " and before ".CSV", commas stripped → 33344.0

        Returns None if the filename doesn't match the pattern.
        """
        # re.search: find the pattern anywhere in the string (not just at start)
        # Pattern breakdown:
        #   " - "        literal separator between date and balance
        #   ([\d,]+)     capture group: digits and commas (the balance number)
        #   (?:\.CSV)?$  optional ".CSV" extension (case handled below)
        match = re.search(r" - ([\d,]+)(?:\.csv)?$", filepath.name, re.IGNORECASE)
        if not match:
            return None

        # Remove commas used as thousands separators: "33,344" → "33344"
        balance_str = match.group(1).replace(",", "")
        try:
            return float(balance_str)
        except ValueError:
            return None

    @classmethod
    def matches_file(cls, filepath: Path) -> bool:
        """
        Return True if this file looks like a Yuh CSV export.

        Called by ConnectorRegistry to auto-select the right parser.
        Reads only the first line — fast, no full parse needed.
        """
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                first_line = f.readline().strip()
            # Split on semicolons and compare to our known signature
            columns = [col.strip() for col in first_line.split(";")]
            return columns == cls.COLUMN_SIGNATURE
        except Exception:
            return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _parse_row(
        self, row: dict, line_number: int, occurrence_counters: dict
    ) -> TransactionDict:
        """
        Convert one CSV row dict into a TransactionDict.

        Called for each row that passed the KEPT_ACTIVITY_TYPES filter.
        Raises ValueError if a required field is missing or malformed.
        """
        date_str = self._parse_date(row["DATE"].strip())
        amount, currency = self._parse_amount(row)
        description_raw = self._strip_quotes(row["ACTIVITY NAME"].strip())
        # Yuh RECIPIENT/SENDER columns are already clean names — use as display_name
        # when available (better than cleaning ACTIVITY NAME which is already clean).
        # Fall back to _clean_description(description_raw) for unrecognised types.
        activity_type = row.get("ACTIVITY TYPE", "").strip()
        recipient = self._strip_quotes(row.get("RECIPIENT", "").strip())
        sender = self._strip_quotes(row.get("SENDER", "").strip())
        if (
            activity_type in ("CARD_TRANSACTION_OUT", "PAYMENT_TRANSACTION_OUT")
            and recipient
        ):
            display_name = self._normalize_merchant(recipient)
        elif activity_type == "PAYMENT_TRANSACTION_IN" and sender:
            display_name = self._normalize_merchant(sender)
        else:
            display_name = self._clean_description(description_raw)
        merchant_name = display_name  # pre-fill override with same value
        card_last_four = self._parse_card(row.get("CARD NUMBER", "").strip())

        # import_hash — see CONTRACT in base.py.
        #
        # Yuh has no bank-assigned transaction ID, so we build a stable key from
        # content fields + occurrence_index.
        #
        # occurrence_index = how many times this exact (date, type, amount, desc)
        # combination has already appeared earlier in THIS file. This disambiguates
        # two identical transactions on the same day (e.g. two 2 CHF parking) while
        # staying stable across partial exports:
        #
        #   Full-year file : parking Jan-15 → occurrence_index=0 → hash H1
        #   January-only   : same parking   → occurrence_index=0 → same hash H1  ✓
        #
        # Contrast with line_number: full-year line 150 vs Jan-only line 5 → different
        # hashes → duplicate import. That's the bug occurrence_index fixes.
        group_key = (date_str, row["ACTIVITY TYPE"], amount, description_raw)
        occurrence_index = occurrence_counters.get(group_key, 0)
        occurrence_counters[group_key] = occurrence_index + 1

        raw = f"{date_str}|{row['ACTIVITY TYPE']}|{amount}|{description_raw}|{occurrence_index}"
        import_hash = hashlib.sha256(raw.encode()).hexdigest()

        return TransactionDict(
            date=date_str,
            time=None,  # Yuh doesn't export transaction time
            amount=amount,
            currency=currency,
            description_raw=description_raw,
            display_name=display_name,
            merchant_name=merchant_name,
            card_last_four=card_last_four,
            import_hash=import_hash,
            balance_after=None,
        )

    def _parse_date(self, raw: str) -> str:
        """
        Convert DD/MM/YYYY → ISO 8601 "YYYY-MM-DD".

        Example: "23/10/2025" → "2025-10-23"
        Raises ValueError if format doesn't match.
        """
        parts = raw.split("/")
        if len(parts) != 3:
            raise ValueError(f"Unexpected date format: '{raw}'")
        day, month, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    def _parse_amount(self, row: dict) -> tuple[float, str]:
        """
        Extract (amount, currency) from the DEBIT/CREDIT columns.

        Yuh uses two separate columns:
            DEBIT  + DEBIT CURRENCY  → negative amount (money out)
            CREDIT + CREDIT CURRENCY → positive amount (money in)

        One of the two pairs is always empty. We check DEBIT first.
        Raises ValueError if both are empty or the value can't be parsed.
        """
        debit = row.get("DEBIT", "").strip()
        debit_currency = row.get("DEBIT CURRENCY", "").strip()
        credit = row.get("CREDIT", "").strip()
        credit_currency = row.get("CREDIT CURRENCY", "").strip()

        if debit:
            # Debit amounts are already negative in the file (e.g. "-196.20")
            return float(debit), debit_currency
        elif credit:
            return float(credit), credit_currency
        else:
            raise ValueError("Both DEBIT and CREDIT are empty")

    def _strip_quotes(self, text: str) -> str:
        """
        Remove Yuh's triple-quote wrapping from text values.

        Yuh wraps most text fields in triple double-quotes (3 x "):
            e.g. [3x"]Transfert de ANTEIS SA[3x"] → 'Transfert de ANTEIS SA'
        strip('"') removes all leading/trailing double-quote characters.
        """
        return text.strip('"').strip()

    def _clean_merchant(self, description: str, row: dict) -> str:
        """
        Derive a clean merchant name from the raw description.

        Strategy:
        1. For CARD_TRANSACTION_OUT: use RECIPIENT field if available (already clean)
        2. For transfers: use RECIPIENT or SENDER field if available
        3. Fallback: use the description itself, title-cased

        This gives the best pre-fill for the merchant_name field in the UI.
        The user can always edit it manually.
        """
        activity_type = row.get("ACTIVITY TYPE", "").strip()

        if activity_type == "CARD_TRANSACTION_OUT":
            recipient = self._strip_quotes(row.get("RECIPIENT", "").strip())
            if recipient:
                return self._normalize_merchant(recipient)

        if activity_type == "PAYMENT_TRANSACTION_OUT":
            recipient = self._strip_quotes(row.get("RECIPIENT", "").strip())
            if recipient:
                return self._normalize_merchant(recipient)

        if activity_type == "PAYMENT_TRANSACTION_IN":
            sender = self._strip_quotes(row.get("SENDER", "").strip())
            if sender:
                return self._normalize_merchant(sender)

        # Fallback: normalize the raw description
        return self._normalize_merchant(description)

    def _parse_card(self, raw: str) -> str | None:
        """
        Extract the last 4 digits from Yuh's masked card number.

        Format: "**** 1150" → "1150"
        Returns None if the field is empty (non-card transactions).
        """
        if not raw:
            return None
        # Take the last 4 characters after stripping whitespace
        digits = raw.strip().split()[-1] if " " in raw else raw[-4:]
        return digits if digits.isdigit() else None
