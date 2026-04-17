# =============================================================================
# 💰 BricBudget — Makefile
# =============================================================================

SHELL := /bin/bash
MANAGE := poetry run python src/manage.py

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
	@printf "    $(BOLD)make import-yuh$(RESET)      Analyse un export Yuh CSV (dry run)\n"
	@printf "    $(BOLD)make import-ubs$(RESET)      Analyse un export UBS CSV (dry run)\n"
	@printf "    $(BOLD)make import-cic$(RESET)      Analyse un export CIC Excel (dry run)\n"
	@printf "\n"
	@printf "  $(CYAN)🧪 Dev tools$(RESET)\n"
	@printf "    $(BOLD)make dev-randomize$(RESET)   Catégorisation aléatoire (transactions non catégorisées)\n"
	@printf "    $(BOLD)make dev-randomize ALL=1$(RESET)  Re-randomiser toutes les transactions\n"
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
	@printf "  🌐 Django       $(DIM)http://localhost:8000$(RESET)\n"
	@printf "  🔐 Admin        $(DIM)http://localhost:8000/admin$(RESET)\n"
	@printf "  $(DIM)─────────────────────────────────────────$(RESET)\n\n"
	@$(MANAGE) runserver

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
	@printf "  🌱 $(CYAN)Seed des données initiales...$(RESET)\n"
	@$(MANAGE) seed_initial
	@printf "  $(DIM)→ banques, comptes, cartes, catégories créés$(RESET)\n"

reset-seed:
	@printf "  🗑️  $(RED)Suppression des données seedées...$(RESET)\n"
	@$(MANAGE) reset_seed --yes
	@printf "  $(DIM)→ relance make seed pour repeupler$(RESET)\n"

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

# =============================================================================
# 🧪 Dev tools
# =============================================================================

dev-randomize:
	@printf "  🎲 $(YELLOW)DEV — Catégorisation aléatoire des transactions...$(RESET)\n"
	@printf "  $(DIM)→ income → Revenus/Remboursements | dépenses → toutes les autres$(RESET)\n"
	@$(MANAGE) dev_randomize_categories $(if $(ALL),--all,)
	@printf "  ✅ $(GREEN)Fait — recharge /budget/ pour voir les données$(RESET)\n"

update-bank-logos:
	@printf "  🏦 $(YELLOW)Téléchargement des logos banques (Google Favicons)...$(RESET)\n"
	@$(MANAGE) update_bank_logos $(if $(BANK),--bank=$(BANK),)
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

# Usage : make restore FILE=backups/bricbudget_20260405_103000.sql
restore:
	@if [ -z "$(FILE)" ]; then \
		printf "  ❌ $(RED)Précise le fichier : make restore FILE=backups/nom_du_fichier.sql$(RESET)\n"; \
		exit 1; \
	fi
	@printf "  ⚠️  $(YELLOW)Restauration depuis $(FILE)... (la DB actuelle sera écrasée)$(RESET)\n"
	@docker exec -i bricbudget-db psql \
		--username=$(shell grep DB_USER .env | cut -d= -f2) \
		--dbname=$(shell grep DB_NAME .env | cut -d= -f2) \
		< $(FILE)
	@printf "  ✅ $(GREEN)Restauration terminée$(RESET)\n"

# =============================================================================
.PHONY: help status up down logs run migrate makemigrations shell create-superuser seed reset-seed import-yuh import-ubs import-cic backup restore dev-randomize
