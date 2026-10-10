"""Stage 4: Real-World Excel Compatibility and End-to-End Reliability Tests."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from attendease.attendance import calculate_student_attendance
from attendease.config import ATTENDANCE_THRESHOLD
from attendease.email_sender import send_email_report, EmailSendError
from attendease.excel_reader import load_workbook, ExcelReadError
from attendease.history import (
    DatabaseAccessError,
    DuplicateSendError,
    generate_report_key,
    get_delivery_history,
    is_report_sent,
)
from attendease.main import main
from attendease.report import generate_report_markdown, save_report_to_file
from attendease.validator import (
    IncompleteDataError,
    ValidationError,
    validate_workbook,
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


def create_excel_workbook(filepath: Path, attendance_data: dict, schedule_data: dict, sheet_names=("Attendance", "Class_Schedule")):
    """Helper to generate physical .xlsx files with specific sheets and data."""
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        if "Attendance" in sheet_names:
            df_att = pd.DataFrame(attendance_data)
            df_att.to_excel(writer, sheet_name="Attendance", index=False)
        if "Class_Schedule" in sheet_names:
            df_sch = pd.DataFrame(schedule_data)
            df_sch.to_excel(writer, sheet_name="Class_Schedule", index=False)


# --- TASK 1 FIXTURES & TESTS: REALISTIC EXCEL WORKBOOKS ---

def test_excel_fixture_whitespace_and_lowercase_normalization(tmp_path):
    """Verifies whitespace around headers/values and lowercase marks 'p'/'a' are normalized cleanly."""
    att_data = {
        " student_id ": [" S1001 "],
        " name ": [" Alex Taylor "],
        " email ": [" alex.taylor@example.edu "],
        " C001 ": [" p "],
        " C002 ": [" a "],
        " C003 ": ["   "],  # Future class
    }
    sch_data = {
        " class_id ": [" C001 ", " C002 ", " C003 "],
        " class_date ": [" 2026-10-05 ", " 2026-10-07 ", " 2026-10-20 "],
        " subject ": [" Python Programming ", " Data Structures ", " Database Systems "],
    }
    excel_file = tmp_path / "whitespace_lowercase.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    validated = validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))

    assert validated.df_attendance["student_id"].iloc[0] == "S1001"
    assert validated.df_attendance["name"].iloc[0] == "Alex Taylor"
    assert validated.df_attendance["email"].iloc[0] == "alex.taylor@example.edu"
    assert validated.df_attendance["C001"].iloc[0] == "P"
    assert validated.df_attendance["C002"].iloc[0] == "A"
    assert validated.df_attendance["C003"].iloc[0] == ""


def test_excel_fixture_extra_irrelevant_columns(tmp_path):
    """Verifies extra non-class metadata columns (e.g. department, phone, instructor, room) are permitted and ignored."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "department": ["Computer Science"],
        "phone": ["555-0199"],
        "C001": ["P"],
        "C002": ["P"],
    }
    sch_data = {
        "class_id": ["C001", "C002"],
        "class_date": ["2026-10-05", "2026-10-07"],
        "subject": ["Python", "Data Structures"],
        "instructor": ["Dr. Smith", "Dr. Jones"],
        "room": ["Lab 301", "Lab 302"],
    }
    excel_file = tmp_path / "extra_columns.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    validated = validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))

    summary = calculate_student_attendance(validated, "S1001", reporting_date=datetime.date(2026, 10, 15))
    assert summary.overall.classes_held == 2
    assert summary.overall.classes_attended == 2


def test_excel_fixture_missing_sheet(tmp_path):
    """Verifies error raised when a required sheet is missing from workbook."""
    att_data = {"student_id": ["S1001"], "name": ["Alex"], "email": ["alex@example.edu"], "C001": ["P"]}
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "missing_sheet.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data, sheet_names=("Attendance",))

    with pytest.raises(ExcelReadError, match="missing required sheets"):
        load_workbook(excel_file)


