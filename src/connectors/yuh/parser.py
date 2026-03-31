"""
connectors/yuh/parser.py — Yuh CSV parser (Phase 1A).

CSV format (semicolon-separated, UTF-8 BOM):
    DATE ; ACTIVITY TYPE ; ACTIVITY NAME ; DEBIT ; DEBIT CURRENCY ;
    CREDIT ; CREDIT CURRENCY ; CARD NUMBER ; LOCALITY ; RECIPIENT ;
    SENDER ; FEES/COMMISSION ; BUY/SELL ; QUANTITY ; ASSET ; PRICE PER UNIT

Row filtering:
    KEEP:   CARD_TRANSACTION_OUT, PAYMENT_TRANSACTION_IN, PAYMENT_TRANSACTION_OUT
    IGNORE: REWARD_RECEIVED, BANK_AUTO_ORDER_EXECUTED, BANK_ORDER_EXECUTED

Balance extraction:
    Filename format: "Activités_2026_03_17 - 33,344.CSV"
    Pattern: everything after " - " and before ".CSV", strip commas → float
"""

from pathlib import Path

from connectors.base import BaseConnector, TransactionDict


class YuhConnector(BaseConnector):
    """
    Parses Yuh CSV exports into normalized TransactionDicts.
    Implemented in Phase 1A.
    """

    # Activity types to keep — everything else is ignored
    KEPT_ACTIVITY_TYPES = {
        "CARD_TRANSACTION_OUT",
        "PAYMENT_TRANSACTION_IN",
        "PAYMENT_TRANSACTION_OUT",
    }

    def parse(self, filepath: Path) -> list[TransactionDict]:
        # TODO Phase 1A: implement CSV parsing
        # Steps:
        #   1. Open file with UTF-8-sig encoding (strips BOM automatically)
        #   2. csv.DictReader with delimiter=";"
        #   3. Skip rows where ACTIVITY TYPE not in KEPT_ACTIVITY_TYPES
        #   4. Build amount: -DEBIT if debit row, +CREDIT if credit row
        #   5. merchant_name: clean ACTIVITY NAME (strip codes, capitalise)
        #   6. card_last_four: last 4 chars of CARD NUMBER if present
        #   7. import_hash: SHA1(date + activity_type + amount + description_raw)
        raise NotImplementedError("YuhConnector.parse() — implemented in Phase 1A")

    def extract_balance(self, filepath: Path) -> float | None:
        # TODO Phase 1A: implement balance extraction from filename
        # Pattern: "Activités_2026_03_17 - 33,344.CSV" → 33344.0
        raise NotImplementedError("YuhConnector.extract_balance() — implemented in Phase 1A")
