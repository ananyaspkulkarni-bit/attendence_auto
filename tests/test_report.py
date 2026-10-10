"""Unit tests for AttendEase report generation and export."""

import datetime
from pathlib import Path
import pytest

from attendease.attendance import StudentAttendanceSummary, PeriodAttendance
from attendease.report import generate_report_markdown, save_report_to_file, format_period_str


@pytest.fixture
def sample_summary():
    """Provides a sample StudentAttendanceSummary for report testing."""
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


def test_format_period_str_with_data():
    """Verifies format_period_str when classes were held."""
    period = PeriodAttendance("Weekly", datetime.date(2026, 10, 12), datetime.date(2026, 10, 15), 3, 2, 1, 66.67)
    res = format_period_str(period)
    assert "66.67%" in res
    assert "2/3 attended" in res
    assert "1 missed" in res


def test_format_period_str_no_data():
    """Verifies format_period_str when 0 classes were held."""
    period = PeriodAttendance("Weekly", datetime.date(2026, 10, 12), datetime.date(2026, 10, 15), 0, 0, 0, None)
    res = format_period_str(period)
    assert res == "No classes held in this period (N/A)"


def test_generate_report_markdown_good_standing(sample_summary):
    """Verifies markdown report content for student meeting attendance threshold."""
    report = generate_report_markdown(sample_summary, threshold=75.0)
    assert "Student Name   : Alex Taylor" in report
    assert "Student ID     : S1001" in report
    assert "STATUS: Good Standing" in report
    assert "WARNING" not in report


def test_generate_report_markdown_warning_triggered(sample_summary):
    """Verifies warning status when overall attendance is below threshold."""
    sample_summary.overall.attendance_percentage = 60.0
    report = generate_report_markdown(sample_summary, threshold=75.0)
    assert "WARNING: OVERALL ATTENDANCE IS BELOW THE REQUIRED TARGET!" in report
    assert "Required Minimum: 75.00%" in report


def test_save_report_to_file(tmp_path, sample_summary):
    """Verifies report text is written correctly to output directory."""
    report_text = generate_report_markdown(sample_summary)
    saved_path = save_report_to_file(report_text, "S1001", output_dir=tmp_path)

    assert saved_path.exists()
    assert saved_path.name == "report_S1001.txt"
    content = saved_path.read_text(encoding="utf-8")
    assert "ATTENDEASE REPORT PREVIEW" in content
    assert "Alex Taylor" in content
