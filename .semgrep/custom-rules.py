# Fichier de test de .semgrep/custom-rules.yml — validé par `semgrep --test`.
# (les lignes annotées plus bas indiquent ce qui doit / ne doit pas matcher)
from decimal import Decimal

# ruleid: decimal-from-float
bad = Decimal(float("1.5"))

# ok: decimal-from-float
good_str = Decimal(str(1.5))

# ok: decimal-from-float
good_int = Decimal(5)

# ok: decimal-from-float
good_literal = Decimal("1.5")
