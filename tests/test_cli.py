"""Unit tests for AttendEase CLI interface and execution workflows."""

import datetime
from unittest.mock import patch, MagicMock
import pytest

from attendease.main import main


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Ensures each test operates on an isolated temporary database."""
    test_db = tmp_path / "test_delivery_history.db"
    monkeypatch.setattr("attendease.config.DB_PATH", test_db)
    monkeypatch.setattr("attendease.email_sender.DB_PATH", test_db)
    monkeypatch.setattr("attendease.history.DB_PATH", test_db)
    monkeypatch.setattr("attendease.main.DB_PATH", test_db)
    return test_db


def test_cli_dry_run_default(tmp_path, monkeypatch, capsys):
    """Verifies default CLI execution generates a dry-run email preview."""
    test_args = ["main.py", "--date", "2026-10-15"]
    monkeypatch.setattr("sys.argv", test_args)

    main()

    captured = capsys.readouterr()
    assert "DRY RUN — EMAIL REPORT PREVIEW" in captured.out
    assert "Alex Taylor" in captured.out
    assert "[DRY-RUN MODE ACTIVE]" in captured.out


def test_cli_select_student(tmp_path, monkeypatch, capsys):
    """Verifies student ID selection via --student-id flag."""
    test_args = ["main.py", "--student-id", "S1001", "--date", "2026-10-15"]
    monkeypatch.setattr("sys.argv", test_args)

    main()

    captured = capsys.readouterr()
    assert "Student ID     : S1001" in captured.out


def test_cli_real_send_non_interactive_aborts(monkeypatch, capsys):
    """Verifies real send attempt in non-interactive shell without --yes aborts cleanly."""
    test_args = ["main.py", "--send", "--recipient", "test@example.com", "--date", "2026-10-15"]
    monkeypatch.setattr("sys.argv", test_args)
    monkeypatch.setattr("attendease.email_sender.TEST_RECIPIENT_EMAIL", "test@example.com")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CONFIRMATION ABORTED" in captured.err


def test_cli_real_send_recipient_mismatch_aborts(monkeypatch, capsys):
    """Verifies recipient safety rejection when target recipient differs from TEST_RECIPIENT_EMAIL."""
    test_args = [
        "main.py",
        "--send",
        "--recipient", "wrong_recipient@example.com",
        "--yes",
        "--date", "2026-10-15"
    ]
    monkeypatch.setattr("sys.argv", test_args)
    monkeypatch.setattr("attendease.email_sender.TEST_RECIPIENT_EMAIL", "correct_test@example.com")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "SAFETY REJECTION" in captured.err
