#!/usr/bin/env bash
# security_audit.sh — Audit sécurité BricBudget
# Usage: bash .claude/skills/security/scripts/security_audit.sh [src_dir]
# Retourne 0 si propre, 1 si problèmes trouvés

SRC=${1:-src}
ERRORS=0

echo "=== Security Audit BricBudget ==="
echo "Répertoire : $SRC"
echo ""

# SR-001a — IDOR Transaction : get_object_or_404(Transaction, pk=...) sans for_user
echo "--- SR-001a : IDOR Transaction ---"
IDOR_TX=$(grep -rn "get_object_or_404(Transaction," "$SRC" --include="*.py" \
  | grep -v "for_user" | grep -v "test" | grep -v "#")
if [ -n "$IDOR_TX" ]; then
  echo "❌ IDOR Transaction détecté :"
  echo "$IDOR_TX"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-001b — IDOR Account : Account.objects.filter(is_active=True) sans members=request.user
echo "--- SR-001b : IDOR Account ---"
IDOR_ACC=$(grep -rn "Account.objects.filter(is_active=True)" "$SRC" --include="*.py" \
  | grep -v "members=request.user" | grep -v "test" | grep -v "seed" | grep -v "#")
if [ -n "$IDOR_ACC" ]; then
  echo "❌ IDOR Account détecté :"
  echo "$IDOR_ACC"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-001c — IDOR ImportLog : ImportLog.objects.filter(file_hash=...) sans account__members
echo "--- SR-001c : IDOR ImportLog ---"
IDOR_IMP=$(grep -rn "ImportLog.objects.filter(file_hash=" "$SRC" --include="*.py" \
  | grep -v "account__members" | grep -v "test" | grep -v "#")
if [ -n "$IDOR_IMP" ]; then
  echo "❌ IDOR ImportLog détecté :"
  echo "$IDOR_IMP"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-002 — Précision monétaire : Decimal(float_literal) sans str()
# Note : Decimal(int) est sûr — ce check ne cible que les floats littéraux.
# Les variables de type float sont couvertes par la règle semgrep custom-rules.yml.
echo "--- SR-002 : Précision monétaire (float literals) ---"
DEC=$(grep -rEn "Decimal\([0-9]+\.[0-9]" "$SRC" --include="*.py" \
  | grep -v "test" | grep -v "#")
if [ -n "$DEC" ]; then
  echo "❌ Decimal(float_literal) sans str() :"
  echo "$DEC"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK (variables float → voir semgrep)"
fi
echo ""

# SR-003 — Atomicité DB (vérification manuelle)
echo "--- SR-003 : Atomicité DB ---"
echo "ℹ️  Vérification manuelle : toute opération multi-étapes doit être dans transaction.atomic()."
echo ""

# SR-004 — Migrations réversibles : RunPython sans reverse_code ni RunPython.noop
# Vérifie par fichier entier (reverse_code= peut être sur une ligne différente).
echo "--- SR-004 : Migrations réversibles ---"
RUNPY_BAD=""
while IFS= read -r mig_file; do
  if grep -q "RunPython(" "$mig_file"; then
    if ! grep -qE "reverse_code=|reverse=|RunPython\.noop" "$mig_file"; then
      RUNPY_BAD="$RUNPY_BAD\n$mig_file"
    fi
  fi
done < <(find "$SRC" -path "*/migrations/*.py" ! -path "*/.venv/*" ! -name "*.pyc" 2>/dev/null)
if [ -n "$RUNPY_BAD" ]; then
  echo "❌ Migration(s) avec RunPython sans reverse_code :"
  echo -e "$RUNPY_BAD"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-005 — Pas de print() en production
echo "--- SR-005 : print() en prod ---"
PRINTS=$(grep -rn "print(" "$SRC" --include="*.py" \
  | grep -v "/tests/" \
  | grep -v "management/commands/" \
  | grep -v "/migrations/" \
  | grep -v '"print(' \
  | grep -v "'print(" \
  | grep -v "#")
if [ -n "$PRINTS" ]; then
  echo "❌ print() détecté hors tests/commands/migrations :"
  echo "$PRINTS"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-008 — Données bancaires hors code (IBAN/RIB)
echo "--- SR-008 : IBAN/RIB hardcodés ---"
IBAN=$(grep -rn "CH[0-9]\{2\}[0-9A-Z]\{4\}\|FR[0-9]\{2\}[0-9A-Z]\{23\}" "$SRC" --include="*.py" \
  | grep -v "test" | grep -v "#")
if [ -n "$IBAN" ]; then
  echo "❌ IBAN/RIB détecté dans le code :"
  echo "$IBAN"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-009 — Env vars normalisées : config("LOG_LEVEL") doit avoir .strip().upper()
# Cible uniquement les variables d'env de niveau/mode connues (pas AUTH_USER_MODEL etc.)
echo "--- SR-009 : Env vars normalisées ---"
ENV_RAW=$(grep -rn 'config("LOG_LEVEL\|config("DJANGO_ENV\|config("APP_ENV\|config("DEBUG_MODE' \
  "$SRC" --include="*.py" \
  | grep -v "\.upper()" \
  | grep -v "test" \
  | grep -v "#")
if [ -n "$ENV_RAW" ]; then
  echo "⚠️  config() d'env var de niveau/mode sans .strip().upper() :"
  echo "$ENV_RAW"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ OK"
fi
echo ""

# SR-010 — Clé cryptographique (vérification manuelle)
echo "--- SR-010 : Clé cryptographique ---"
echo "ℹ️  Vérification manuelle : grep -A10 'def _get_fernet' src/imports/storage.py → doit contenir 'if not keys'."
echo ""

# SR-011 — Fonctions bool (vérification manuelle)
echo "--- SR-011 : Fonctions bool ---"
echo "ℹ️  Vérification manuelle : toute méthode -> bool doit avoir return False explicite sur tous les chemins."
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
