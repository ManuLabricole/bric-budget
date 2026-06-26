"""
transactions/management/commands/dump_db_to_s3.py — Sauvegarde DB → bucket S3 (#257).

Commande de DÉPLOIEMENT / OPS (voisine de sync_reference_data, autre command de
deploy) : `pg_dump` → gzip → bucket Railway (clé `db-backups/prod_<ts>.sql.gz`),
puis purge des dumps plus vieux que la rétention.

Déclenchée :
  - en PRE-DEPLOY (railway.json), APRÈS migrate + sync_reference_data → le backup
    capture l'état POST-migration (cohérent avec le code déployé), et surtout il ne
    GATE pas la migration : un échec de dump ne bloque pas l'application des
    migrations (l'inverse — `dump && migrate` — empêchait toute migration tant que
    le dump ratait, fatal pour la 1ʳᵉ migration d'un service vierge) ;
  - par un CRON nightly (service Railway dédié, schedule `0 3 * * *`) = la vraie
    régularité des sauvegardes, découplée du déploiement.

Réutilise l'existant : DATABASE_URL + les vars bucket AWS_BACKUP_* (sinon fallback
AWS_* du storage MEDIA). pg_dump doit être présent dans le conteneur → fourni par le
`Dockerfile` (postgresql-client-18). Aucun secret en clair : mot de passe via
PGPASSWORD (env), jamais dans argv.
"""

from __future__ import annotations

import gzip
import logging
import os
import subprocess
import tempfile
from datetime import timedelta
from urllib.parse import unquote, urlparse

import boto3
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "db-backups/"


class Command(BaseCommand):
    help = "Sauvegarde la DB (pg_dump) dans le bucket S3 + purge des dumps anciens."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument(  # type: ignore[attr-defined]
            "--retention-days",
            type=int,
            default=int(os.environ.get("DB_BACKUP_RETENTION_DAYS", "14")),
            help="Supprime les dumps S3 plus vieux que N jours (défaut 14).",
        )

    def handle(self, *args: object, **options: object) -> None:
        bucket = _backup_setting("AWS_BACKUP_BUCKET_NAME", "AWS_S3_BUCKET_NAME")
        if not bucket:
            raise CommandError(
                "Aucun bucket S3 — définis AWS_BACKUP_BUCKET_NAME (bucket dédié) "
                "ou, à défaut, AWS_S3_BUCKET_NAME. Backup impossible."
            )
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            raise CommandError("DATABASE_URL absent.")

        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        key = f"{BACKUP_PREFIX}prod_{ts}.sql.gz"
        client = _s3_client()

        with tempfile.NamedTemporaryFile(suffix=".sql.gz") as tmp:
            # _pg_dump_gzip lève si pg_dump retourne un code != 0 (auth/réseau) → le
            # pre-deploy s'arrête AVANT migrate (fail-closed). Un succès (code 0)
            # produit un dump valide même sur une DB vierge (schéma seul, 1er deploy)
            # → on l'uploade tel quel sans seuil de taille (qui ferait échouer à tort
            # le premier déploiement).
            raw_bytes = _pg_dump_gzip(database_url, tmp.name)
            client.upload_file(tmp.name, bucket, key)

        logger.info("db backup → s3://%s/%s (%d octets bruts)", bucket, key, raw_bytes)
        self.stdout.write(self.style.SUCCESS(f"✅ Backup DB → s3://{bucket}/{key}"))

        # Rotation = best-effort : le backup est DÉJÀ uploadé (ligne ci-dessus). Un
        # échec de purge (S3 transitoire, droits delete manquants) ne doit PAS faire
        # échouer le pre-deploy et bloquer migrate alors qu'un backup valide existe.
        retention = int(options["retention_days"])  # type: ignore[call-overload]
        try:
            purged = _rotate(client, bucket, retention)
        except Exception:
            logger.exception("db backup rotation a échoué (backup déjà conservé)")
            purged = 0
        if purged:
            logger.info(
                "db backup rotation : %d dump(s) > %dj supprimé(s)", purged, retention
            )
            self.stdout.write(
                f"🧹 {purged} ancien(s) dump(s) purgé(s) (> {retention}j)"
            )


def _backup_setting(backup_key: str, media_key: str, default: str = "") -> str:
    """Préfère la var du bucket DÉDIÉ backups (AWS_BACKUP_*), sinon retombe sur la
    var du bucket média existant (AWS_*). → on bascule vers un bucket de sauvegarde
    séparé (best practice : blast radius isolé) en définissant juste les AWS_BACKUP_*,
    sans toucher au code (#257)."""
    return os.environ.get(backup_key) or os.environ.get(media_key, default)


def _s3_client():  # type: ignore[no-untyped-def]
    """Client boto3 — bucket dédié backups si configuré, sinon le bucket média."""
    return boto3.client(
        "s3",
        endpoint_url=_backup_setting(
            "AWS_BACKUP_ENDPOINT_URL", "AWS_ENDPOINT_URL", "https://storage.railway.app"
        ),
        aws_access_key_id=_backup_setting(
            "AWS_BACKUP_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"
        ),
        aws_secret_access_key=_backup_setting(
            "AWS_BACKUP_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"
        ),
        region_name=_backup_setting("AWS_BACKUP_REGION", "AWS_DEFAULT_REGION", "auto"),
    )


def _pg_dump_gzip(database_url: str, out_path: str) -> int:
    """pg_dump → gzip dans `out_path`. Retourne le nb d'octets BRUTS dumpés.

    Le mot de passe passe par PGPASSWORD (env), jamais dans argv (pas de fuite via
    la liste des process). pg_dump doit être dans le PATH (nixpacks postgresql).
    """
    u = urlparse(database_url)
    # urlparse NE décode PAS le percent-encoding du userinfo → un user/mot de passe
    # contenant @ : / % (ex. "p%40ss") serait passé tel quel à pg_dump et l'auth
    # échouerait. On décode explicitement user + password (unquote("") == "").
    env = {
        **os.environ,
        "PGHOST": u.hostname or "",
        "PGPORT": str(u.port or 5432),
        "PGUSER": unquote(u.username or ""),
        "PGPASSWORD": unquote(u.password or ""),
        "PGDATABASE": (u.path or "").lstrip("/"),
    }
    # --clean --if-exists : restaurable sur une base existante.
    # --no-owner --no-privileges : restaurable dans une DB scratch sans les rôles.
    cmd = ["pg_dump", "--clean", "--if-exists", "--no-owner", "--no-privileges"]
    raw_bytes = 0
    with gzip.open(out_path, "wb") as gz:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(65536), b""):  # type: ignore[union-attr]
            gz.write(chunk)
            raw_bytes += len(chunk)
        if proc.wait() != 0:
            raise CommandError(f"pg_dump a échoué (code {proc.returncode}).")
    return raw_bytes


def _rotate(client, bucket: str, retention_days: int) -> int:  # type: ignore[no-untyped-def]
    """Supprime les dumps `db-backups/` plus vieux que la rétention. Retourne le nb supprimé."""
    cutoff = timezone.now() - timedelta(days=retention_days)
    purged = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=BACKUP_PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
                purged += 1
    return purged
