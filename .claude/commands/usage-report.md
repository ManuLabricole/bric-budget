---
name: usage-report
description: Agrège le log de traçage .claude (agents/skills/commands) — top usage + skills jamais utiles (candidates rétrogradation)
---

# /usage-report — Rapport d'usage de l'outillage .claude

Lit `~/.claude/logs/tool-usage.jsonl` (alimenté par `.claude/hooks/usage_logger.py`) et produit un classement d'usage.

## Agrégat global
```bash
python3 - <<'PY'
import json, collections, os
p = os.path.expanduser("~/.claude/logs/tool-usage.jsonl")
if not os.path.exists(p):
    print("Aucun log encore. Le hook usage_logger se déclenchera au 1er agent/skill/command.")
else:
    c = collections.Counter()
    total = 0
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line); c[(r["kind"], r["name"])] += 1; total += 1
            except Exception:
                pass
    print(f"{total} invocations loguées\n")
    for (kind, name), n in c.most_common():
        print(f"{n:4}  {kind:8}  {name}")
PY
```

## Analyse à produire (après l'agrégat)
- **Top agents / skills / commands** réellement utilisés.
- **Skills `ecc-*` jamais (ou quasi jamais) invoquées** → candidates à rétrograder de `~/.claude/skills/ecc-*` vers `~/.claude/reference/ecc/` (réduit la pollution de l'intent-routing).
- **Skills qui se déclenchent à tort** (présentes au log mais hors contexte attendu) → à surveiller.
- Recommandation concrète : quoi garder actif, quoi rétrograder.

## Filtres utiles
```bash
# par type
grep '"kind": "skill"' ~/.claude/logs/tool-usage.jsonl | wc -l
# par repo
grep BudgetTracker ~/.claude/logs/tool-usage.jsonl | wc -l
```
