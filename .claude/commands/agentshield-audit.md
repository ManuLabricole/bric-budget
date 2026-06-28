---
name: agentshield-audit
description: Scan sécurité du dossier de config d'agent (.claude) via AgentShield — read-only, grade /100 + findings
argument-hint: [chemin, défaut .claude]
---

# /agentshield-audit — Scan sécurité des configs d'agent

Scan **read-only** d'un dossier de configuration d'agent (prompt-injection, dérive de config, garde-fous manquants) via AgentShield.

## Lancer le scan
```bash
# La sous-commande est `scan --path <dossier>` (PAS `audit`). Défaut : .claude
PATH_ARG="${ARGUMENTS:-.claude}"
npx -y ecc-agentshield@1.5.0 scan --path "$PATH_ARG"
# variantes : --min-severity high | --format markdown | --deep (injection+sandbox+taint+opus)
```

⛔ **Jamais `--fix`** : ne pas laisser AgentShield auto-éditer les configs (machine à secrets bancaires). On lit le rapport, on corrige nous-mêmes les findings pertinents.

## Traiter le rapport
1. Lire le **grade /100** et les findings (CRITICAL / HIGH / MEDIUM / INFO).
2. **Juger chaque finding** : pertinent → corriger ; faux positif / hors contexte → écarter avec raison brève.
   - ⚠️ Faux positifs connus chez nous : `--no-verify` flaggé CRITICAL alors qu'il est en contexte *interdiction* (CLAUDE.md, `block_no_verify.sh`) ; "skill missing observation/version metadata" = doctrine ECC 2.0, non pertinente.
3. Récap à Emmanuel : finding → action.

Note : `npx` télécharge le package au 1er run (réseau requis). Outil ponctuel, **pas** un hook permanent. `scan` sans `--path` cible `~/.claude` ou le cwd.
