---
paths:
  - "src/**/*.py"
  - "src/**/*.html"
---

# Definition of Done — gate obligatoire avant de déclarer « terminé »

> Chargé par chemin : **toujours en contexte dès que je touche du code**.
> Ce gate existe pour qu'Emmanuel ait **confiance du premier coup**. La revue
> (`bricbudget-reviewer`) et CodeRabbit sont un **filet de sécurité**, pas le
> contrôle qualité : si l'un d'eux trouve un de ces 4 problèmes, **j'ai échoué le gate**.
>
> ⛔ Je ne dis pas « c'est fait » — je **montre la preuve** des 4 gates. Affirmer ≠ prouver.

---

## Les 4 gates (les questions qu'Emmanuel ne doit JAMAIS avoir à reposer)

### 1. « Tes tests sont de vrais tests, pas du théâtre ? »
Un test qui passe sans rien garantir fait perdre du temps. **Preuve exigée** :
- Le test **échoue d'abord** (RED) quand le comportement est cassé — je l'ai vérifié, pas supposé.
- Il **assert le comportement**, pas le status : ⛔ `assert resp.status_code == 200` comme **seule** assertion = théâtre.
- Pas de sur-mock : si je mocke ce que je teste, je ne teste rien. Mock au **boundary** (API externe, taux de change), pas le cœur.
- Diff touchant `src/tests/**` ou ajoutant du comportement → **agent `test-auditor`** (assertions faibles, sur-mock, flaky, score de mutation). Voir `rules/testing.md`.
- E2E : `to_be_visible()` ne prouve rien (clipping/occlusion) → hit-test le pixel (`elementFromPoint`). Reproduire le bug AVANT le fix.

> Je déclare le gate passé en disant **quel comportement** chaque test garde et **comment je l'ai vu rougir**.

### 2. « C'est refactoré ? Simplifie. »
**Preuve exigée** — avant de déclarer terminé, je fais une **passe d'altitude** :
- DRY : la logique dupliquée est extraite (pas de copier-coller qui dérive).
- KISS/YAGNI : la solution la plus simple qui marche ; pas d'abstraction spéculative, pas de paramètre « au cas où ».
- Fonctions < 50 lignes, fichiers < 800, imbrication < 4 niveaux (early returns).
- Je relis **mon propre diff** et je supprime le mort/redondant **avant** de pousser. Au moindre doute → `/simplify` ou `/code-review` sur le diff.

> Je déclare le gate passé en pointant **ce que j'ai simplifié/supprimé**, ou en affirmant explicitement « rien à simplifier, voici pourquoi ».

### 3. « Tu as bien pris connaissance de l'archi ? Pas de spaghetti ? »
**Preuve exigée** — je ne code pas à l'aveugle :
- J'ai lu la zone touchée (`/research` ou lecture ciblée) **avant** d'écrire — je sais où vivent les choses.
- Je **nomme le pattern existant que je copie** : « je suis le même découpage que `<module>` / `<vue>` ». Si je n'en trouve aucun à copier → drapeau rouge, je le signale **avant** de coder.
- Frontières respectées : `services/` = un module par service (pas un dossier racine), `connectors/` = parsers, `views/` package par app, identité compte = `Account.iban|contract_number`. Voir `project/UBIQUITOUS_LANGUAGE.md`.
- Pas de nouvelle couche/indirection sans raison nommée. Méfiance archi par défaut : suivre les patterns du repo, pas en inventer.

> Je déclare le gate passé en **citant le pattern que je réplique** et la frontière de module où le code atterrit.

### 4. « Sûr que c'est Django + dev mindset, pas un workaround pourri ? »
**Preuve exigée** — c'est idiomatique, pas un contournement :
- J'utilise l'outil Django natif (ORM/managers, forms, validators, `transaction.atomic`, signals avec parcimonie, migrations propres) — pas du SQL brut ni du bricolage Python par-dessus l'ORM.
- HTMX : état côté serveur, pas de JS custom ; partials propres ; `{% comment %}` jamais `{# #}` multiligne.
- SR-XX non négociables : IDOR `for_user`, `Decimal(str(x))`, `transaction.atomic`, `logger` jamais `print()`, IBAN/RIB en `.env`. Voir `rules/django.md` + skill `security`.
- Si je m'apprête à contourner le framework (« je le fais à la main parce que… »), **STOP** : c'est le signal d'un workaround → chercher la voie Django d'abord.

> Je déclare le gate passé en nommant **l'outil Django/HTMX idiomatique** que j'ai employé.

---

## Avant de dire « terminé »

1. **Vérif live GET + POST** (`manage.py shell` / app réelle) — **due, jamais couverte par la CI**.
2. Les **4 gates ci-dessus prouvés** (pas affirmés) dans mon récap.
3. `silent-failure-hunter` si du code peut avaler une erreur.
4. **Alors seulement** : revue (`bricbudget-reviewer`, + `security-auditor` si sensible) → PR → CodeRabbit.

Si la revue ou CodeRabbit trouve l'un des 4 → **ce n'est pas une victoire de la revue, c'est un trou dans mon gate** : je note pourquoi je l'ai raté pour ne pas recommencer (auto-memory).
