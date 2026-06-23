# demo/fixtures/ — relevés bancaires synthétiques (#118)

Exports bancaires **synthétiques** (0 donnée réelle), au format exact de chaque
banque, **committés** et versionnés. Ils servent à `manage.py dev_seed --from-fixtures`
(import reproductible, hors-ligne) et pourront être déposés sur le bucket Railway.

## Contenu
- `ubs/ubs_checking_demo.csv` — compte courant UBS (salaire, charges, virement épargne)
- `ubs/ubs_savings_demo.csv`  — livret UBS (virement mensuel entrant)
- `yuh/yuh_demo.csv`          — carte Yuh (dépenses du quotidien)

## Sécurité (SR-008)
Identifiants **synthétiques uniquement** : IBAN tout-zéro (`CH00 0000 0000 0000 0000 0`
et `…1`), carte `**** 1150`. Garde-fou : `tests/demo/test_fixtures.py` échoue si un
identifiant hors liste blanche apparaît. (Le hook anti-IBAN ne scanne que les `.py`,
mais on ne se repose pas dessus.)

## Régénérer (ne pas éditer à la main)
```
python manage.py dev_generate_fixtures
```
Anchor **fixe** (2026-06-01) → fichiers stables, pas de churn git. Pour changer les
données : modifier `demo/profiles.py` puis régénérer.
