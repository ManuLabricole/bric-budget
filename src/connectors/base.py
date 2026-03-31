"""
connectors/base.py — Abstract base class for all data source connectors.

Why a base class?
-----------------
Every connector (Yuh, CIC, Finpension...) does the same job:
    read a file → return a list of normalized transaction dicts.

The base class defines the contract: what a connector must return.
Each sub-class implements the specifics: CSV vs Excel, column names, encoding...

The import service (Phase 1A) only knows about BaseConnector — it doesn't care
whether it's reading a Yuh CSV or a CIC Excel. That's the point of abstraction.

TransactionDict is the normalized format every parser must produce.
It maps 1-to-1 with the Transaction model fields relevant at import time.
The import service handles DB insertion, deduplication, and categorisation.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict


class TransactionDict(TypedDict):
    """
    Normalized transaction data returned by every parser.

    All parsers must produce this exact shape — the import service
    depends on it to create Transaction model instances.

    Fields marked Optional can be None if the source doesn't provide them.
    """
    date:             str        # ISO 8601: "2026-03-17"
    amount:           float      # negative = debit, positive = credit
    currency:         str        # ISO 4217: "CHF", "EUR"...
    description_raw:  str        # raw text from the bank, never modified
    merchant_name:    str        # cleaned name pre-filled from description_raw
    card_last_four:   str | None # e.g. "4521" — None if not a card transaction
    import_hash:      str        # SHA1 of the raw row — used for deduplication


class BaseConnector(ABC):
    """
    Abstract connector — one concrete subclass per data source.

    Usage (in the import service):
        connector = YuhConnector()
        transactions = connector.parse(Path("Activités_2026_03_17 - 33,344.CSV"))
        balance = connector.extract_balance(Path("Activités_2026_03_17 - 33,344.CSV"))

    Subclasses implement parse() and optionally extract_balance().
    """

    @abstractmethod
    def parse(self, filepath: Path) -> list[TransactionDict]:
        """
        Parse a source file and return a list of normalized transactions.

        Must skip rows that are not actual transactions (fees, rewards, orders...).
        Must compute import_hash for each row for deduplication.
        Must never raise — catch parsing errors per-row and skip with a warning.
        """
        ...

    def extract_balance(self, filepath: Path) -> float | None:
        """
        Extract the account balance from the file, if available.

        Default: returns None (not all sources encode balance in the file).
        Override in connectors where balance is available:
            - Yuh: encoded in the filename ("Activités_2026_03_17 - 33,344.CSV")
        """
        return None
