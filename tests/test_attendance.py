"""Unit tests for AttendEase attendance statistics calculations."""

import datetime
import pytest
import pandas as pd

from attendease.validator import validate_workbook
from attendease.attendance import (
    calculate_student_attendance,
    get_week_range,
    PeriodAttendance,
)


@pytest.fixture
def multi_period_workbook():
    """Provides a synthetic workbook with classes spanning multiple weeks and months."""
    att_data = {
        "student_id": ["S1001"],
        "name": ["Alex Taylor"],
        "email": ["alex.taylor@example.edu"],
        "C001": ["P"],  # Mon 2026-09-07 (W37)
        "C002": ["A"],  # Wed 2026-09-09 (W37)
        "C003": ["P"],  # Mon 2026-09-14 (W38)
        "C004": ["P"],  # Mon 2026-10-05 (W41)
        "C005": ["A"],  # Wed 2026-10-07 (W41)
        "C006": ["P"],  # Mon 2026-10-12 (W42 - Reporting Week)
        "C007": ["P"],  # Wed 2026-10-14 (W42 - Reporting Week)
        "C008": ["P"],  # Tue 2026-10-20 (W43 - Future Class)
    }
    sch_data = {
        "class_id": ["C001", "C002", "C003", "C004", "C005", "C006", "C007", "C008"],
        "class_date": [
            "2026-09-07", "2026-09-09", "2026-09-14",
            "2026-10-05", "2026-10-07",
            "2026-10-12", "2026-10-14",
            "2026-10-20",
        ],
        "subject": [
            "Subj1", "Subj1", "Subj1",
            "Subj2", "Subj2",
            "Subj3", "Subj3",
            "Subj3",
        ],
    }
    return pd.DataFrame(att_data), pd.DataFrame(sch_data)


def test_get_week_range():
    """Verifies that get_week_range returns the correct Monday to Sunday window."""
    # 2026-10-15 is a Thursday
    dt = datetime.date(2026, 10, 15)
    monday, sunday = get_week_range(dt)
    assert monday == datetime.date(2026, 10, 12)
    assert sunday == datetime.date(2026, 10, 18)

    # If target is Monday itself
    dt_mon = datetime.date(2026, 10, 12)
    m2, s2 = get_week_range(dt_mon)
    assert m2 == datetime.date(2026, 10, 12)
    assert s2 == datetime.date(2026, 10, 18)

    # If target is Sunday itself
    dt_sun = datetime.date(2026, 10, 18)
    m3, s3 = get_week_range(dt_sun)
    assert m3 == datetime.date(2026, 10, 12)
    assert s3 == datetime.date(2026, 10, 18)


def test_calculate_student_attendance_metrics(multi_period_workbook):
    """Verifies weekly, monthly, and overall calculations with exact date boundaries."""
    df_att, df_sch = multi_period_workbook
    reporting_date = datetime.date(2026, 10, 15)

    data = validate_workbook(df_att, df_sch, reporting_date)
    summary = calculate_student_attendance(data, "S1001", reporting_date)

    # Future class C008 (2026-10-20) MUST BE EXCLUDED!
    # Total past classes up to 2026-10-15 = 7 classes (C001..C007)
    # Attended = C001(P), C003(P), C004(P), C006(P), C007(P) = 5
    # Missed = C002(A), C005(A) = 2
    # Overall percentage = (5 / 7) * 100 = 71.42857...%
    assert summary.overall.classes_held == 7
    assert summary.overall.classes_attended == 5
    assert summary.overall.classes_missed == 2
    assert pytest.approx(summary.overall.attendance_percentage, 0.01) == 71.43

    # Weekly stats for reporting week (Mon 2026-10-12 to Sun 2026-10-18 up to reporting_date 2026-10-15)
    # Classes in week W42: C006 (Mon Oct 12: P), C007 (Wed Oct 14: P) -> 2 held, 2 attended
    assert summary.weekly.classes_held == 2
    assert summary.weekly.classes_attended == 2
    assert summary.weekly.classes_missed == 0
    assert summary.weekly.attendance_percentage == 100.0

    # Monthly stats for October 2026 (up to Oct 15)
    # October classes: C004 (Oct 5: P), C005 (Oct 7: A), C006 (Oct 12: P), C007 (Oct 14: P)
    # 4 held, 3 attended, 1 missed -> (3/4)*100 = 75.0%
    assert summary.monthly.classes_held == 4
    assert summary.monthly.classes_attended == 3
    assert summary.monthly.classes_missed == 1
    assert summary.monthly.attendance_percentage == 75.0


def test_future_class_excluded(multi_period_workbook):
    """Verifies that future classes do not affect attendance totals even if marked P."""
    df_att, df_sch = multi_period_workbook
    # C008 is dated 2026-10-20 (future). Set mark to 'P'
    df_att["C008"] = ["P"]
    reporting_date = datetime.date(2026, 10, 15)

    data = validate_workbook(df_att, df_sch, reporting_date)
    summary = calculate_student_attendance(data, "S1001", reporting_date)

    # C008 should still be excluded because class_date (2026-10-20) > reporting_date (2026-10-15)
    assert summary.overall.classes_held == 7
    assert summary.overall.classes_attended == 5


def test_zero_classes_in_period(multi_period_workbook):
    """Verifies zero-division prevention when a reporting week has no classes held."""
    df_att, df_sch = multi_period_workbook
    # Reporting date on a week with no classes held (e.g., Nov 1, 2026)
    reporting_date = datetime.date(2026, 11, 1)

    data = validate_workbook(df_att, df_sch, reporting_date)
    summary = calculate_student_attendance(data, "S1001", reporting_date)

    # Week of Nov 1, 2026 (W44) has 0 classes held
    assert summary.weekly.classes_held == 0
    assert summary.weekly.classes_attended == 0
    assert summary.weekly.classes_missed == 0
    assert summary.weekly.attendance_percentage is None
    assert summary.weekly.has_data is False


def test_unequal_classes_across_weeks(multi_period_workbook):
    """Verifies stats when different weeks have unequal number of scheduled classes."""
    df_att, df_sch = multi_period_workbook

    # Reporting date during Week 37 (Sept 7 - Sept 13): 2 classes held
    data_w37 = validate_workbook(df_att, df_sch, datetime.date(2026, 9, 13))
    sum_w37 = calculate_student_attendance(data_w37, "S1001", datetime.date(2026, 9, 13))
    assert sum_w37.weekly.classes_held == 2
    assert sum_w37.weekly.attendance_percentage == 50.0

    # Reporting date during Week 38 (Sept 14 - Sept 20): 1 class held
    data_w38 = validate_workbook(df_att, df_sch, datetime.date(2026, 9, 20))
    sum_w38 = calculate_student_attendance(data_w38, "S1001", datetime.date(2026, 9, 20))
    assert sum_w38.weekly.classes_held == 1
    assert sum_w38.weekly.attendance_percentage == 100.0
