"""Attendance calculation logic for AttendEase."""

from dataclasses import dataclass
import datetime
import logging
from typing import Dict, List, Optional, Tuple
from attendease.validator import ValidatedData, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class PeriodAttendance:
    """Summary of attendance statistics for a specific period."""
    period_name: str
    start_date: datetime.date
    end_date: datetime.date
    classes_held: int
    classes_attended: int
    classes_missed: int
    attendance_percentage: Optional[float]  # None if classes_held == 0

    @property
    def has_data(self) -> bool:
        """Returns True if at least one class was held in this period."""
        return self.classes_held > 0


@dataclass
class StudentAttendanceSummary:
    """Complete attendance summary for a student up to a given reporting date."""
    student_id: str
    name: str
    email: str
    reporting_date: datetime.date
    weekly: PeriodAttendance
    monthly: PeriodAttendance
    overall: PeriodAttendance


def get_week_range(target_date: datetime.date) -> Tuple[datetime.date, datetime.date]:
    """Calculates the Monday-to-Sunday date range containing target_date.

    Args:
        target_date: The date to calculate week range for.

    Returns:
        Tuple of (monday_date, sunday_date).
    """
    # weekday(): 0 = Monday, 6 = Sunday
    monday = target_date - datetime.timedelta(days=target_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def calculate_period_metrics(
    class_records: List[Tuple[datetime.date, str]],
    start_date: datetime.date,
    end_date: datetime.date,
    reporting_date: datetime.date,
    period_name: str
) -> PeriodAttendance:
    """Calculates attendance metrics for classes falling within [start_date, min(end_date, reporting_date)].

    Args:
        class_records: List of tuples (class_date, mark) for a student.
        start_date: Period start date (inclusive).
        end_date: Period end date (inclusive).
        reporting_date: Cutoff date. Future classes (> reporting_date) are excluded.
        period_name: Name of the period (e.g. 'Weekly', 'Monthly', 'Overall').

    Returns:
        PeriodAttendance dataclass with calculated metrics.
    """
    # Effective cutoff end_date cannot exceed reporting_date
    effective_end = min(end_date, reporting_date)

    held = 0
    attended = 0
    missed = 0

    for cdate, mark in class_records:
        # Exclude future classes (class_date > reporting_date)
        if cdate > reporting_date:
            continue

        if start_date <= cdate <= effective_end:
            held += 1
            if mark == "P":
                attended += 1
            elif mark == "A":
                missed += 1

    if held == 0:
        percentage = None
    else:
        percentage = (attended / held) * 100.0

    return PeriodAttendance(
        period_name=period_name,
        start_date=start_date,
        end_date=effective_end,
        classes_held=held,
        classes_attended=attended,
        classes_missed=missed,
        attendance_percentage=percentage,
    )


def calculate_student_attendance(
    data: ValidatedData,
    student_id: str,
    reporting_date: datetime.date
) -> StudentAttendanceSummary:
    """Computes weekly, monthly, and overall attendance stats for a student.

    Args:
        data: ValidatedData returned from validator.
        student_id: Target student ID.
        reporting_date: Date as of which attendance is evaluated.

    Returns:
        StudentAttendanceSummary object.

    Raises:
        ValidationError: If student_id is not found in attendance records.
    """
    df_att = data.df_attendance
    row_matches = df_att[df_att["student_id"] == student_id]

    if row_matches.empty:
        raise ValidationError(f"Student ID '{student_id}' not found in attendance records.")

    student_row = row_matches.iloc[0]
    student_name = str(student_row["name"])
    student_email = str(student_row["email"])

    # Extract all class records (class_date, mark) for this student
    class_records: List[Tuple[datetime.date, str]] = []
    for cid, cdate in data.schedule_map.items():
        mark = str(student_row[cid])
        class_records.append((cdate, mark))

    # 1. Weekly range (Monday to Sunday containing reporting_date)
    week_start, week_end = get_week_range(reporting_date)
    weekly_stats = calculate_period_metrics(
        class_records=class_records,
        start_date=week_start,
        end_date=week_end,
        reporting_date=reporting_date,
        period_name="Weekly"
    )

    # 2. Monthly range (1st day to last day of reporting_date month)
    month_start = datetime.date(reporting_date.year, reporting_date.month, 1)
    if reporting_date.month == 12:
        month_end = datetime.date(reporting_date.year, 12, 31)
    else:
        next_month = datetime.date(reporting_date.year, reporting_date.month + 1, 1)
        month_end = next_month - datetime.timedelta(days=1)

    monthly_stats = calculate_period_metrics(
        class_records=class_records,
        start_date=month_start,
        end_date=month_end,
        reporting_date=reporting_date,
        period_name="Monthly"
    )

    # 3. Overall range (Earliest class date to reporting_date)
    all_dates = list(data.schedule_map.values())
    earliest_date = min(all_dates) if all_dates else reporting_date
    overall_start = min(earliest_date, reporting_date)

    overall_stats = calculate_period_metrics(
        class_records=class_records,
        start_date=overall_start,
        end_date=reporting_date,
        reporting_date=reporting_date,
        period_name="Overall"
    )

    return StudentAttendanceSummary(
        student_id=student_id,
        name=student_name,
        email=student_email,
        reporting_date=reporting_date,
        weekly=weekly_stats,
        monthly=monthly_stats,
        overall=overall_stats,
    )
