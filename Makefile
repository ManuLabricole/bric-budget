# =============================================================================
# 💰 BricBudget — Makefile
# =============================================================================

SHELL := /bin/bash
MANAGE := poetry run python src/manage.py

# Port du serveur Django. Surchargeable pour les worktrees parallèles : make run PORT=8150
PORT ?= 8000

# --- Couleurs ANSI (via printf, car echo macOS n'interprète pas \033) ---
RESET  := \033[0m
BOLD   := \033[1m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m
RED    := \033[31m
DIM    := \033[2m

# =============================================================================
# 📋 help — liste toutes les commandes disponibles (cible par défaut)
# =============================================================================
.DEFAULT_GOAL := help

help:
	@printf "\n"
	@printf "  $(BOLD)💰 BricBudget$(RESET) — commandes disponibles\n"
	@printf "\n"
	@printf "  $(CYAN)🐘 Base de données$(RESET)\n"
	@printf "    $(BOLD)make up$(RESET)              Démarre PostgreSQL (Docker)\n"
	@printf "    $(BOLD)make down$(RESET)            Arrête PostgreSQL (Docker)\n"
	@printf "    $(BOLD)make logs$(RESET)            Logs du container PostgreSQL en live\n"
	@printf "\n"
	@printf "  $(CYAN)🐍 Django$(RESET)\n"
	@printf "    $(BOLD)make run$(RESET)             Lance le serveur Django (démarre Docker si besoin)\n"
	@printf "    $(BOLD)make migrate$(RESET)         Applique les migrations en base\n"
	@printf "    $(BOLD)make makemigrations$(RESET)  Génère de nouvelles migrations\n"
	@printf "    $(BOLD)make shell$(RESET)           Ouvre le shell Django interactif\n"
	@printf "\n"
	@printf "  $(CYAN)📡 Status$(RESET)\n"
	@printf "    $(BOLD)make status$(RESET)          Affiche l'état des services et les ports\n"
	@printf "\n"
	@printf "  $(CYAN)📥 Import CSV$(RESET)\n"
	@printf "    $(BOLD)make import-all$(RESET)      Importe tous les fichiers du dossier raw (dry run)\n"
	@printf "    $(BOLD)make import-all COMMIT=1$(RESET)  Importe tous les fichiers (écriture DB)\n"
	@printf "    $(BOLD)make import-yuh$(RESET)      Analyse un export Yuh CSV (dry run)\n"
	@printf "    $(BOLD)make import-ubs$(RESET)      Analyse un export UBS CSV (dry run)\n"
	@printf "    $(BOLD)make import-cic$(RESET)      Analyse un export CIC Excel (dry run)\n"
	@printf "\n"
	@printf "  $(CYAN)🧪 Qualité$(RESET)\n"
	@printf "    $(BOLD)make lint$(RESET)            Lint Python (ruff) + templates (djlint)\n"
	@printf "    $(BOLD)make type$(RESET)            Vérification de types (mypy)\n"
	@printf "    $(BOLD)make check$(RESET)           Lint + type + tests (tout en un)\n"
	@printf "    $(BOLD)make test$(RESET)            Tests unitaires uniquement\n"
	@printf "    $(BOLD)make audit-sg$(RESET)        Audit structurel SR-XX (ast-grep, heuristique)\n"
	@printf "\n"
	@printf "  $(CYAN)🧪 Dev tools$(RESET)\n"
	@printf "    $(BOLD)make demo-seed$(RESET)       Seed démo : 6 comptes via imports réels (flush)\n"
	@printf "    $(BOLD)make demo-reset$(RESET)      Reset des données démo (garde l'utilisateur)\n"
	@printf "    $(DIM)→ ou via l'admin : /admin/demo/$(RESET)\n"
	@printf "\n"

# =============================================================================
# 📡 status — état de tous les services
# =============================================================================
status:
	@printf "\n"
	@printf "  $(BOLD)📡 BricBudget — état des services$(RESET)\n"
	@printf "  $(DIM)─────────────────────────────────────────$(RESET)\n"
	@DB_STATUS=$$(docker inspect -f '{{.State.Health.Status}}' bricbudget-db 2>/dev/null); \
	if [ "$$DB_STATUS" = "healthy" ]; then \
		printf "  🐘 $(GREEN)$(BOLD)PostgreSQL$(RESET)   healthy   $(DIM)localhost:5433$(RESET)\n"; \
	elif [ "$$DB_STATUS" = "starting" ]; then \
		printf "  🐘 $(YELLOW)$(BOLD)PostgreSQL$(RESET)   starting  $(DIM)localhost:5433$(RESET)\n"; \
	else \
		printf "  🐘 $(RED)$(BOLD)PostgreSQL$(RESET)   stopped   $(DIM)localhost:5433$(RESET)\n"; \
	fi
	@if lsof -i :8000 -sTCP:LISTEN -t > /dev/null 2>&1; then \
		printf "  🐍 $(GREEN)$(BOLD)Django$(RESET)       running   $(DIM)http://localhost:8000$(RESET)\n"; \
	else \
		printf "  🐍 $(RED)$(BOLD)Django$(RESET)       stopped   $(DIM)http://localhost:8000$(RESET)\n"; \
	fi
	@printf "  $(DIM)─────────────────────────────────────────$(RESET)\n"
	@printf "\n"

# =============================================================================
# 🐘 Docker — PostgreSQL
# =============================================================================

up:
	@printf "  🐘 $(CYAN)Démarrage PostgreSQL...$(RESET)\n"
	@docker compose up -d
	@printf "  $(DIM)→ port 5433 (Mac) → 5432 (container)$(RESET)\n"
	@printf "  ✅ $(GREEN)PostgreSQL démarré$(RESET)\n"

down:
	@printf "  🐘 $(YELLOW)Arrêt PostgreSQL...$(RESET)\n"
	@docker compose down
	@printf "  ✅ $(GREEN)PostgreSQL arrêté$(RESET)\n"

logs:
	@printf "  🐘 $(CYAN)Logs PostgreSQL (Ctrl+C pour quitter)$(RESET)\n\n"
	@docker compose logs -f db

# =============================================================================
# 🐍 Django
# =============================================================================

run:
	@if [ "$$(docker inspect -f '{{.State.Health.Status}}' bricbudget-db 2>/dev/null)" != "healthy" ]; then \
		printf "  🐘 $(CYAN)Démarrage PostgreSQL...$(RESET)\n"; \
		docker compose up -d; \
		printf "  $(DIM)→ attente que PostgreSQL soit prêt...$(RESET)\n"; \
		until [ "$$(docker inspect -f '{{.State.Health.Status}}' bricbudget-db 2>/dev/null)" = "healthy" ]; do sleep 1; done; \
		printf "  ✅ $(GREEN)PostgreSQL prêt$(RESET)\n"; \
	fi
	@printf "\n"
	@printf "  🐍 $(CYAN)Démarrage Django...$(RESET)\n"
	@printf "  $(DIM)─────────────────────────────────────────$(RESET)\n"
	@printf "  🐘 PostgreSQL   $(DIM)localhost:5433$(RESET)\n"
	@printf "  🌐 Django       $(DIM)http://localhost:$(PORT)$(RESET)\n"
	@printf "  🔐 Admin        $(DIM)http://localhost:$(PORT)/admin$(RESET)\n"
	@printf "  $(DIM)─────────────────────────────────────────$(RESET)\n\n"
	@$(MANAGE) runserver 0.0.0.0:$(PORT)

test:
	@printf "  🧪 $(CYAN)Lancement des tests...$(RESET)\n"
	@poetry run pytest --color=yes
	@printf "  ✅ $(GREEN)Tests terminés$(RESET)\n"

coverage:
	@printf "  📊 $(CYAN)Coverage report...$(RESET)\n"
	@cd src && poetry run pytest --cov=. --cov-report=term-missing -q --tb=no
	@printf "  ✅ $(GREEN)Coverage terminé$(RESET)\n"

lint:
	@printf "  🔍 $(CYAN)Linting Python (ruff) + templates (djlint)...$(RESET)\n"
	@poetry run ruff check src/
	@poetry run djlint src/templates/ --profile=django --lint
	@printf "  ✅ $(GREEN)Lint OK$(RESET)\n"

type:
	@printf "  🔎 $(CYAN)Vérification de types (mypy)...$(RESET)\n"
	@cd src && poetry run mypy . --config-file ../pyproject.toml
	@printf "  ✅ $(GREEN)Types OK$(RESET)\n"

check:
	@printf "  🔍 $(CYAN)Lint + types + tests...$(RESET)\n"
	@poetry run ruff check src/
	@poetry run djlint src/templates/ --profile=django --lint
	@cd src && poetry run mypy . --config-file ../pyproject.toml
	@poetry run pytest --color=yes
	@printf "  ✅ $(GREEN)Tout est bon$(RESET)\n"

# =============================================================================
# 🔎 audit-sg — recherche structurelle SR-XX (ast-grep, tree-sitter)
#   Heuristique d'audit (faux positifs possibles), PAS un gate CI.
#   Pré-requis : brew install ast-grep — cf. .claude/agent-codenav.md
# =============================================================================
audit-sg:
	@printf "  🔎 $(CYAN)Audit structurel SR-XX (ast-grep)...$(RESET)\n"
	@command -v ast-grep >/dev/null 2>&1 || { printf "  ❌ $(RED)ast-grep absent$(RESET) — brew install ast-grep\n"; exit 1; }
	@ast-grep scan || true
	@printf "  $(DIM)→ heuristique : juger chaque hit à la lecture (cf. .claude/agent-codenav.md)$(RESET)\n"

migrate:
	@printf "  🔄 $(CYAN)Application des migrations...$(RESET)\n"
	@$(MANAGE) migrate
	@printf "  ✅ $(GREEN)Migrations appliquées$(RESET)\n"

makemigrations:
	@printf "  ✏️  $(CYAN)Génération des migrations...$(RESET)\n"
	@$(MANAGE) makemigrations
	@printf "  ✅ $(GREEN)Migrations générées$(RESET)\n"

shell:
	@printf "  🐚 $(CYAN)Ouverture du shell Django...$(RESET)\n\n"
	@$(MANAGE) shell

create-superuser:
	@printf "  👤 $(CYAN)Création du superuser depuis .env...$(RESET)\n"
	@$(MANAGE) create_user --superuser
	@printf "  $(DIM)→ connecte-toi sur http://localhost:8000/admin$(RESET)\n"

seed:
	@printf "  🌱 $(CYAN)Seed des référentiels (catégories + institutions)...$(RESET)\n"
	@$(MANAGE) seed_initial
	@printf "  $(DIM)→ comptes perso : make setup-accounts (ou python manage.py setup_accounts)$(RESET)\n"

import-all:
	@printf "  📥 $(CYAN)Import all raw files$(if $(COMMIT), — écriture DB,  — dry run)...$(RESET)\n"
	@$(MANAGE) import_all --dir assets/private/data/raw $(if $(COMMIT),--commit,)

import-yuh:
	@if [ -z "$(FILE)" ]; then printf "  ❌ $(RED)Usage: make import-yuh FILE=path/to/export.csv [COMMIT=1]$(RESET)\n"; exit 1; fi
	@printf "  📥 $(CYAN)Import Yuh$(if $(COMMIT), — écriture DB,  — dry run)...$(RESET)\n"
	@$(MANAGE) import_yuh --file "$(FILE)" $(if $(COMMIT),--commit,)

import-ubs:
	@if [ -z "$(FILE)" ]; then printf "  ❌ $(RED)Usage: make import-ubs FILE=path/to/export.csv [COMMIT=1]$(RESET)\n"; exit 1; fi
	@printf "  📥 $(CYAN)Import UBS$(if $(COMMIT), — écriture DB,  — dry run)...$(RESET)\n"
	@$(MANAGE) import_ubs --file "$(FILE)" $(if $(COMMIT),--commit,)

import-cic:
	@if [ -z "$(FILE)" ]; then printf "  ❌ $(RED)Usage: make import-cic FILE=path/to/export.xlsx [COMMIT=1]$(RESET)\n"; exit 1; fi
	@printf "  📥 $(CYAN)Import CIC$(if $(COMMIT), — écriture DB,  — dry run)...$(RESET)\n"
	@$(MANAGE) import_cic --file "$(FILE)" $(if $(COMMIT),--commit,)

recalculate-display-names:
	@printf "  🧹 $(CYAN)Recalcul display_name pour toutes les transactions...$(RESET)\n"
	@$(MANAGE) recalculate_display_names

apply-rules:
	@printf "  ⚡ $(CYAN)Application des règles de catégorisation...$(RESET)\n"
	@$(MANAGE) apply_rules $(if $(DRY),--dry-run,) $(if $(RESET),--reset,)

export-rules:
	@printf "  📤 $(CYAN)Export règles de catégorisation → JSON...$(RESET)\n"
	@mkdir -p assets/private
	@$(MANAGE) export_rules --output assets/private/rules_backup_$(shell date +%Y%m%d).json

# =============================================================================
# 🧪 Dev tools — données de démo (app demo/, voir aussi /admin/demo/)
# =============================================================================

demo-seed:
	@printf "  🌱 $(YELLOW)DEV — Seed démo : 6 comptes via imports réels...$(RESET)\n"
	@$(MANAGE) dev_seed --flush $(if $(MONTHS),--months=$(MONTHS),)
	@printf "  ✅ $(GREEN)Fait — recharge /budget/ ou /patrimoine/ pour voir les données$(RESET)\n"

demo-reset:
	@printf "  🗑️  $(RED)DEV — Reset des données démo (garde l'utilisateur)...$(RESET)\n"
	@$(MANAGE) dev_reset --yes
	@printf "  $(DIM)→ relance make demo-seed pour repeupler$(RESET)\n"

backfill-logos:
	@printf "  🏦 $(YELLOW)Téléchargement des logos institutions manquants (Google Favicons)...$(RESET)\n"
	@$(MANAGE) backfill_logos $(if $(BANK),--institution=$(BANK),) $(if $(FORCE),--force,)
	@printf "  ✅ $(GREEN)Logos mis à jour dans static/icons/banks/miniature/$(RESET)\n"

# =============================================================================
# 💾 Sauvegarde / Restauration PostgreSQL
# =============================================================================
# pg_dump : outil standard PostgreSQL qui exporte toute la DB en SQL
# On l'exécute DANS le container Docker (docker exec) car pg_dump doit être
# sur la même machine que PostgreSQL. Le fichier résultant est copié sur le Mac.

BACKUP_DIR := backups
BACKUP_FILE := $(BACKUP_DIR)/bricbudget_$(shell date +%Y%m%d_%H%M%S).sql

backup:
	@mkdir -p $(BACKUP_DIR)
	@printf "  💾 $(CYAN)Sauvegarde PostgreSQL...$(RESET)\n"
	@docker exec bricbudget-db pg_dump \
		--username=$(shell grep DB_USER .env | cut -d= -f2) \
		--dbname=$(shell grep DB_NAME .env | cut -d= -f2) \
		--clean \
		--if-exists \
		> $(BACKUP_FILE)
	@printf "  ✅ $(GREEN)Sauvegarde créée :$(RESET) $(BACKUP_FILE)\n"

# Usage : make restore FILE=backups/bricbudget_20260405_103000.sql[.gz]
# Gère les .sql ET les .sql.gz (les dumps prod sont gzippés) → décompression à la volée.
restore:
	@if [ -z "$(FILE)" ]; then \
		printf "  ❌ $(RED)Précise le fichier : make restore FILE=backups/nom_du_fichier.sql[.gz]$(RESET)\n"; \
		exit 1; \
	fi
	@printf "  ⚠️  $(YELLOW)Restauration depuis $(FILE)... (la DB actuelle sera écrasée)$(RESET)\n"
	@case "$(FILE)" in \
		*.gz) gunzip -c "$(FILE)" ;; \
		*)    cat "$(FILE)" ;; \
	esac | docker exec -i bricbudget-db psql \
		--username=$(shell grep DB_USER .env | cut -d= -f2) \
		--dbname=$(shell grep DB_NAME .env | cut -d= -f2)
	@printf "  ✅ $(GREEN)Restauration terminée$(RESET)\n"

# Dump de la PROD (Railway) — #257. Le script DEMANDE l'URL en saisie masquée si
# PROD_DATABASE_URL n'est pas déjà dans l'env → le secret ne passe pas par la ligne
# de commande / l'historique shell. Récupérer l'URL : Railway → Postgres → Connect.
prod-backup:
	@bash scripts/db_prod_backup.sh

# =============================================================================
.PHONY: help status up down logs run migrate makemigrations shell create-superuser seed import-all import-yuh import-ubs import-cic backup restore prod-backup demo-seed demo-reset lint type check test coverage audit-sg
