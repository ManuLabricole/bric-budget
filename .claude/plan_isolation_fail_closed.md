# Plan : Isolation multi-user fail-closed (epic)
Date : 2026-06-23
Branch : à créer par phase depuis `development` (epic = parapluie sans branche)
Statut : ⏳ EN ATTENTE DE VALIDATION — aucun code écrit

> Recherche faite (RLS Postgres, django-rls, pooling `SET LOCAL`, footgun table-owner-bypass).
> Cause racine : `for_user` = scoping **applicatif opt-in fail-OPEN** (149 sites + reverse-FK) ;
> `BudgetTarget` sans `owner` (OneToOne→Category) = objectifs sur catégories système
> structurellement partagés. Cible : **fail-CLOSED au niveau DB** (Postgres RLS) + fix schéma.

---

## Phase 0 — Spike & ADR (PAS de code applicatif) [~1/2 j]

**But** : lever les 2 inconnues bloquantes AVANT d'écrire des migrations RLS.

1. **Modèle de connexion Railway** (bloquant n°1) :
   - L'app se connecte-t-elle en tant que **propriétaire des tables** ? (→ RLS ignorée sans `FORCE`).
   - Y a-t-il un pooler (PgBouncer) ? `pool_mode` ? (`statement` casse `SET LOCAL` → inutilisable).
   - Vérifs : `mcp__railway__list_variables`, `SELECT current_user, session_user;`, `\du`.
2. **Lib vs hand-rolled** : évaluer `django-rls` (django-rls.com / kdpisda) — supporte Django 4.2–6.0,
   PG15+, policies en `Meta`. **Reco : hand-rolled `RowLevelSecurityConstraint`** (pattern Alasco,
   ~100 lignes, dans notre contrôle, zéro lock-in sur lib jeune) — sauf si django-rls couvre
   proprement le cas système(owner NULL)/perso + le bypass seeds.
3. **Stratégie rôle runtime** : créer un rôle Postgres restreint (non-owner, sans `BYPASSRLS`,
   non-superuser) pour le runtime ; migrations en rôle privilégié. Acter comment fournir 2 rôles
   sur Railway (2e role + 2e `DATABASE_URL`, ou `SET ROLE` post-connexion).

**Livrable** : ADR dans `project/DECISIONS.md` (lib choisie, rôle, pooling). **Go/no-go RLS ici.**
**Test** : aucun — c'est une décision documentée.

---

## Phase 1 — Fix schéma `BudgetTarget` [~1 j] · INDÉPENDANT de RLS, livre tout de suite

**Fichier** : `src/transactions/models.py`
**Quoi** : donner un `owner` à `BudgetTarget` et autoriser un objectif par (user, catégorie).

```python
class BudgetTarget(models.Model):
    # AVANT : OneToOneField(Category) → 1 row global par catégorie = partagé sur les system cats.
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budget_targets")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="budget_targets", db_index=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    objects = OwnedQuerySet.as_manager()  # for_user dispo (owner NULL impossible ici : tjrs perso)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "category"], name="budgettarget_owner_category_uniq"),
        ]
```

**Migration** (réversible, SR-004) : add `owner` (nullable temporaire) → data-migrate
(`target.owner = target.category.owner` si perso ; **les targets sur catégorie système sont
ambigus/partagés → décision Phase 0 : purge** car données pré-launch, pas de perte réelle) →
`owner` NOT NULL → drop OneToOne, add FK + contrainte.

