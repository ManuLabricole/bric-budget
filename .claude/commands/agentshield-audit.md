---
name: agentshield-audit
description: Audit sécurité des configs d'agent (.claude/CLAUDE.md, settings, agents) via AgentShield — read-only, score /100 + findings
argument-hint: [chemin config, défaut .claude/CLAUDE.md]
---

# /agentshield-audit — Scan sécurité des configs d'agent

Audit **read-only** des fichiers de configuration d'agent (prompt-injection, dérive de config, garde-fous manquants) via AgentShield (102 règles statiques).

## Lancer l'audit
```bash
# Cible par défaut : .claude/CLAUDE.md (ou $ARGUMENTS si fourni)
TARGET="${ARGUMENTS:-.claude/CLAUDE.md}"
npx -y ecc-agentshield@latest audit "$TARGET" --json
```

⛔ **Jamais `--fix`** : ne pas laisser AgentShield auto-éditer les configs (machine à secrets bancaires). On lit le rapport, on corrige nous-mêmes les findings pertinents.

## Cibles utiles à scanner
- `.claude/CLAUDE.md` (instructions du projet)
- `.claude/settings.json` (permissions + hooks)
- les agents `.claude/agents/*.md` si présents

## Traiter le rapport
1. Lire le **score /100** et les findings (CRITICAL / WARNING / PASS).
2. **Juger chaque CRITICAL/WARNING** : pertinent → corriger dans la foulée (branche → fix → push) ; faux positif / hors contexte → écarter avec raison brève.
3. Récap à Emmanuel : finding → action.

Note : `npx` télécharge le package au 1er run (réseau requis). Outil ponctuel, **pas** un hook permanent.
