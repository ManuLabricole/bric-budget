# Procfile — commandes de démarrage pour Railway (et Heroku-compatible)
#
# Format : <type>: <commande>
#
# "web" est le seul type exposé sur internet par Railway.
# Railway lit cette ligne, injecte $PORT, et lance la commande.
#
# Décomposition de la commande :
#
#   poetry run
#     → active le virtualenv Poetry avant de lancer gunicorn
#     → garantit qu'on utilise les bonnes versions de packages
#
#   gunicorn src.config.wsgi
#     → src.config.wsgi = chemin Python vers src/config/wsgi.py
#     → c'est le fichier que Django a généré automatiquement
#     → il contient l'objet "application" que Gunicorn appelle pour chaque requête
#
#   --workers 3
#     → 3 processus Python en parallèle (règle : 2 × CPU + 1, Railway = 1 CPU)
#     → chaque worker traite une requête à la fois
#     → 3 workers = 3 requêtes simultanées sans attente
#
#   --bind 0.0.0.0:$PORT
#     → 0.0.0.0 = écouter sur toutes les interfaces réseau (obligatoire en container)
#     → $PORT = Railway injecte automatiquement le bon port (souvent 8080)
#     → Railway fait suivre le trafic HTTPS externe vers ce port interne
#
#   --timeout 30
#     → si une vue met plus de 30s à répondre, Gunicorn tue le worker
#     → protège contre les vues qui bloquent (boucle infinie, requête SQL lente)
#     → le worker est automatiquement redémarré après
#
#   --access-logfile -
#     → redirige les logs d'accès vers stdout (visible dans Railway Logs)
#     → format : IP - - [date] "GET /budget/ HTTP/1.1" 200 1234
#     → sans ça, les logs sont perdus dans le container
#
# Note sur les migrations :
#   On ne lance PAS migrate ici (le lancer au démarrage de chaque worker serait
#   dangereux en multi-workers). Les migrations + le seed des référentiels tournent
#   en pre-deploy, une seule fois, AVANT le start : voir railway.json
#   (deploy.preDeployCommand = migrate && sync_reference_data, #135).

# On lance Gunicorn depuis src/ pour que Python trouve le module "config.wsgi".
# Sans le "cd src &&", Python cherche "src.config.wsgi" depuis la racine et échoue
# avec "No module named 'config'" car src/ n'est pas dans PYTHONPATH par défaut.
web: cd src && poetry run gunicorn config.wsgi --workers 3 --bind 0.0.0.0:$PORT --timeout 30 --access-logfile -