def test_excel_fixture_missing_required_column(tmp_path):
    """Verifies error raised when required student_id column is missing."""
    att_data = {"name": ["Alex"], "email": ["alex@example.edu"], "C001": ["P"]}
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "missing_col.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    with pytest.raises(ValidationError, match="Attendance sheet missing required columns"):
        validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))


def test_excel_fixture_duplicate_student_id(tmp_path):
    """Verifies error raised when duplicate student IDs exist."""
    att_data = {
        "student_id": ["S1001", "S1001"],
        "name": ["Alex Taylor", "Alex Duplicate"],
        "email": ["alex@example.edu", "alex2@example.edu"],
        "C001": ["P", "A"],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "dup_student.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    with pytest.raises(ValidationError, match="Duplicate student_id found"):
        validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))


def test_excel_fixture_unknown_class_column(tmp_path):
    """Verifies error raised when attendance sheet has an unmapped class column C999."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex@example.edu"],
        "C001": ["P"],
        "C999": ["P"],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "unknown_class.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    with pytest.raises(ValidationError, match="Attendance columns exist without a corresponding schedule"):
        validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))


def test_excel_fixture_invalid_attendance_mark(tmp_path):
    """Verifies error raised when attendance mark is invalid (e.g. 'Late' or 'X')."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex@example.edu"],
        "C001": ["Late"],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "invalid_mark.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    with pytest.raises(ValidationError, match="Invalid attendance mark 'Late'"):
        validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))


