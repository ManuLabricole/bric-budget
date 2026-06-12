---
paths:
  - "src/**/*.py"
---

# Django — conventions BricBudget (chargé sur le code Python)

> Conventions courtes et **obligatoires** (chargées par chemin, toujours présentes sur le code Python).
> Détail/exemples → skill `security` (SR-XX, OWASP, LLM) + `.claude/SECURITY_RULES.md` (source de vérité).

## Sécurité (non négociable — SR-XX)
- **IDOR (SR-001)** : accès toujours scopé utilisateur — `Transaction.objects.for_user(request.user)`,
  `Account.objects.filter(is_active=True, members=request.user)`,
  `ImportLog.objects.filter(file_hash=h, account__members=request.user)`. Jamais `.all()` / `.get(pk=)` nu.
- **Argent (SR-002)** : `Decimal(str(x))`, JAMAIS `Decimal(float)`.
- **Écritures multiples (SR-003)** : `with transaction.atomic():`.
- **Logs (SR-005)** : `logger.{debug,info,exception}`, jamais `print()`.
- **Données bancaires (SR-008)** : `config()` + `.env`, jamais d'IBAN/RIB/contrat en dur.

## POST & validation — PAS de Django Forms en front
- Les vues parsent les POST à la main (`request.POST.get(...)`) ; pas de `Form`/`ModelForm` hors admin.
- Donc **valide, caste et borne chaque champ dans la vue** (type, longueur, valeurs autorisées) :
  il n'y a pas de `clean()` centralisé pour rattraper un oubli.

## Vues & HTMX
- HTMX détecté via `request.headers.get("HX-Request")` (**header brut**, pas `request.htmx`).
  Réponse HTMX = partial `_xxx.html`, jamais la page complète.
- N+1 : `select_related` (FK) / `prefetch_related` (M2M, reverse FK) dès qu'on accède aux relations.
- `.exists()` / `.count()` plutôt que `if qs:` / `len(qs)`.
- Pattern PRG : POST/HTMX → maj **session** → redirect/re-render en GET (état UI en session, pas d'URL params).

## Constantes & référentiels (acté 2026-06-12, #126 — best practice Two Scoops)
- Constantes/data d'app → **dans l'app propriétaire** (`<app>/constants.py`, `<app>/reference/*.json`),
  comme les `fixtures/` natives Django. ⛔ Pas de package data racine, pas de data métier dans
  `config/` (= settings de déploiement uniquement). Racine réservée à l'infra transverse (`services/`).
- Référentiel = données **committées** app-locales + seed **idempotent** (`update_or_create`)
  + enregistré dans `sync_reference_data` (release deploy). Échec de seed = `CommandError` (exit ≠ 0),
  jamais de return silencieux. Pas de `loaddata`/fixtures ni de data migrations pour les catalogues vivants.
- SR-008 garanti par test : `tests/test_reference_data.py` scanne tous les `*/reference/` +
  `institutions_config.py` (aucun IBAN/contrat/donnée perso).

## Structure & style
- Un module qui grossit → **package** (`views/` package + `__init__.py`, pas de `views_xxx.py` à plat).
- Type hints (mypy passe, `make type`), pas de `Any` gratuit.
- Commenter le **POURQUOI**, pas le QUOI. Pas de sur-abstraction — ROI d'abord.

## Pièges
- **Dates** : `DateTimeField` est stocké en UTC (`USE_TZ=True`). Toujours `timezone.localtime(dt).strftime(...)` — `dt.strftime()` direct donne l'UTC (bug silencieux la nuit en UTC+N). Tests : `timezone.now()`, jamais `datetime.now()` naïf.
