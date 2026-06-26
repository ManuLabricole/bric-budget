"""
tests/transactions/test_dump_db_to_s3.py — backup DB → S3 (#257).

On mocke les BOUNDARIES externes (subprocess pg_dump + client boto3) et on prouve :
upload sous la bonne clé, fail-closed si pg_dump échoue, rotation des vieux dumps,
préférence du bucket dédié, erreurs de config. Aucune vraie DB / vrai S3.
"""

import io
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from transactions.management.commands import dump_db_to_s3 as mod


class _FakeProc:
    """pg_dump simulé : `stdout` lisible par chunks + code retour contrôlé."""

    def __init__(self, data: bytes, returncode: int = 0):
        self.stdout = io.BytesIO(data)
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.fixture
def s3(monkeypatch):
    """Client boto3 mocké + env minimal (bucket média + creds + DATABASE_URL)."""
    client = MagicMock()
    monkeypatch.setattr(mod.boto3, "client", lambda *a, **k: client)
    monkeypatch.setenv("AWS_S3_BUCKET_NAME", "media-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    # Pas de vieux dumps par défaut (rotation no-op).
    client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
    return client


def _ok_pg_dump(monkeypatch, data=b"-- SQL DUMP\n" * 300, returncode=0):
    monkeypatch.setattr(
        mod.subprocess, "Popen", lambda *a, **k: _FakeProc(data, returncode)
    )


def test_uploads_dump_under_db_backups_key(s3, monkeypatch):
    _ok_pg_dump(monkeypatch)

    call_command("dump_db_to_s3")

    assert s3.upload_file.call_count == 1
    _local, bucket, key = s3.upload_file.call_args.args
    assert bucket == "media-bucket"  # fallback sur le bucket média
    assert key.startswith("db-backups/prod_")
    assert key.endswith(".sql.gz")


def test_prefers_dedicated_backup_bucket(s3, monkeypatch):
    monkeypatch.setenv("AWS_BACKUP_BUCKET_NAME", "backup-bucket")
    _ok_pg_dump(monkeypatch)

    call_command("dump_db_to_s3")

    _local, bucket, _key = s3.upload_file.call_args.args
    assert bucket == "backup-bucket"  # bucket dédié prioritaire


def test_pg_dump_failure_is_fail_closed(s3, monkeypatch):
    # pg_dump code != 0 (auth/réseau) → CommandError, AUCUN upload (le pre-deploy
    # s'arrête avant migrate).
    _ok_pg_dump(monkeypatch, returncode=1)

    with pytest.raises(CommandError):
        call_command("dump_db_to_s3")
    assert s3.upload_file.call_count == 0


def test_rotation_deletes_only_old_dumps(s3, monkeypatch):
    _ok_pg_dump(monkeypatch)
    old = timezone.now() - timedelta(days=30)
    recent = timezone.now() - timedelta(days=1)
    s3.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {"Key": "db-backups/prod_old.sql.gz", "LastModified": old},
                {"Key": "db-backups/prod_recent.sql.gz", "LastModified": recent},
            ]
        }
    ]

    call_command("dump_db_to_s3", "--retention-days", "14")

    deleted = [c.kwargs["Key"] for c in s3.delete_object.call_args_list]
    assert deleted == ["db-backups/prod_old.sql.gz"]  # le récent est conservé


def test_missing_bucket_raises(monkeypatch):
    monkeypatch.delenv("AWS_S3_BUCKET_NAME", raising=False)
    monkeypatch.delenv("AWS_BACKUP_BUCKET_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")

    with pytest.raises(CommandError):
        call_command("dump_db_to_s3")


def test_missing_database_url_raises(monkeypatch):
    monkeypatch.setenv("AWS_S3_BUCKET_NAME", "media-bucket")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(CommandError):
        call_command("dump_db_to_s3")


def test_pg_dump_env_decodes_percent_encoded_credentials(s3, monkeypatch):
    # urlparse ne décode PAS le %-encoding → un mot de passe "p@ss/w:rd" encodé en
    # "p%40ss%2Fw%3Ard" doit arriver DÉCODÉ dans PGPASSWORD, sinon l'auth pg_dump casse.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://us%40er:p%40ss%2Fw%3Ard@host:5432/db"
    )
    captured: dict = {}

    def _capture_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return _FakeProc(b"-- SQL DUMP\n" * 300, returncode=0)

    monkeypatch.setattr(mod.subprocess, "Popen", _capture_popen)

    call_command("dump_db_to_s3")

    assert captured["env"]["PGUSER"] == "us@er"
    assert captured["env"]["PGPASSWORD"] == "p@ss/w:rd"