def test_excel_fixture_blank_mark_past_class(tmp_path):
    """Verifies IncompleteDataError raised for blank mark on past class."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex@example.edu"],
        "C001": [""],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file = tmp_path / "blank_past.xlsx"
    create_excel_workbook(excel_file, att_data, sch_data)

    df_att, df_sch = load_workbook(excel_file)
    with pytest.raises(IncompleteDataError, match="Incomplete attendance data"):
        validate_workbook(df_att, df_sch, reporting_date=datetime.date(2026, 10, 15))


def test_excel_fixture_invalid_date_and_email(tmp_path):
    """Verifies errors raised for invalid dates and malformed emails."""
    # Bad Email
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["invalid-email-no-at-sign"],
        "C001": ["P"],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    excel_file1 = tmp_path / "bad_email.xlsx"
    create_excel_workbook(excel_file1, att_data, sch_data)

    df_att1, df_sch1 = load_workbook(excel_file1)
    with pytest.raises(ValidationError, match="Invalid or missing email"):
        validate_workbook(df_att1, df_sch1, reporting_date=datetime.date(2026, 10, 15))

    # Bad Date
    att_data2 = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex@example.edu"],
        "C001": ["P"],
    }
    sch_data2 = {"class_id": ["C001"], "class_date": ["invalid-date-format"], "subject": ["Math"]}
    excel_file2 = tmp_path / "bad_date.xlsx"
    create_excel_workbook(excel_file2, att_data2, sch_data2)

    df_att2, df_sch2 = load_workbook(excel_file2)
    with pytest.raises(ValidationError, match="Invalid date format"):
        validate_workbook(df_att2, df_sch2, reporting_date=datetime.date(2026, 10, 15))


# --- TASK 3 END-TO-END WORKFLOW & SAFETY TESTS ---

@patch("smtplib.SMTP")
def test_full_end_to_end_successful_flow(mock_smtp_cls, tmp_path, monkeypatch, capsys):
    """Exercises full E2E workflow: Excel loading -> Validation -> Calculation -> Preview -> Dry Run -> Real Send -> History -> Duplicate Blocking."""
    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    monkeypatch.setattr("attendease.email_sender.SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("attendease.email_sender.SMTP_PORT", 587)
    monkeypatch.setattr("attendease.email_sender.SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr("attendease.email_sender.SMTP_PASSWORD", "secret_password")
    monkeypatch.setattr("attendease.email_sender.SENDER_EMAIL", "sender@example.com")
    monkeypatch.setattr("attendease.main.SENDER_EMAIL", "sender@example.com")

    excel_file = tmp_path / "e2e_sample.xlsx"
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "C001": ["P"],
        "C002": ["P"],
        "C003": ["A"],
        "C004": [" "],  # Future class on 2026-10-20
    }
    sch_data = {
        "class_id": ["C001", "C002", "C003", "C004"],
        "class_date": ["2026-10-05", "2026-10-12", "2026-10-14", "2026-10-20"],
        "subject": ["Python", "Algorithms", "Database", "Web Dev"],
    }
    create_excel_workbook(excel_file, att_data, sch_data)

    test_db = tmp_path / "e2e_history.db"

    # Step 1: Default Dry Run via CLI
    cli_args_dry = [
        "main.py",
        "--excel", str(excel_file),
        "--student-id", "S1001",
        "--date", "2026-10-15",
        "--db-path", str(test_db),
    ]
    monkeypatch.setattr("sys.argv", cli_args_dry)
    main()

    captured = capsys.readouterr()
    assert "DRY RUN — EMAIL REPORT PREVIEW" in captured.out
    assert "Alex Taylor" in captured.out
    assert "66.67%" in captured.out or "2/3 attended" in captured.out
    assert "WARNING: OVERALL ATTENDANCE IS BELOW THE REQUIRED TARGET!" in captured.out

    key = generate_report_key("S1001", "2026-10-15")
    assert is_report_sent(key, db_path=test_db) is False

    # Step 2: Real Send via CLI with --yes and test recipient
    monkeypatch.setattr("attendease.email_sender.TEST_RECIPIENT_EMAIL", "test@example.com")
    cli_args_real = [
        "main.py",
        "--excel", str(excel_file),
        "--student-id", "S1001",
        "--date", "2026-10-15",
        "--send",
        "--recipient", "test@example.com",
        "--yes",
        "--db-path", str(test_db),
    ]
    monkeypatch.setattr("sys.argv", cli_args_real)
    main()

    captured_real = capsys.readouterr()
    assert "Email accepted by SMTP server" in captured_real.out
    assert is_report_sent(key, db_path=test_db) is True

    # Step 3: Second Real Send Attempt (Blocked as Duplicate)
    monkeypatch.setattr("sys.argv", cli_args_real)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    captured_dup = capsys.readouterr()
    assert "DUPLICATE SEND BLOCKED" in captured_dup.err

    # Step 4: Resend with --resend flag
    cli_args_resend = cli_args_real + ["--resend"]
    monkeypatch.setattr("sys.argv", cli_args_resend)
    main()

    captured_resend = capsys.readouterr()
    assert "EXPLICIT RESEND OVERRIDE ACTIVE" in captured_resend.out or "Email accepted" in captured_resend.out
    assert len(get_delivery_history(student_id="S1001", db_path=test_db)) == 2


@patch("smtplib.SMTP")
def test_invalid_input_stops_process_before_email_send(mock_smtp, tmp_path, monkeypatch, capsys):
    """Verifies invalid input aborts execution immediately before any SMTP call can occur."""
    excel_file = tmp_path / "invalid_input.xlsx"
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "C001": ["INVALID_MARK"],
    }
    sch_data = {"class_id": ["C001"], "class_date": ["2026-10-05"], "subject": ["Math"]}
    create_excel_workbook(excel_file, att_data, sch_data)

    test_db = tmp_path / "e2e_history.db"
    monkeypatch.setattr("attendease.email_sender.TEST_RECIPIENT_EMAIL", "test@example.com")

    cli_args = [
        "main.py",
        "--excel", str(excel_file),
        "--student-id", "S1001",
        "--date", "2026-10-15",
        "--send",
        "--recipient", "test@example.com",
        "--yes",
        "--db-path", str(test_db),
    ]
    monkeypatch.setattr("sys.argv", cli_args)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_smtp.assert_not_called()
    captured = capsys.readouterr()
    assert "VALIDATION ERROR" in captured.err
    assert len(get_delivery_history(db_path=test_db)) == 0
