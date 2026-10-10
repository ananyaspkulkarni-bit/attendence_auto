"""Unit tests for AttendEase data validation rules."""

import datetime
import pytest
import pandas as pd

from attendease.validator import (
    validate_workbook,
    ValidationError,
    IncompleteDataError,
    ValidatedData,
)


@pytest.fixture
def valid_dfs():
    """Provides a pair of valid Attendance and Class_Schedule DataFrames."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "C001": ["P"],
        "C002": ["A"],
        "C003": ["P"],
    }
    sch_data = {
        "class_id": ["C001", "C002", "C003"],
        "class_date": ["2026-10-05", "2026-10-07", "2026-10-20"],
        "subject": ["Python", "Data Structures", "Database"],
    }
    return pd.DataFrame(att_data), pd.DataFrame(sch_data)


def test_valid_workbook(valid_dfs):
    """Verifies that a valid workbook passes validation cleanly."""
    df_att, df_sch = valid_dfs
    reporting_date = datetime.date(2026, 10, 15)

    result = validate_workbook(df_att, df_sch, reporting_date)
    assert isinstance(result, ValidatedData)
    assert len(result.schedule_map) == 3
    assert result.schedule_map["C001"] == datetime.date(2026, 10, 5)


def test_missing_attendance_columns(valid_dfs):
    """Verifies error when required Attendance sheet columns are missing."""
    df_att, df_sch = valid_dfs
    df_att = df_att.drop(columns=["email"])
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Attendance sheet missing required columns"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_missing_schedule_columns(valid_dfs):
    """Verifies error when required Class_Schedule sheet columns are missing."""
    df_att, df_sch = valid_dfs
    df_sch = df_sch.drop(columns=["class_date"])
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Class_Schedule sheet missing required columns"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_duplicate_student_id(valid_dfs):
    """Verifies error when duplicate student IDs exist."""
    df_att, df_sch = valid_dfs
    dup_row = df_att.iloc[0].copy()
    df_att = pd.concat([df_att, pd.DataFrame([dup_row])], ignore_index=True)
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Duplicate student_id found"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_duplicate_class_id(valid_dfs):
    """Verifies error when duplicate class IDs exist in schedule."""
    df_att, df_sch = valid_dfs
    dup_sch = df_sch.iloc[0].copy()
    df_sch = pd.concat([df_sch, pd.DataFrame([dup_sch])], ignore_index=True)
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Duplicate class_id found"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_unmapped_attendance_column(valid_dfs):
    """Verifies error when Attendance has a column not present in Class_Schedule."""
    df_att, df_sch = valid_dfs
    df_att["C999"] = ["P"]
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Attendance columns exist without a corresponding schedule"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_unmapped_scheduled_class(valid_dfs):
    """Verifies error when Class_Schedule has a class ID not in Attendance sheet."""
    df_att, df_sch = valid_dfs
    new_sch = pd.DataFrame([{"class_id": "C999", "class_date": "2026-10-12", "subject": "Math"}])
    df_sch = pd.concat([df_sch, new_sch], ignore_index=True)
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Scheduled class IDs missing from Attendance sheet"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_invalid_date_format(valid_dfs):
    """Verifies error on invalid class date."""
    df_att, df_sch = valid_dfs
    df_sch.loc[df_sch["class_id"] == "C001", "class_date"] = "not-a-valid-date"
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Invalid date format"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_invalid_email_format(valid_dfs):
    """Verifies error on bad email format."""
    df_att, df_sch = valid_dfs
    df_att["email"] = ["invalid-email-address"]
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Invalid or missing email"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_invalid_attendance_mark(valid_dfs):
    """Verifies error when mark is not P, A, or blank."""
    df_att, df_sch = valid_dfs
    df_att["C001"] = ["X"]
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(ValidationError, match="Invalid attendance mark 'X'"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_blank_mark_past_class_raises_incomplete_error(valid_dfs):
    """Verifies IncompleteDataError when a class on or before reporting date has a blank mark."""
    df_att, df_sch = valid_dfs
    # C001 is on 2026-10-05, which is <= reporting_date 2026-10-15
    df_att["C001"] = [""]
    reporting_date = datetime.date(2026, 10, 15)

    with pytest.raises(IncompleteDataError, match="Incomplete attendance data"):
        validate_workbook(df_att, df_sch, reporting_date)


def test_blank_mark_future_class_allowed(valid_dfs):
    """Verifies blank mark on a future class (> reporting date) is permitted."""
    df_att, df_sch = valid_dfs
    # C003 is on 2026-10-20, which is > reporting_date 2026-10-15
    df_att["C003"] = [""]
    reporting_date = datetime.date(2026, 10, 15)

    validated = validate_workbook(df_att, df_sch, reporting_date)
    assert isinstance(validated, ValidatedData)
