# /sync — Sync gate de fin de session

> Inspiré de "Solving Hard Problems" (Dex) — "intentional compaction".
> But : garantir que **tous** les fichiers `.claude/` reflètent l'état courant.
>
> 🔒 **Règle fondamentale** : entre la création et le merge d'une branche, `.claude/` ne doit JAMAIS être désynchronisé. `/sync` est le seul moment où cette synchronisation est vérifiée et appliquée.
>
> ⚠️  **Note** : `/sync` met à jour les fichiers `.claude/`. Pour comprimer le contexte de la conversation,
>     utilise la commande native `/compact` de Claude Code APRÈS avoir terminé `/sync`.

---

## Quand utiliser

- En fin de session (avant de fermer)
- Avant de merger une PR
- Avant de changer de tâche radicalement

---

## Protocole — 6 phases, dans l'ordre

### Phase 1 — État git + tests (lecture)

```bash
git branch --show-current
git log --oneline -5
git status
cd src && poetry run pytest --tb=no -q 2>&1 | tail -3
make check 2>&1 | tail -3
```

### Phase 2 — Mise à jour CONTEXT.md (obligatoire)

Réécrire la section "État Git" + "scope restant" avec l'état réel observé.
```
Branche courante : <branche> (<état>)
Dernière PR : #N (<titre> — état)
Dernier commit : <hash> <message>
Tests : N passed / N failed
```

### Phase 3 — Entrée CHANGELOG.md (obligatoire, append-only)

```markdown
## YYYY-MM-DD — Session XX : <titre court>

**Contexte**
<1-2 phrases : pourquoi cette session>

**Livré**
- <bullet list de ce qui a été fait>

**Tests**
- N passed / N failed

**Prochaine session**
- <ce qui reste>
```

### Phase 4 — 🔒 SYNC GATE : balayer chaque fichier `.claude/`

**Pour CHAQUE fichier ci-dessous, se poser explicitement la question et appliquer si nécessaire.**

#### 4.1 — DECISIONS.md
> "Une décision archi a-t-elle été actée pendant cette session ?"
> Critère : un arbitrage entre ≥ 2 options avec un trade-off documenté.

Si oui → append ligne :
```markdown
| YYYY-MM-DD | D-0XX | <sujet 3-5 mots> | <décision concrète> | <pourquoi : contrainte + alternative rejetée> |
```
Calcul ID : `grep -E "^\| 2026-.. \| D-0[0-9]+" .claude/DECISIONS.md | tail -1` → incrémenter.

#### 4.2 — SECURITY_RULES.md
> "Une nouvelle règle de sécurité a-t-elle été identifiée (audit, fix, incident) ?"

Si oui → ajouter section SR-0XX avec ID, règle, justification, exemple code.

#### 4.3 — UBIQUITOUS_LANGUAGE.md
> "Un nouveau concept domain ou pattern a-t-il émergé ?"
> Exemples : nouveau modèle Django, nouveau type d'événement, nouvelle abstraction.

Si oui → ajouter entrée dans la section appropriée (vocabulaire, module map, anti-patterns).

#### 4.4 — MEMO.md
> "Un pattern Django/HTMX/Python non-évident a-t-il été utilisé/découvert ?"
> Exemples : piège résolu, commande utile récurrente, snippet à mémoriser.

Si oui → append section dans MEMO.md avec exemple concret.

#### 4.5 — CLAUDE.md
> "Une règle GLOBALE et toujours active a-t-elle changé ?"

Cas rare. Si oui → modifier CLAUDE.md. Sinon **ne pas toucher**.

#### 4.6 — Memory (`~/.claude/projects/.../memory/`)
> "Un feedback utilisateur récurrent ou une préférence durable est-elle apparue ?"

Si oui → Write nouvelle entrée `feedback_<topic>.md` ou `project_<topic>.md` + ajouter ligne MEMORY.md.

### Phase 5 — Nettoyer les fichiers research/plan temporaires

```bash
ls .claude/research_*.md .claude/plan_*.md 2>/dev/null
mv .claude/research_*.md .claude/history/ 2>/dev/null || true
mv .claude/plan_*.md .claude/history/ 2>/dev/null || true
```

### Phase 6 — Rapport final

```
✅ Sync gate OK
📋 CONTEXT.md  ······ mis à jour
📋 CHANGELOG.md ····· entrée session ajoutée
📋 DECISIONS.md ····· [N décisions ajoutées | aucune]
📋 SECURITY_RULES.md  [N règles | inchangé]
📋 UBIQUITOUS_LANG.md [N concepts | inchangé]
📋 MEMO.md ·········· [N patterns | inchangé]
📋 Memory ··········· [N entrées | inchangé]
🗂  Research/plan archivés vers history/
→ Lance /compact pour compresser le contexte, puis /hello pour la prochaine session.
```

---

## Règles

- **Ne jamais mentir** dans CONTEXT.md ou CHANGELOG.md — si quelque chose ne fonctionne pas, le noter
- **CHANGELOG append-only** — ne pas modifier les entrées passées
- **DECISIONS append-only** — révisions = nouvelle ligne avec `D-0XX-rev`
- Si `make test` échoue → noter dans CONTEXT.md AVANT de sync
- Si la phase 4 trouve qu'un fichier devait être mis à jour mais ne l'a pas été pendant la session → c'est **un signal d'erreur**, le mentionner dans le rapport