"""tests/transactions/test_sentry_test.py — commande sentry_test (#259).

On mocke sentry_sdk (boundary externe) et on prouve : no-op sans DSN, capture_message
avec DSN, capture_exception avec --raise. Aucun event réel envoyé.
"""

from unittest.mock import MagicMock

from django.core.management import call_command


def test_noop_without_dsn(settings, capsys):
    settings.SENTRY_DSN = ""

    call_command("sentry_test")

    out = capsys.readouterr().out
    assert "Sentry désactivé" in out or "Rien envoyé" in out


def test_sends_message_with_dsn(settings, monkeypatch):
    settings.SENTRY_DSN = "https://public@example.ingest.sentry.io/1"
    import sentry_sdk

    capture_message = MagicMock(return_value="evt-123")
    monkeypatch.setattr(sentry_sdk, "capture_message", capture_message)
    monkeypatch.setattr(sentry_sdk, "flush", MagicMock())

    call_command("sentry_test")

    capture_message.assert_called_once()
    assert capture_message.call_args.kwargs.get("level") == "error"


def test_raise_captures_exception(settings, monkeypatch):
    settings.SENTRY_DSN = "https://public@example.ingest.sentry.io/1"
    import sentry_sdk

    capture_exception = MagicMock(return_value="evt-456")
    monkeypatch.setattr(sentry_sdk, "capture_exception", capture_exception)
    monkeypatch.setattr(sentry_sdk, "flush", MagicMock())

    call_command("sentry_test", "--raise")

    capture_exception.assert_called_once()
