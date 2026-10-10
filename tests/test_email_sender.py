"""Unit tests for AttendEase email generation, dry-run, safety policy, and SMTP delivery."""

import datetime
from email.message import EmailMessage
import socket
import ssl
import smtplib
from unittest.mock import MagicMock, patch
import pytest
import pandas as pd

from attendease.attendance import StudentAttendanceSummary, PeriodAttendance
from attendease.validator import ValidationError, validate_workbook
from attendease.email_sender import (
    build_email_message,
    send_email_report,
    validate_email_syntax,
    validate_recipient_safety,
    validate_smtp_config,
    EmailError,
    EmailSendError,
    RecipientSafetyError,
    SMTPConfigError,
)


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
    """Provides a sample StudentAttendanceSummary for email testing."""
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


def test_validate_email_syntax():
    """Verifies valid email syntax acceptance and invalid rejection."""
    assert validate_email_syntax("user@example.com") == "user@example.com"
    assert validate_email_syntax("  alex.taylor@edu.co.in  ") == "alex.taylor@edu.co.in"

    with pytest.raises(ValidationError, match="Invalid email address syntax"):
        validate_email_syntax("invalid-email")

    with pytest.raises(ValidationError, match="Invalid email address syntax"):
        validate_email_syntax("")


def test_build_email_message_headers_and_body(sample_summary):
    """Verifies subject line, recipient/sender headers, and body metrics formatting."""
    msg = build_email_message(
        summary=sample_summary,
        recipient_email="test_recipient@example.com",
        sender_email="sender@example.com",
        threshold=75.0,
    )
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "test_recipient@example.com"
    assert msg["From"] == "sender@example.com"
    assert "Attendance Report: Alex Taylor (S1001) - 2026-10-15" in msg["Subject"]

    body = msg.get_content()
    assert "Alex Taylor" in body
    assert "S1001" in body
    assert "100.00% (3/3 attended, 0 missed)" in body
    assert "80.00% (4/5 attended, 1 missed)" in body
    assert "80.00% (8/10 attended, 2 missed)" in body
    assert "STATUS: Good Standing" in body
    assert "DISCLAIMER:" in body


def test_build_email_message_warning_triggered(sample_summary):
    """Verifies warning banner included when overall percentage falls below threshold."""
    sample_summary.overall.attendance_percentage = 65.0
    msg = build_email_message(
        summary=sample_summary,
        recipient_email="test_recipient@example.com",
        sender_email="sender@example.com",
        threshold=75.0,
    )
    body = msg.get_content()
    assert "WARNING: OVERALL ATTENDANCE IS BELOW THE REQUIRED TARGET!" in body
    assert "Current Overall: 65.00% | Required Minimum: 75.00%" in body


def test_validate_recipient_safety_match():
    """Verifies recipient safety check passes when recipient matches TEST_RECIPIENT_EMAIL."""
    res = validate_recipient_safety("test@example.com", allowed_test_recipient="test@example.com")
    assert res == "test@example.com"


def test_validate_recipient_safety_mismatch_rejected():
    """Verifies recipient safety check rejects non-test recipient email addresses."""
    with pytest.raises(RecipientSafetyError, match="Recipient safety violation"):
        validate_recipient_safety("other_student@example.com", allowed_test_recipient="test@example.com")


def test_validate_smtp_config_missing_raises_error():
    """Verifies error raised when required SMTP options are unconfigured."""
    with pytest.raises(SMTPConfigError, match="Missing required SMTP configuration"):
        validate_smtp_config(host="", port=587, username="", password="", sender="")


@patch("smtplib.SMTP")
@patch("smtplib.SMTP_SSL")
def test_dry_run_mode_never_opens_smtp_connection(mock_ssl, mock_smtp, sample_summary):
    """Verifies dry-run mode never opens an SMTP or SMTP_SSL connection."""
    success, msg = send_email_report(
        summary=sample_summary,
        recipient_email="alex.taylor@example.edu",
        dry_run=True,
    )
    assert success is True
    assert "Dry-run preview" in msg
    mock_smtp.assert_not_called()
    mock_ssl.assert_not_called()


@patch("smtplib.SMTP")
def test_real_send_starttls_success(mock_smtp_cls, sample_summary):
    """Verifies successful real email sending over STARTTLS (port 587)."""
    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    success, msg = send_email_report(
        summary=sample_summary,
        recipient_email="test@example.com",
        sender_email="sender@example.com",
        dry_run=False,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user@example.com",
        smtp_password="secret_password",
        test_recipient_email="test@example.com",
    )

    assert success is True
    assert "Email accepted by SMTP server" in msg
    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user@example.com", "secret_password")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_real_send_implicit_tls_success(mock_ssl_cls, sample_summary):
    """Verifies successful real email sending over implicit TLS (port 465)."""
    mock_server = MagicMock()
    mock_ssl_cls.return_value.__enter__.return_value = mock_server

    success, msg = send_email_report(
        summary=sample_summary,
        recipient_email="test@example.com",
        sender_email="sender@example.com",
        dry_run=False,
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="user@example.com",
        smtp_password="secret_password",
        test_recipient_email="test@example.com",
    )

    assert success is True
    assert "Email accepted by SMTP server" in msg
    mock_ssl_cls.assert_called_once()
    mock_server.login.assert_called_once_with("user@example.com", "secret_password")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP")
def test_smtp_auth_error_handled(mock_smtp_cls, sample_summary):
    """Verifies SMTPAuthenticationError is caught and raised as EmailSendError without claiming success."""
    mock_server = MagicMock()
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    with pytest.raises(EmailSendError, match="SMTP Authentication failed"):
        send_email_report(
            summary=sample_summary,
            recipient_email="test@example.com",
            sender_email="sender@example.com",
            dry_run=False,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="wrong_password",
            test_recipient_email="test@example.com",
        )


@patch("smtplib.SMTP")
def test_smtp_timeout_handled(mock_smtp_cls, sample_summary):
    """Verifies socket.timeout is caught and handled cleanly."""
    mock_smtp_cls.side_effect = socket.timeout("Connection timed out")

    with pytest.raises(EmailSendError, match="SMTP connection timed out"):
        send_email_report(
            summary=sample_summary,
            recipient_email="test@example.com",
            sender_email="sender@example.com",
            dry_run=False,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="password",
            test_recipient_email="test@example.com",
        )


def test_invalid_attendance_data_prevents_email():
    """Verifies incomplete/invalid attendance workbook raises ValidationError before email step."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "C001": ["X"],  # Invalid attendance mark
    }
    sch_data = {
        "class_id": ["C001"],
        "class_date": ["2026-10-05"],
        "subject": ["Python"],
    }
    df_att = pd.DataFrame(att_data)
    df_sch = pd.DataFrame(sch_data)
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Invalid attendance mark"):
        validate_workbook(df_att, df_sch, reporting_date)
