# /github — Maintenance GitHub Project BricBudget

> **Source de vérité = skill `github`** (`.claude/skills/github/SKILL.md`), chargé
> **automatiquement** dès qu'on touche aux issues, PR, milestones, labels ou au board.
> Cette commande n'est qu'un point d'entrée manuel : la convention 3-axes, les templates
> issue/PR et le cycle 1 issue = 1 branche = 1 PR vivent dans le skill (pas de duplication).

## Quand tu tapes `/github`

1. Audit rapide de l'état du board + convention :
   ```bash
   bash .claude/skills/github/scripts/check_convention.sh
   ```
2. Puis applique le skill `github` pour toute création/édition/fermeture d'issue ou PR.

⚠️ Rappels durs (détails dans le skill) : `unset GITHUB_TOKEN` ; repo = `ManuLabricole/bric-budget` ;
toute issue = milestone version + label type + board ; PR `--base development` ; Claude ne merge jamais.