**Vues** : remplacer le band-aid `category__in=for_user` (PR #200) par le scoping owner natif :
`BudgetTarget.objects.for_user(request.user)` dans `transactions.py` (×2) + `core.py`.
`related_name` `budget_target` → `budget_targets` : MAJ templates (`category.budget_target` → logique liste).

**Test** : `tests/test_budget_target_isolation.py` — user A et B ont CHACUN un objectif sur la
catégorie système « Alimentation » sans collision ; B ne lit pas celui de A. `make test`.

---

## Phase 2 — Socle RLS : rôle + middleware + bypass (plomberie, 0 policy) [~1 j]

**Fichiers** : `src/config/db_rls.py` (backend ou hook), `src/config/middleware.py`, `src/config/settings.py`

```python
# Pattern pooling-safe (recherche confirmée) : SET LOCAL dans la transaction de requête.
# ATOMIC_REQUESTS=True wrappe la vue ; le middleware tourne HORS transaction → on pose la var
# via un backend custom qui l'exécute à la création du curseur, OU au début de la txn (signal).
import contextvars
_current_user_id = contextvars.ContextVar("current_user_id", default=None)

@contextmanager
def rls_bypass():
    """Seeds / admin / imports / commands : exécuter hors filtre RLS."""
    token = _current_user_id.set("BYPASS")
    try: yield
    finally: _current_user_id.reset(token)
```

- `ATOMIC_REQUESTS = True` sur la DB par défaut.
- Middleware : `_current_user_id.set(request.user.id)` ; le backend émet
  `SET LOCAL app.current_user_id = '<id>'` (ou `'BYPASS'`) sur chaque curseur de la txn.
- **Vérif pooling** : `SET LOCAL` + tout en transaction (jamais `SET`/`SET SESSION`).

**Test** : middleware pose bien la var (`SELECT current_setting('app.current_user_id')`),
se reset après la requête, `rls_bypass()` fonctionne. Pas encore de policy → pas de filtrage.

---

## Phase 3 — Policies RLS sur les modèles Owned [~1–2 j]

**Fichier** : `src/transactions/migrations/00XX_rls_policies.py` + helper `RowLevelSecurityConstraint`.

Pour `Category`, `SubCategory`, `CategorizationRule`, `BudgetTarget` :
```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;            -- sinon owner des tables bypass (footgun n°1)
CREATE POLICY <t>_owned ON <t>
  USING (
    current_setting('app.current_user_id', true) = 'BYPASS'
    OR owner_id IS NULL                                -- lignes système, lisibles par tous
    OR owner_id = current_setting('app.current_user_id', true)::int
  )
  WITH CHECK (                                         -- écriture : interdit de créer du système
    current_setting('app.current_user_id', true) = 'BYPASS'  -- ou d'assigner à autrui
    OR owner_id = current_setting('app.current_user_id', true)::int
  );
CREATE INDEX IF NOT EXISTS <t>_owner_idx ON <t>(owner_id);   -- perf : la policy doit être un index lookup
```

**Cas `Transaction` / `Account` / `ImportLog`** (isolation par *membership*, pas par `owner`) :
policy via sous-requête `account_id IN (SELECT account_id FROM accounts_account_members WHERE user_id = current_user_id)`
→ **plus coûteux** : index sur la table de jonction + bench. **Sous-issue séparée** (risque perf).

**Test** : avec la var positionnée sur user B, `Model.objects.all()` (manager NU, sans for_user)
ne retourne **que** système + B. Une écriture `owner=A` lève une erreur. `unset` → 0 ligne (fail-closed).

---

## Phase 4 — Non-régression + guard CI [~1/2 j]

- `tests/test_rls_isolation.py` : pour CHAQUE modèle Owned, prouver qu'un `objects.all()` *sans*
  `for_user` est filtré par la DB (le cœur du fail-closed). Fixtures pytest posent le contexte RLS.
- Test « méta » : `RLS enabled AND forced` sur toutes les tables Owned (anti-régression schéma).
- CI : intégrer au pipeline (s'appuyer sur #162 semgrep + #199 framework de test).

---

## Phase 5 — Cutover & doc [~1/2 j]

- `for_user` reste pour l'ergonomie/perf des querysets — **plus la barrière de sécu**. Documenter.
- Backfill `owner` manquants (lié [[project_user_deletion_global_cleanup]]).
- SR-014 « isolation fail-closed » dans `SECURITY_RULES.md` ; MAJ `rules/django.md`.

---

## Vérification finale (epic)
- [ ] Chaque modèle Owned : `objects.all()` nu filtré par la DB (test prouvé)
- [ ] `BudgetTarget` per-user sur catégorie système sans collision
- [ ] Pooling Railway OK (`SET LOCAL` en txn, mode session/transaction confirmé)
- [ ] Rôle runtime non-owner + `FORCE RLS` (footgun couvert)
- [ ] `rls_bypass()` couvre seeds / admin / imports / commands
- [ ] 0 `print()`, migrations réversibles (SR-004/005)

## Périmètre
- Epic → **6 issues enfants** (1 phase = 1 issue = 1 branche, anti-stacking). Phase 1 livrable seule.
- Migrations : oui (BudgetTarget + RLS). Fichiers nouveaux : ~4. Risque : pooling Railway, perf policy membership.

## Questions à trancher (Phase 0)
1. **django-rls** (lib) **ou** `RowLevelSecurityConstraint` hand-rolled ? (reco : hand-rolled)
2. Targets sur catégories **système** existantes au backfill : **purge** (pré-launch) ou réassignation ?
3. `Transaction`/`Account` (membership) sous RLS dans cet epic, ou phase ultérieure (perf sous-requête) ?
4. Numéro d'epic GitHub : créer un nouvel epic, ou rattacher à **#168** (déjà « décision scoping BudgetTarget ») / **#148** ?

---

# Phase 0 — ADR (spike & décision) · #204

> Date : 2026-06-24 · Branche : `feature/204-rls-phase0` (PR docs `Part of #204`).
> Statut : **PROPOSÉ** — décision à acter par Emmanuel (1 vérif prod restante, §A.3).
> Cet ADR tranche les 2 inconnues bloquantes de la Phase 0 et **séquence la mise en
> œuvre** : palier ORM fail-closed **maintenant**, RLS **différé** à un déclencheur précis.

## TL;DR — décision

1. **GO sur un palier intermédiaire « couche-2 ORM fail-closed »** (manager par défaut scopé,
   `unscoped()` explicite et grep-able) → **≈90 %** de la fermeture de la classe « oubli de
   scoper » (#118), **0 footgun** pooling/rôle, migrable modèle par modèle, 100 % Python/ORM.
2. **NO-GO immédiat sur RLS Postgres** — mais **pré-validé** (go conditionnel). RLS est **différé**
   jusqu'au **premier consommateur écrivant/lisant des données users hors `request.user`**
   (worker `django.tasks`/Celery, BI/SQL direct, 2ᵉ service). Tant que **tout passe par l'ORM
   d'une requête HTTP**, la couche-2 ORM **est** la barrière fail-closed suffisante.
3. **Quand RLS arrivera** : **hand-rolled `RowLevelSecurityConstraint`** (≈100 lignes, pattern
   Alasco) **plutôt que** `django-rls` — justifié en §B. Pré-requis prod : rôle runtime
   non-owner + `FORCE ROW LEVEL SECURITY` + pooling session-mode ou `SET LOCAL` en transaction.

Conséquence sur le plan : **Phase 1** (`BudgetTarget.owner`, déjà livrée via #201/#206) et une
**nouvelle Phase 1.5 « couche-2 ORM fail-closed »** sont le chemin critique. Les Phases 2–5 (RLS)
restent au plan mais **gelées derrière le déclencheur** ci-dessus, pas au prochain sprint.

---

## A. Recherche Railway — l'app se connecte-t-elle en OWNER des tables ?

### A.1 Ce qui est établi (preuve locale + config)

- **Connexion via un seul `DATABASE_URL`** (`src/config/settings.py:240`), `CONN_MAX_AGE = 60`
  → **connexions persistantes** côté Django (pertinent pour `SET LOCAL` : la var doit être
  re-posée par transaction, jamais `SET SESSION`, sinon elle fuit d'une requête à l'autre sur
  la connexion réutilisée).
- **En local (Docker), le rôle applicatif `bricbudget` est à la fois** : `current_user = session_user
  = bricbudget`, **owner** de `transactions_category`, **`rolsuper = true`, `rolbypassrls = true`**.
  → C'est **exactement** le footgun RLS : un owner **et** un superuser **ignorent silencieusement**
  toute policy même `ENABLE`d. Seul `FORCE ROW LEVEL SECURITY` ré-applique au **owner**, et **rien**
  ne contraint un **superuser** → il faut un **rôle runtime dédié non-superuser, non-owner**.
- **Railway managed Postgres** : par convention, le service injecte un `DATABASE_URL` dont le user
  est le rôle d'admin de l'instance (`postgres`), **propriétaire de toutes les tables créées par les
  migrations** et généralement superuser sur l'instance. **Présomption forte : prod = même footgun
  que local.** À confirmer (A.3).
- **Pas de pooler documenté** (`ops.md` : aucun PgBouncer/PgCat). Railway = **connexion directe** par
  défaut → pas de contrainte `transaction-mode`. Si un pooler est ajouté plus tard, il **devra** être
  en **session mode** (ou `SET LOCAL` strictement en transaction).

### A.2 Impact

→ **RLS sans rôle dédié = inutile** (bypass owner/superuser). Le pré-requis #1 de toute Phase RLS
est donc **infra, pas Django** : provisionner un **2ᵉ rôle Postgres** non-owner/non-superuser/sans
`BYPASSRLS` pour le runtime (migrations gardant le rôle privilégié). C'est un point **dur sur
Railway managed** (création de rôle + 2ᵉ `DATABASE_URL` ou `SET ROLE` post-connexion) — argument
**de plus** pour différer RLS jusqu'au déclencheur réel.

### A.3 À FAIRE par Emmanuel — vérif prod (MCP Railway = non autorisé ici, `railway login` requis)

Se connecter à la base prod (Railway dashboard → service Postgres → « Connect » → `psql`) et lancer :

```sql
-- 1. Sous quel rôle l'app tourne-t-elle ? (et est-ce un superuser ?)
SELECT current_user, session_user;
SELECT rolsuper, rolbypassrls, rolcreaterole
  FROM pg_roles WHERE rolname = current_user;

-- 2. Ce rôle possède-t-il les tables ? (owner => bypass sans FORCE)
SELECT tableowner FROM pg_tables WHERE tablename = 'transactions_category';

-- 3. Liste des rôles (pour savoir si un 2ᵉ rôle non-priv existe déjà)
\du

-- 4. Y a-t-il un pooler en façade ? (Railway = direct par défaut)
SHOW server_version;          -- direct PG, pas un pooler
SELECT current_setting('server_version');
-- si un PgBouncer est ajouté : son admin console `SHOW POOLS;` donne pool_mode.
```

**Interprétation des réponses :**

| Réponse | Conséquence |
|---|---|
| `current_user` = owner des tables (cas attendu) | RLS **ignorée** sans `FORCE ROW LEVEL SECURITY` → `FORCE` obligatoire. |
| `rolsuper = true` **ou** `rolbypassrls = true` (cas attendu) | RLS **totalement bypassée**, même avec `FORCE` → **rôle runtime dédié non-priv OBLIGATOIRE** avant toute policy. |
| `rolsuper = false` ET non-owner | Cas idéal : `ENABLE` suffit, pas besoin de gérer un 2ᵉ rôle. (Peu probable sur Railway managed.) |
| pooler en `transaction`/`statement` mode | `SET LOCAL` cassé → forcer `session` mode ou abandonner `SET LOCAL` pour un GUC par-connexion. |
| pas de pooler (cas attendu) | `SET LOCAL` en transaction = OK, rien à changer côté pooling. |

**Cette unique vérif est le seul résidu « prod » de la Phase 0.** Elle ne bloque PAS la couche-2
ORM (qui n'en dépend pas) ; elle conditionne uniquement le coût d'infra de la future Phase RLS.

---

## B. Décision technique — couche-2 ORM d'abord, RLS différé

### B.1 Les 3 options évaluées

| Option | Bénéfice | Coût / risque | Verdict |
|---|---|---|---|
| **Couche-2 ORM fail-closed** (manager défaut scopé + `unscoped()`) | ferme ≈90 % de #118, Python pur, par-modèle, testable trivialement, **0 dépendance prod** | ne couvre PAS le raw SQL / hors-ORM / reverse-FK non scopée | ✅ **MAINTENANT** |
| **Hand-rolled `RowLevelSecurityConstraint`** (RLS, pattern Alasco) | fail-closed **DB** (couvre raw SQL, migrations, reverse-FK, 2ᵉ service) ; ≈100 lignes ; **0 lock-in** ; on maîtrise le SQL des policies (cas `owner NULL` système + `BYPASS`) | exige rôle runtime non-priv + `FORCE` + discipline pooling ; coût M2M `members` (sous-requête) | ⏳ **DIFFÉRÉ** (1er conso hors-ORM) |
| **`django-rls` / `django-rls-tenants`** (lib) | policies déclaratives en `Meta`, middleware GUC fourni | **suppose un `tenant_id` UNIQUE** par ligne → **ne couvre PAS** `Account.members` (M2M) ni le cas `owner NULL` (catégories système lisibles par tous) ; lib jeune (lock-in, Django 6 à valider) | ❌ **écartée** |

### B.2 Pourquoi la couche-2 ORM d'abord (justification)

- **ROI maximal, risque minimal.** Aujourd'hui 100 % des accès aux données users passent par
  l'ORM dans une requête HTTP scopée par `request.user`. La classe d'incident #118 = **un
  `for_user` oublié** sur l'un des 149 sites (fail-OPEN). Un **manager par défaut déjà scopé**
  transforme l'oubli en **0 ligne** (fail-CLOSED) sans rien changer à l'infra.
- **`for_user` reste à vie** (acté par l'audit) : c'est le pattern Django standard, pas un
  workaround ; RLS le *renforce*, ne le remplace pas. La couche-2 ne fait que **changer le défaut**
  du manager : `Model.objects` → déjà scopé ; l'accès global devient **explicite et grep-able**.
- **0 footgun.** Pas de rôle Postgres à provisionner, pas de `SET LOCAL`/pooling, pas de
  `FORCE RLS`, pas de risque « policy bypassée par owner ». Migrable **un modèle à la fois**.
- **RLS = sur-ingénierie tant que rien ne sort de l'ORM.** RLS protège contre le **raw SQL, les
  migrations, un worker async, un 2ᵉ service, le BI direct**. Aucun de ces consommateurs n'existe
  aujourd'hui. Django 6.0 embarque `django.tasks` **mais sans worker/scheduler prod** → pas encore
  de chemin d'écriture hors-requête. **Le jour où l'un d'eux lit/écrit des données users sans
  `request.user`, `for_user` ET la couche-2 ORM sont inopérants → RLS devient la seule barrière.**
  **C'est LE déclencheur** documenté de la Phase 2+.

### B.3 DESIGN de la couche-2 ORM (prêt à coder, palier 2 / « Phase 1.5 »)

> Aucune ligne écrite ici (Phase 0 = doc). Ceci spécifie l'archi à valider AVANT de coder.

**Où vivent les managers.** Un module partagé **`src/transactions/managers.py`** (ou
`src/<app>/managers.py` par app si on préfère la colocation modèle↔manager) exposant un
`OwnedQuerySet` / `OwnedManager` réutilisable. On **étend l'existant** `for_user` (déjà sur les
modèles Owned) plutôt que de réinventer.

**Principe — défaut fail-closed, global explicite :**

```python
# managers.py  (DESIGN — non implémenté)
class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        # garde le contrat actuel : système (owner NULL) + perso de `user`
        return self.filter(models.Q(owner__isnull=True) | models.Q(owner=user))

class OwnedManager(models.Manager):
    """Manager PAR DÉFAUT fail-closed : exige un user, sinon 0 ligne.

    Le défaut `Model.objects.all()` NE renvoie PLUS tout : il EXIGE un scope.
    L'accès global légitime (seeds, admin, commands, agrégats cross-user) passe
    par `unscoped()` — explicite, grep-able, audité.
    """
    def get_queryset(self):
        # fail-closed : sans contexte user, on ne révèle rien.
        return OwnedQuerySet(self.model, using=self._db).none()

    def for_user(self, user):
        return OwnedQuerySet(self.model, using=self._db).for_user(user)

    def unscoped(self):
        # SEUL point d'accès global — un grep `unscoped(` liste tous les bypass.
        return OwnedQuerySet(self.model, using=self._db)
```

**Comment `unscoped()`** : un **unique** point d'entrée nommé, **grep-able** (`grep -rn
"unscoped(" src/` = liste exhaustive et auditable des accès cross-user, comme `# noqa` pour la
sécu). Utilisé par : seeds/`sync_reference_data`, `import_service._load_rules` (#205), admin
Django, commandes CLI, agrégats cross-user légitimes. **Toute occurrence est revue** ; c'est
l'inverse du fail-open actuel (où l'oubli est invisible).

**M2M `Account.members` (Transaction/Account/ImportLog) — plus tard, en sous-requête.** Ces modèles
ne s'isolent pas par `owner` mais par **appartenance** (`members` M2M). Le `OwnedManager` ci-dessus
ne s'y applique pas tel quel. Pour eux, le manager fail-closed filtrera via la **jonction** :
`Account.objects.filter(is_active=True, members=user)` puis `Transaction.objects.filter(account__in=…)`.
C'est **plus coûteux** (jointure/sous-requête sur la table de jonction `accounts_account_members`) et
c'est **le même point dur** que la future policy RLS membership → on le traite **après** les modèles
`owner` simples (Category, SubCategory, CategorizationRule, BudgetTarget), pas dans le même incrément.

**Migration progressive (anti-régression).** Modèle par modèle : (1) basculer `objects` sur
`OwnedManager`, (2) faire tourner la suite de tests — tout `objects.all()` nu non migré vers
`for_user`/`unscoped` **casse en test** (révèle les oublis), (3) corriger site par site. Un **test
méta** (Phase 4) vérifie que chaque modèle Owned a bien un manager fail-closed par défaut.

**Garde anti-régression CI.** Une règle semgrep (s'appuyer sur #162) interdit le pattern
`.objects.all()` / `.objects.filter()` **sans** `for_user`/`unscoped` sur les modèles Owned — la
couche-2 rend l'oubli détectable statiquement **en plus** de fail-closed à l'exécution.

### B.4 Go/No-Go — synthèse décisionnelle

- **GO couche-2 ORM** (palier « Phase 1.5 ») — **prêt à coder**, design ci-dessus, 0 dépendance prod.
  ⚠️ Tâche **porteuse d'archi** (manager transverse) → **gate Emmanuel sur ce design AVANT code.**
- **GO conditionnel RLS** (Phases 2–5) — **architecture validée** (hand-rolled, `FORCE`, rôle dédié),
  **déclenchée** par le 1er consommateur hors-ORM, **et** après la vérif prod §A.3 (rôle/owner/pooling).
- **NO-GO `django-rls`** — incompatible M2M `members` + cas `owner NULL`, lib jeune.

---

## C. Ce qu'il reste à décider / vérifier (sortie Phase 0)

1. **[Emmanuel — prod]** Lancer les requêtes §A.3 sur la base Railway → confirmer owner + superuser +
   absence de pooler. Reporter le résultat dans `ops.md`. **Seul résidu prod de la Phase 0.**
2. **[Gate archi]** Valider le design couche-2 §B.3 (emplacement managers, sémantique `unscoped()`,
   ordre owner-d'abord puis membership) **avant** d'ouvrir la branche d'implémentation.
3. **[Roadmap]** Acter que les Phases 2–5 (RLS) sont **gelées derrière le déclencheur** (1er conso
   hors-ORM) et non planifiées au prochain sprint ; créer l'issue enfant « couche-2 ORM fail-closed »
   (Phase 1.5) comme prochain livrable de l'epic #204.
