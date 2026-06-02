#!/usr/bin/env bash
# security_audit.sh — Audit sécurité BricBudget
# Usage: bash .claude/scripts/security_audit.sh [src_dir]
# Retourne 0 si propre, 1 si problèmes trouvés

SRC=${1:-src}
ERRORS=0

echo "=== Security Audit BricBudget ==="
echo "Répertoire : $SRC"
echo ""

# SR-001 — IDOR Transaction : get_object_or_404(Transaction, pk=...) sans for_user
echo "--- SR-001 : IDOR Transaction ---"
IDOR_TX=$(grep -rn "get_object_or_404(Transaction," "$SRC" --include="*.py" | grep -v "for_user" | grep -v "test" | grep -v "#")
if [ -n "$IDOR_TX" ]; then
  echo "❌ IDOR Transaction détecté :"
  echo "$IDOR_TX"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-002 — IDOR Account : Account.objects.filter sans members=request.user
echo "--- SR-002 : IDOR Account ---"
IDOR_ACC=$(grep -rn "Account.objects.filter(is_active=True)" "$SRC" --include="*.py" | grep -v "members=request.user" | grep -v "test" | grep -v "seed" | grep -v "#")
if [ -n "$IDOR_ACC" ]; then
  echo "❌ IDOR Account détecté :"
  echo "$IDOR_ACC"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-003 — IDOR ImportLog : file_hash lookup sans account__members
echo "--- SR-003 : IDOR ImportLog ---"
IDOR_IMP=$(grep -rn "ImportLog.objects.filter(file_hash=" "$SRC" --include="*.py" | grep -v "account__members" | grep -v "test" | grep -v "#")
if [ -n "$IDOR_IMP" ]; then
  echo "❌ IDOR ImportLog détecté :"
  echo "$IDOR_IMP"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-004 — Précision monétaire : Decimal(float_value) sans str()
echo "--- SR-004 : Précision monétaire ---"
DEC=$(grep -rn "Decimal(" "$SRC" --include="*.py" | grep -v "Decimal(str(" | grep -v "Decimal(\"" | grep -v "Decimal('" | grep -v "test" | grep -v "#" | grep -v "import")
if [ -n "$DEC" ]; then
  echo "⚠️  Decimal sans str() :"
  echo "$DEC"
  # Warning only, not error
else
  echo "✅ OK"
fi
echo ""

# SR-005 — Logs prod : print() dans le code source (hors tests, management commands, migrations, strings)
echo "--- SR-005 : print() en prod ---"
PRINTS=$(grep -rn "print(" "$SRC" --include="*.py" | grep -v "/tests/" | grep -v "management/commands/" | grep -v "/migrations/" | grep -v "\"print(" | grep -v "'print(" | grep -v "#")
if [ -n "$PRINTS" ]; then
  echo "❌ print() détecté hors tests/commands/migrations :"
  echo "$PRINTS"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-006 — IBAN/RIB hardcodés dans le code Python
echo "--- SR-006 : IBAN/RIB hardcodés ---"
IBAN=$(grep -rn "CH[0-9]\{2\}[0-9A-Z]\{4\}\|FR[0-9]\{2\}[0-9A-Z]\{23\}" "$SRC" --include="*.py" | grep -v "test" | grep -v "#")
if [ -n "$IBAN" ]; then
  echo "❌ IBAN/RIB détecté :"
  echo "$IBAN"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-007 — Transactions atomiques : opérations multi-étapes sans transaction.atomic()
# (difficile à auditer automatiquement — check manuel)
echo "--- SR-007 : Atomicité DB ---"
echo "ℹ️  Vérification manuelle requise pour les opérations multi-étapes."
echo ""

# Résultat final
echo "=== Résultat ==="
if [ $ERRORS -eq 0 ]; then
  echo "✅ Aucune anomalie critique détectée."
  exit 0
else
  echo "❌ $ERRORS anomalie(s) critique(s) — corriger avant merge."
  exit 1
fi
