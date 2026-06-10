"""
services/ — micro-services transverses (package unique, hors apps Django).

Convention : UN module par service, pas un dossier par service. Les services
ici sont réutilisables par plusieurs apps, framework-light, testés isolément
(même esprit que connectors/ pour les parsers bancaires).

    logos.py — récupération de logos (Institution, futur Merchant #124)

Un service spécifique à UNE app reste dans l'app (ex. patrimoine/services/).
"""
