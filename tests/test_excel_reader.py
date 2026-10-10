"""Unit tests for AttendEase Excel reader."""

from pathlib import Path
import pytest
import pandas as pd

from attendease.excel_reader import load_workbook, ExcelReadError


def test_load_workbook_not_found():
    """Verifies FileNotFoundError raised when workbook path does not exist."""
    with pytest.raises(FileNotFoundError, match="Attendance workbook not found"):
        load_workbook("non_existent_file.xlsx")


def test_load_workbook_invalid_format(tmp_path):
    """Verifies ExcelReadError raised when file is not a valid Excel file."""
    bad_file = tmp_path / "bad.xlsx"
    bad_file.write_text("not an excel file content", encoding="utf-8")

    with pytest.raises(ExcelReadError, match="Could not open Excel file"):
        load_workbook(bad_file)


def test_load_workbook_missing_sheet(tmp_path):
    """Verifies ExcelReadError raised when workbook is missing expected sheets."""
    incomplete_excel = tmp_path / "incomplete.xlsx"
    with pd.ExcelWriter(incomplete_excel, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="OnlyOneSheet", index=False)

    with pytest.raises(ExcelReadError, match="Workbook missing required sheets"):
        load_workbook(incomplete_excel)


def test_load_workbook_valid(tmp_path):
    """Verifies successful loading of valid workbook."""
    valid_excel = tmp_path / "valid.xlsx"
    with pd.ExcelWriter(valid_excel, engine="openpyxl") as writer:
        pd.DataFrame({"student_id": ["S1001"]}).to_excel(writer, sheet_name="Attendance", index=False)
        pd.DataFrame({"class_id": ["C001"]}).to_excel(writer, sheet_name="Class_Schedule", index=False)

    df_att, df_sch = load_workbook(valid_excel)
    assert "student_id" in df_att.columns
    assert "class_id" in df_sch.columns
