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

Currency conversions (2 legs per row)
--------------------------------------
BANK_AUTO_ORDER_EXECUTED and BANK_ORDER_EXECUTED can fill BOTH DEBIT and
CREDIT on the SAME row, in two different currencies — e.g. "Change automatique
Francs suisses": DEBIT -8.30 CHF + CREDIT 8.90 EUR. This is ONE wallet
movement (money leaves the CHF pocket, enters the EUR pocket of the SAME
Yuh account), not a CHF expense. _parse_row() emits 2 TransactionDict in
that case (one per currency), linked via paired_leg_key (see CONTRACT in
connectors/base.py) so ImportService pairs them via Transaction.
paired_transaction and marks both is_internal_transfer=True / is_ignored=True
— they must never count as real spend/income, in ANY currency (CHF, EUR,
GBP, USD all observed on real exports). Rows with only one column filled
(most CARD_TRANSACTION_OUT, transfers, and some BANK_ORDER_EXECUTED that
only convert without a matching debit on this account) stay 1 leg, no pairing.

Balance extraction
------------------
None — Yuh exposes NO balance anywhere, not in the file content and not in
the filename. The number after " - " in the filename (e.g. "Activités_
2026_09_18 - 46,933.CSV") LOOKS like a balance and was originally treated as
one, but this was never verified against a real balance and turned out to be
wrong: summing every transaction from a confirmed anchor forward lands ~30k
CHF away from that number on a real account. What that number actually is
remains unknown (not a transaction count, not a same-currency running sum —
checked both). Since it is not reliable, extract_balance() always returns
None; the account balance can only be anchored via a manual entry
(patrimoine account-detail page) or trusted from bank-confirmed data of
other institutions.

Account detection
-----------------
Yuh files have no identifier. Detection works by recognising the unique column
signature of Yuh exports. If a single Yuh checking account exists in the DB,
we assign it. Error if 0 or more than 1.
"""

import csv
import hashlib
import logging
from pathlib import Path

from connectors.base import BaseConnector, TransactionDict

logger = logging.getLogger(__name__)


class YuhConnector(BaseConnector):
    """Parses Yuh CSV exports into normalized TransactionDicts."""

    # Résolution de compte : Yuh n'expose aucun identifiant dans ses exports
    # → IDENTITY_FIELD=None → picker manuel obligatoire (voir resolver.py).
    INSTITUTION_SLUG = "yuh"
    IDENTITY_FIELD: str | None = None

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
                    transactions.extend(
                        self._parse_row(row, line_number, occurrence_counters)
                    )
                except Exception as e:
                    logger.warning(
                        "[Yuh] line %d: %s — row skipped: %s",
                        line_number,
                        e,
                        row,
                        exc_info=True,
                    )
                    skipped += 1

        logger.info(
            "[Yuh] Parsed %d transactions, %d rows skipped",
            len(transactions),
            skipped,
        )
        return transactions

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Yuh exposes no balance — see module docstring "Balance extraction".

        The number after " - " in the filename looks like a balance but
        isn't one (verified wrong on a real account: off by ~30k CHF from
        the transaction-confirmed total). Always None — base class default.
        """
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
            columns = [col.strip() for col in first_line.split(";")]
            return columns == cls.COLUMN_SIGNATURE
        except Exception:
            logger.debug("[Yuh] matches_file failed for %s", filepath, exc_info=True)
            return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _parse_row(
        self, row: dict, line_number: int, occurrence_counters: dict
    ) -> list[TransactionDict]:
        """
        Convert one CSV row dict into 1 or 2 TransactionDict.

        Called for each row that passed the KEPT_ACTIVITY_TYPES filter.
        Raises ValueError if a required field is missing or malformed.

        2 TransactionDict when the row is a currency conversion (BANK_AUTO_
        ORDER_EXECUTED, BANK_ORDER_EXECUTED with both DEBIT and CREDIT filled) :
        one CSV row = one movement, but two currencies, two legs. Dropping
        either leg silently understates one currency and overstates the other
        by the exact same amount — see CONTRACT in base.py (paired_leg_key).
        """
        date_str = self._parse_date(row["DATE"].strip())
        legs = self._parse_legs(row)
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
        # occurrence_index = how many times this exact (date, type, description)
        # combination has already appeared earlier in THIS file. This disambiguates
        # two identical transactions on the same day (e.g. two 2 CHF parking) while
        # staying stable across partial exports:
        #
        #   Full-year file : parking Jan-15 → occurrence_index=0 → hash H1
        #   January-only   : same parking   → occurrence_index=0 → same hash H1  ✓
        #
        # Contrast with line_number: full-year line 150 vs Jan-only line 5 → different
        # hashes → duplicate import. That's the bug occurrence_index fixes.
        #
        # The group key deliberately EXCLUDES the amount (unlike before this
        # supported the single-leg case only): a 2-leg conversion has two
        # different amounts (one per currency) but is still ONE occurrence of
        # ONE source row — including the amount would desync occurrence_index
        # between the debit and credit leg and break hash stability.
        group_key = (date_str, row["ACTIVITY TYPE"], description_raw)
        occurrence_index = occurrence_counters.get(group_key, 0)
        occurrence_counters[group_key] = occurrence_index + 1

        # paired_leg_key — only set when the row produced 2 legs. Built the same
        # way as import_hash minus the leg-specific amount/currency, so it's
        # identical for both legs and stable across partial re-exports.
        paired_leg_key = (
            f"{date_str}|{row['ACTIVITY TYPE']}|{description_raw}|{occurrence_index}"
            if len(legs) == 2
            else None
        )

        results = []
        for leg_index, (amount, currency) in enumerate(legs):
            raw = (
                f"{date_str}|{row['ACTIVITY TYPE']}|{description_raw}"
                f"|{occurrence_index}|leg{leg_index}|{amount}|{currency}"
            )
            import_hash = hashlib.sha256(raw.encode()).hexdigest()
            results.append(
                TransactionDict(
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
                    paired_leg_key=paired_leg_key,
                )
            )
        return results

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

    def _parse_legs(self, row: dict) -> list[tuple[float, str]]:
        """
        Extract [(amount, currency), ...] from the DEBIT/CREDIT columns.

        Yuh uses two separate column pairs:
            DEBIT  + DEBIT CURRENCY  → negative amount (money out)
            CREDIT + CREDIT CURRENCY → positive amount (money in)

        Most rows fill only ONE pair → 1 leg (a normal card payment, transfer...).

        Currency conversions (BANK_AUTO_ORDER_EXECUTED, BANK_ORDER_EXECUTED) fill
        BOTH pairs on the SAME row: e.g. DEBIT -8.30 CHF + CREDIT 8.90 EUR is one
        wallet movement expressed in two currencies, not a CHF expense. Returning
        only the debit leg (the old behaviour) silently drops the EUR credit —
        the account then looks 8.90 EUR poorer than it really is. Both legs are
        real Decimal amounts as written in the file (already signed — no abs()),
        including the rare case where Yuh puts a NEGATIVE value in CREDIT
        (observed on real exports: "Échange Francs suisses" selling CHF back).

        Raises ValueError if both pairs are empty or a value can't be parsed.
        """
        debit = row.get("DEBIT", "").strip()
        debit_currency = row.get("DEBIT CURRENCY", "").strip()
        credit = row.get("CREDIT", "").strip()
        credit_currency = row.get("CREDIT CURRENCY", "").strip()

        legs = []
        if debit:
            # Debit amounts are already negative in the file (e.g. "-196.20")
            legs.append((float(debit), debit_currency))
        if credit:
            # Usually positive, but Yuh sometimes writes a negative CREDIT
            # (e.g. selling CHF back to buy EUR) — kept as-is, never abs().
            legs.append((float(credit), credit_currency))

        if not legs:
            raise ValueError("Both DEBIT and CREDIT are empty")
        return legs

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
