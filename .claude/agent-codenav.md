# Outillage de navigation de code pour agents

Donne aux agents (Claude Code / VSCode) une **vue archi** et une **nav rapide** pour
réduire les `read`/`grep` exploratoires. Trois couches complémentaires :

| Couche | Outil | Pour quoi |
|--------|-------|-----------|
| Carte | [ARCHITECTURE.md](../ARCHITECTURE.md) | Situer une responsabilité sans lire 10 fichiers |
| Symbole (sémantique) | **Serena** (MCP / LSP Pyright) | `find_symbol`, `find_referencing_symbols`, `get_symbols_overview` — call-sites réels, pas de bruit |
| Structure | **ast-grep** (tree-sitter) | Audits SR-XX structurels (IDOR, Decimal, print) sans matcher commentaires/strings |

---

## 1. Serena (MCP)

> `.mcp.json` est **gitignoré** → chaque poste/worktree ajoute le bloc lui-même.

Pré-requis host (une fois) :
```bash
brew install uv          # fournit uvx, le runtime de Serena
```

Bloc à coller dans `.mcp.json` (adapter le chemin `--project`) :
```json
"serena": {
  "command": "uvx",
  "args": [
    "--from", "git+https://github.com/oraios/serena",
    "serena", "start-mcp-server",
    "--context", "claude-code",
    "--project", "/chemin/absolu/vers/BudgetTracker"
  ]
}
```

- `--context claude-code` désactive les outils d'édition de Serena (doublon avec Claude Code) → on garde la **navigation**.
- Serena crée un dossier `.serena/` (cache + mémoires) — **gitignoré**.
- Premier démarrage : Serena indexe le projet (onboarding) ; les requêtes suivantes sont rapides.

Outils clés exposés : `get_symbols_overview` (sommaire d'un fichier), `find_symbol`
(aller à un symbole par nom), `find_referencing_symbols` (tous les call-sites).

## 2. ast-grep (CLI)

Pré-requis host : `brew install ast-grep`.

Audit complet (règles SR-XX dans `tools/ast-grep/rules/`, via `sgconfig.yml`) :
```bash
ast-grep scan                                   # toutes les règles
ast-grep scan --rule tools/ast-grep/rules/sr-idor-transaction-objects.yml
```

One-liners du quotidien (recherche structurelle ad hoc) :
```bash
ast-grep -p 'Decimal($X)' -l py src/            # tous les Decimal(...) — structurel, pas grep
ast-grep -p 'Transaction.objects.$METHOD($$$)' -l py # tous les accès au manager Transaction
```

> ⚠️ Les règles sont des **heuristiques d'audit** (faux positifs possibles) — un appui
> pour la revue/`security-auditor`, **pas un gate CI**. Le gate reste pre-commit +
> pre-push (pytest) + CI (mypy/semgrep).
