"""Stage 5: Unit tests for configuration validation, CLI options, and security checks."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from attendease.attendance import StudentAttendanceSummary, PeriodAttendance
from attendease.config import (
    ConfigError,
    parse_float_setting,
    parse_int_setting,
    validate_config,
)
from attendease.email_sender import send_email_report
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


@pytest.fixture
def sample_summary():
    """Provides a sample StudentAttendanceSummary for testing."""
    weekly = PeriodAttendance(
        period_name="Weekly",
        start_date=datetime.date(2026, 10, 12),
        end_date=datetime.date(2026, 10, 15),
        classes_held=3,
        classes_attended=3,
        classes_missed=0,
        attendance_percentage=100.0,
    )
    monthly = PeriodAttendance(
        period_name="Monthly",
        start_date=datetime.date(2026, 10, 1),
        end_date=datetime.date(2026, 10, 15),
        classes_held=5,
        classes_attended=4,
        classes_missed=1,
        attendance_percentage=80.0,
    )
    overall = PeriodAttendance(
        period_name="Overall",
        start_date=datetime.date(2026, 9, 7),
        end_date=datetime.date(2026, 10, 15),
        classes_held=10,
        classes_attended=8,
        classes_missed=2,
        attendance_percentage=80.0,
    )
    return StudentAttendanceSummary(
        student_id="S1001",
        name="Alex Taylor",
        email="alex.taylor@example.edu",
        reporting_date=datetime.date(2026, 10, 15),
        weekly=weekly,
        monthly=monthly,
        overall=overall,
    )


def test_validate_config_success():
    """Verifies validate_config returns validated configuration dictionary."""
    config = validate_config()
    assert isinstance(config, dict)
    assert config["ATTENDANCE_THRESHOLD"] == 75.0
    assert config["DRY_RUN"] is True


def test_invalid_attendance_threshold_raises_config_error(monkeypatch):
    """Verifies ConfigError raised when ATTENDANCE_THRESHOLD is not a number or out of bounds."""
    monkeypatch.setenv("ATTENDANCE_THRESHOLD", "invalid_number")
    with pytest.raises(ConfigError, match="must be a valid number"):
        parse_float_setting("ATTENDANCE_THRESHOLD", "75.0", 0.0, 100.0)

    monkeypatch.setenv("ATTENDANCE_THRESHOLD", "150.0")
    with pytest.raises(ConfigError, match="must be between 0.0 and 100.0"):
        parse_float_setting("ATTENDANCE_THRESHOLD", "75.0", 0.0, 100.0)


def test_invalid_smtp_port_raises_config_error(monkeypatch):
    """Verifies ConfigError raised when SMTP_PORT is out of range 1..65535."""
    monkeypatch.setenv("SMTP_PORT", "999999")
    with pytest.raises(ConfigError, match="must be between 1 and 65535"):
        parse_int_setting("SMTP_PORT", "587", 1, 65535)


def test_invalid_log_level_raises_config_error(monkeypatch):
    """Verifies ConfigError raised for invalid LOG_LEVEL."""
    monkeypatch.setattr("attendease.config.LOG_LEVEL", "INVALID_LEVEL")
    with pytest.raises(ConfigError, match="Invalid LOG_LEVEL"):
        validate_config()


def test_cli_validate_only_option(monkeypatch, capsys):
    """Verifies --validate-only option validates workbook and exits code 0."""
    test_args = ["main.py", "--validate-only", "--date", "2026-10-15"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "WORKBOOK VALIDATION SUCCESSFUL" in captured.out
    assert "Total Students" in captured.out


def test_cli_preview_only_option(monkeypatch, capsys):
    """Verifies --preview-only option prints report markdown without saving file."""
    test_args = ["main.py", "--preview-only", "--student-id", "S1001", "--date", "2026-10-15"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ATTENDEASE REPORT PREVIEW" in captured.out
    assert "Alex Taylor" in captured.out


def test_cli_nonexistent_workbook_path(monkeypatch, capsys):
    """Verifies clear error displayed when workbook file does not exist."""
    test_args = ["main.py", "--excel", "nonexistent_file.xlsx"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "FILE ERROR" in captured.err or "VALIDATION ERROR" in captured.err


def test_cli_invalid_date_format(monkeypatch, capsys):
    """Verifies error message when date format is invalid."""
    test_args = ["main.py", "--date", "invalid-date"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CONFIGURATION ERROR" in captured.err or "Invalid date format" in captured.err


def test_cli_invalid_threshold_out_of_bounds(monkeypatch, capsys):
    """Verifies error message when threshold is out of bounds."""
    test_args = ["main.py", "--threshold", "200.0"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Threshold must be between 0.0 and 100.0" in captured.err


@patch("smtplib.SMTP")
def test_report_preview_works_without_smtp_credentials(mock_smtp, sample_summary):
    """Verifies dry-run preview works with zero SMTP credentials configured."""
    success, msg = send_email_report(
        summary=sample_summary,
        recipient_email="test@example.com",
        sender_email="",
        dry_run=True,
        smtp_host="",
        smtp_username="",
        smtp_password="",
    )
    assert success is True
    assert "Dry-run preview" in msg
    mock_smtp.assert_not_called()
