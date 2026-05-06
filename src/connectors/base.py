"""
connectors/base.py — Abstract base class for all data source connectors.

Why a base class?
-----------------
Every connector (Yuh, CIC, UBS, Finpension...) does the same job:
    read a file → return a list of normalized transaction dicts.

The base class defines the contract: what a connector must return.
Each sub-class implements the specifics: CSV vs Excel, column names, encoding...

The import service only knows about BaseConnector — it doesn't care whether
it's reading a Yuh CSV or a CIC Excel. That's the point of abstraction.

TransactionDict is the normalized format every parser must produce.
It maps to the Transaction model fields relevant at import time.
The import service handles DB insertion, deduplication, and categorisation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTRACT : import_hash
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import_hash is the per-transaction deduplication key. It must satisfy:

  STABLE      Two exports of the same transaction (from different date-range
              exports of the same account) produce the same hash. This is the
              hardest property to get right — see each connector for how it's
              achieved.

  UNIQUE      Two genuinely distinct transactions never produce the same hash,
              even if they share date + amount + description (e.g. two coffees
              at the same café on the same day).

Use the best available identifier, in priority order:

  1. Bank-assigned transaction ID (best)
       UBS : "No de transaction" column — globally unique, bank-guaranteed.
       Usage : sha256("ubs_tx|{no_transaction}")

  2. Running balance after transaction
       CIC : column F (Solde) — uniquely identifies a transaction's position
             in the account's history. Two transactions cannot leave the same
             balance unless there is a concurrent reversal (extremely rare).
       Usage : sha256("{rib}|{date}|{amount}|{description}")  ← current
       Note  : balance_after is used for BalanceSnapshot, NOT for the hash,
               to avoid re-hashing historical transactions that lack stored balance.

  3. Stable positional identifier
       Yuh : line_number in the CSV. Yuh always exports chronologically
             (new transactions appended at the end), so line_number is
             stable across re-exports from the same origin date.
       Usage : sha256("{line_number}|{date}|{type}|{amount}|{description}")

The hash is a SHA256 hex string stored in Transaction.import_hash (unique=True).
The ImportService checks this column before inserting — no DB-level collision needed
for the happy path, but the unique constraint is the safety net.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTRACT : balance_after
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

balance_after is the account balance AFTER this transaction was applied.
It enables ImportService to create daily BalanceSnapshots automatically,
giving us a complete balance history curve without extra API calls.

Set to None if the source file does not provide a per-row balance:
  - Yuh  : balance only in the filename (one snapshot per import)
  - UBS  : balance only in the file header (one snapshot per import)
  - CIC  : balance in column F on every row → daily snapshots possible ✓

Future connectors (Finpension, Swissquote...) should set this when available.
"""

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict


class TransactionDict(TypedDict):
    """
    Normalized transaction data returned by every parser.

    All parsers must produce this exact shape — the import service
    depends on it to create Transaction model instances.

    Fields marked | None can be None if the source doesn't provide them.
    """

    date: str  # ISO 8601: "2026-03-17"
    time: str | None  # "HH:MM:SS" — UBS card payments only, None otherwise
    amount: float  # negative = debit (out), positive = credit (in)
    currency: str  # ISO 4217: "CHF", "EUR", "GBP"...
    description_raw: str  # raw bank text — never modified, used for rules + audit
    merchant_name: str  # cleaned display name pre-filled from description_raw
    card_last_four: str | None  # "4521" for card tx, None otherwise

    # Deduplication key — see CONTRACT above for rules on stability + uniqueness.
    import_hash: str  # SHA256 hex string

    # Running balance after this transaction — None if source doesn't provide it.
    # Used by ImportService to create daily BalanceSnapshots.
    # See CONTRACT above for which connectors set this.
    balance_after: float | None


class BaseConnector(ABC):
    """
    Abstract connector — one concrete subclass per data source.

    Subclasses implement parse() and optionally extract_balance(),
    extract_account_identifier(), and extract_account_name().
    """

    @abstractmethod
    def parse(self, filepath: Path) -> list[TransactionDict]:
        """
        Parse a source file and return a list of normalized transactions.

        Must skip rows that are not actual transactions (fees, rewards, FX...).
        Must compute import_hash per row — see CONTRACT in module docstring.
        Must set balance_after per row when available, None otherwise.
        Must never raise — catch parsing errors per-row and skip with a warning.
        """
        ...

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Extract the closing account balance from the file, if available.

        This is the balance at the END of the export period — used as the
        authoritative BalanceSnapshot for the import date.

        Default: None. Override when the source embeds a closing balance:
            Yuh : in the filename  ("Activités_2026_03_17 - 33,344.CSV")
            UBS : in file header   (line 6: "Solde final:;7281.45;")
            CIC : in sheet footer  ("Solde au 30/03/2026 : 798.27")

        Distinct from balance_after in TransactionDict — that's a per-row value
        for daily history; this is the single closing balance for the snapshot.
        """
        return None

    def extract_account_identifier(self, filepath: Path) -> str | None:
        """
        Extract a normalized account identifier from the file.

        Used by the resolver to find the matching Account in the DB via
        Account.iban or Account.contract_number.

        Default: None. Override in connectors that embed an identifier:
            UBS : IBAN normalized (no spaces) from line 2 → matches Account.iban
            CIC : RIB per sheet → matches Account.contract_number
            Yuh : None (no identifier — convention-based resolution)

        Future connectors:
            Finpension : contract number from CSV/PDF header → Account.contract_number
            Swissquote : account number → Account.contract_number
        """
        return None

    def _normalize_merchant(self, text: str) -> str:
        """
        Shared normalization: collapse spaces, strip, title-case.

        Example: "FEEL EAT SARL            LA CHAUX-D" → "Feel Eat Sarl La Chaux-D"
        """
        collapsed = re.sub(r" {2,}", " ", text).strip()
        return collapsed.title()

    def extract_account_name(self, filepath: Path) -> str | None:
        """
        Extract a human-readable account name hint from the file.

        Used to pre-fill the account creation form when resolve_accounts() raises
        AccountNotFound. The user can always override in the form.

        Default: None. Override in connectors that embed a human-readable name:
            UBS : "Numéro de compte" from line 1 → "UBS 0243 00693382.40"
        """
        return None
