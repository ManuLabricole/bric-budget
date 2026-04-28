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

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict


class TransactionDict(TypedDict):
    """
    Normalized transaction data returned by every parser.

    All parsers must produce this exact shape — the import service
    depends on it to create Transaction model instances.

    Fields with | None can be None if the source doesn't provide them.
    """

    date: str  # ISO 8601 date: "2026-03-17"
    time: str | None  # "HH:MM:SS" if available (UBS yes, Yuh/CIC no)
    amount: float  # negative = debit (money out), positive = credit (money in)
    currency: str  # ISO 4217: "CHF", "EUR", "GBP"...
    description_raw: (
        str  # raw text from the bank — never modified, used for audit + rules
    )
    merchant_name: str  # cleaned display name pre-filled from description_raw
    card_last_four: str | None  # "4521" for card transactions, None otherwise
    import_hash: str  # SHA256 of key fields — used for deduplication across imports


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
            - UBS: line 6 of the metadata block ("Solde final:;7281.45;")
        """
        return None

    def _normalize_merchant(self, text: str) -> str:
        """
        Final normalization step shared by all connectors.

        Collapses consecutive spaces (padding artifact in some bank exports),
        strips leading/trailing whitespace, then title-cases the result.

        Called as the last step in each connector's _clean_merchant() so the
        output format is consistent regardless of the source bank.

        Example: "FEEL EAT SARL            LA CHAUX-D" → "Feel Eat Sarl La Chaux-D"
        """
        collapsed = re.sub(r" {2,}", " ", text).strip()
        return collapsed.title()

    def extract_account_identifier(self, filepath: Path) -> str | None:
        """
        Extract a normalized account identifier from the file.

        Used by import commands to find the matching Account in the database
        via Account.contract_number — the universal import matching key.

        Default: returns None — override in connectors that embed an identifier.

        Who overrides:
            - UBSConnector  → IBAN normalized (no spaces): "CH9XXXXXXXXXXXXXXXXXXX"
            - YuhConnector  → None (no identifier in Yuh files — convention fallback)
            - CICConnector  → None (multi-account file — identifier resolved per sheet)

        Future connectors:
            - FinpensionConnector → contract number extracted from PDF/CSV header
            - UK connector        → sort code + account number

        The returned string must match Account.contract_number exactly (no spaces,
        same case) — the import command does a direct .get(contract_number=identifier).
        """
        return None
