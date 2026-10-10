"""Unit tests for Stage 3 delivery history, duplicate-send prevention, and CLI options."""

import datetime
from unittest.mock import MagicMock, patch
import pytest
import sqlite3

from attendease.attendance import StudentAttendanceSummary, PeriodAttendance
from attendease.config import ATTENDANCE_THRESHOLD
from attendease.email_sender import send_email_report, EmailSendError
from attendease.history import (
    DatabaseAccessError,
    DuplicateSendError,
    DeliveryRecord,
    generate_report_key,
    get_delivery_history,
    get_last_successful_delivery,
    init_db,
    is_report_sent,
    record_delivery_failure,
    record_delivery_success,
    start_delivery_attempt,
)
from attendease.main import main


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh temporary SQLite database path."""
    return tmp_path / "test_delivery_history.db"


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


def test_generate_report_key():
    """Verifies deterministic report key format."""
    key1 = generate_report_key("S1001", datetime.date(2026, 10, 15))
    key2 = generate_report_key("S1001", "2026-10-15")
    assert key1 == "S1001:attendance_summary:2026-10-15"
    assert key2 == "S1001:attendance_summary:2026-10-15"


def test_create_and_read_delivery_history(test_db):
    """Verifies creating delivery records and reading them back."""
    init_db(test_db)
    key = generate_report_key("S1001", "2026-10-15")
    
    del_id = start_delivery_attempt(
        report_key=key,
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    assert del_id > 0

    record_delivery_success(del_id, db_path=test_db)
    
    assert is_report_sent(key, db_path=test_db) is True
    records = get_delivery_history(student_id="S1001", db_path=test_db)
    assert len(records) == 1
    assert records[0].status == "SUCCESS"
    assert records[0].student_id == "S1001"
    assert records[0].recipient == "test@example.com"


def test_detect_previously_successful_report(test_db):
    """Verifies detecting previously sent report status and details."""
    key = generate_report_key("S1001", "2026-10-15")
    assert get_last_successful_delivery(key, db_path=test_db) is None

    del_id = start_delivery_attempt(
        report_key=key,
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    record_delivery_success(del_id, db_path=test_db)

    record = get_last_successful_delivery(key, db_path=test_db)
    assert record is not None
    assert record.report_key == key
    assert record.status == "SUCCESS"


def test_blocking_duplicate_sends(test_db):
    """Verifies second send attempt without allow_resend raises DuplicateSendError."""
    key = generate_report_key("S1001", "2026-10-15")
    del_id = start_delivery_attempt(
        report_key=key,
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    record_delivery_success(del_id, db_path=test_db)

    with pytest.raises(DuplicateSendError, match="already successfully sent"):
        start_delivery_attempt(
            report_key=key,
            student_id="S1001",
            reporting_date="2026-10-15",
            recipient="test@example.com",
            allow_resend=False,
            db_path=test_db,
        )


def test_allowing_resend_with_explicit_override(test_db):
    """Verifies allow_resend=True permits creating a new delivery attempt for sent report."""
    key = generate_report_key("S1001", "2026-10-15")
    del_id1 = start_delivery_attempt(
        report_key=key,
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    record_delivery_success(del_id1, db_path=test_db)

    del_id2 = start_delivery_attempt(
        report_key=key,
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        allow_resend=True,
        db_path=test_db,
    )
    record_delivery_success(del_id2, db_path=test_db)
    assert del_id2 > del_id1

    records = get_delivery_history(student_id="S1001", db_path=test_db)
    assert len(records) == 2


@patch("smtplib.SMTP")
def test_dry_run_not_recorded_as_successful_send(mock_smtp, test_db, sample_summary):
    """Verifies dry-run previews do not record any success entries in history DB."""
    success, msg = send_email_report(
        summary=sample_summary,
        recipient_email="test@example.com",
        dry_run=True,
        db_path=test_db,
    )
    assert success is True
    key = generate_report_key("S1001", "2026-10-15")
    assert is_report_sent(key, db_path=test_db) is False
    assert len(get_delivery_history(db_path=test_db)) == 0


@patch("smtplib.SMTP")
def test_smtp_failure_not_recorded_as_successful_send(mock_smtp_cls, test_db, sample_summary):
    """Verifies SMTP failures record a FAILED status and do not mark report as sent."""
    mock_server = MagicMock()
    mock_server.login.side_effect = Exception("SMTP Connection Failed")
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    with pytest.raises(EmailSendError):
        send_email_report(
            summary=sample_summary,
            recipient_email="test@example.com",
            sender_email="sender@example.com",
            dry_run=False,
            db_path=test_db,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="pwd",
            test_recipient_email="test@example.com",
        )

    key = generate_report_key("S1001", "2026-10-15")
    assert is_report_sent(key, db_path=test_db) is False

    records = get_delivery_history(db_path=test_db)
    assert len(records) == 1
    assert records[0].status == "FAILED"
    assert "SMTP Connection Failed" in records[0].error_summary


@patch("attendease.history.get_db_connection")
@patch("smtplib.SMTP")
def test_database_error_prevents_real_send(mock_smtp, mock_db_conn, sample_summary, test_db):
    """Verifies database access failure aborts execution before SMTP send attempt."""
    mock_db_conn.side_effect = sqlite3.OperationalError("Database disk image is malformed")

    with pytest.raises(DatabaseAccessError, match="Database"):
        send_email_report(
            summary=sample_summary,
            recipient_email="test@example.com",
            sender_email="sender@example.com",
            dry_run=False,
            db_path=test_db,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="pwd",
            test_recipient_email="test@example.com",
        )

    mock_smtp.assert_not_called()


def test_distinct_students_and_reporting_periods(test_db):
    """Verifies distinct student IDs and dates maintain separate history records."""
    key1 = generate_report_key("S1001", "2026-10-15")
    key2 = generate_report_key("S1002", "2026-10-15")
    key3 = generate_report_key("S1001", "2026-10-22")

    del1 = start_delivery_attempt(report_key=key1, student_id="S1001", reporting_date="2026-10-15", recipient="a@ex.com", db_path=test_db)
    record_delivery_success(del1, db_path=test_db)

    # S1002 on same date should succeed
    del2 = start_delivery_attempt(report_key=key2, student_id="S1002", reporting_date="2026-10-15", recipient="b@ex.com", db_path=test_db)
    record_delivery_success(del2, db_path=test_db)

    # S1001 on different date should succeed
    del3 = start_delivery_attempt(report_key=key3, student_id="S1001", reporting_date="2026-10-22", recipient="a@ex.com", db_path=test_db)
    record_delivery_success(del3, db_path=test_db)

    assert is_report_sent(key1, db_path=test_db) is True
    assert is_report_sent(key2, db_path=test_db) is True
    assert is_report_sent(key3, db_path=test_db) is True


def test_cli_history_option(monkeypatch, capsys, test_db):
    """Verifies --history CLI option displays past delivery records."""
    init_db(test_db)
    del_id = start_delivery_attempt(
        report_key="S1001:attendance_summary:2026-10-15",
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    record_delivery_success(del_id, db_path=test_db)

    test_args = ["main.py", "--history", "--db-path", str(test_db)]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ATTENDEASE DELIVERY HISTORY" in captured.out
    assert "S1001" in captured.out
    assert "SUCCESS" in captured.out


def test_cli_check_sent_option(monkeypatch, capsys, test_db):
    """Verifies --check-sent CLI option displays report delivery status."""
    init_db(test_db)
    del_id = start_delivery_attempt(
        report_key="S1001:attendance_summary:2026-10-15",
        student_id="S1001",
        reporting_date="2026-10-15",
        recipient="test@example.com",
        db_path=test_db,
    )
    record_delivery_success(del_id, db_path=test_db)

    test_args = ["main.py", "--check-sent", "--student-id", "S1001", "--date", "2026-10-15", "--db-path", str(test_db)]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "STATUS    : ALREADY SENT" in captured.out
    assert "test@example.com" in captured.out
