"""Data validator for AttendEase workbook structures and values."""

from dataclasses import dataclass
import datetime
import logging
import re
from typing import Dict, List, Set, Tuple
import pandas as pd

logger = logging.getLogger(__name__)

# Basic plausible email regex pattern
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class AttendanceError(Exception):
    """Base exception for AttendEase domain errors."""
    pass


class ValidationError(AttendanceError):
    """Raised when data structure, values, schema or relationships fail validation."""
    pass


class IncompleteDataError(ValidationError):
    """Raised when completed/past classes have blank or missing attendance marks."""
    pass


@dataclass
class ValidatedData:
    """Container holding cleaned and validated attendance and schedule records."""
    df_attendance: pd.DataFrame
    schedule_map: Dict[str, datetime.date]  # class_id -> class_date
    subject_map: Dict[str, str]            # class_id -> subject


def validate_workbook(
    df_attendance: pd.DataFrame,
    df_schedule: pd.DataFrame,
    reporting_date: datetime.date
) -> ValidatedData:
    """Validates attendance and class schedule DataFrames against business rules.

    Args:
        df_attendance: Raw attendance DataFrame.
        df_schedule: Raw class schedule DataFrame.
        reporting_date: Target reporting date.

    Returns:
        ValidatedData containing cleaned DataFrames and date mappings.

    Raises:
        ValidationError: If schema, IDs, dates, email, or marks are invalid.
        IncompleteDataError: If any class on or before reporting_date has blank mark.
    """
    df_att = df_attendance.copy()
    df_sch = df_schedule.copy()

    # Normalize column names by stripping whitespace
    df_att.columns = [str(c).strip() for c in df_att.columns]
    df_sch.columns = [str(c).strip() for c in df_sch.columns]

    # 1. Validate required columns exist
    req_att_cols = {"student_id", "name", "email"}
    req_sch_cols = {"class_id", "class_date", "subject"}

    missing_att_cols = req_att_cols - set(df_att.columns)
    if missing_att_cols:
        raise ValidationError(
            f"Attendance sheet missing required columns: {sorted(missing_att_cols)}. Required columns: 'student_id', 'name', 'email'."
        )

    missing_sch_cols = req_sch_cols - set(df_sch.columns)
    if missing_sch_cols:
        raise ValidationError(
            f"Class_Schedule sheet missing required columns: {sorted(missing_sch_cols)}. Required columns: 'class_id', 'class_date', 'subject'."
        )

    # 2. Validate Student IDs present and unique
    seen_students: Set[str] = set()
    for idx, row in df_att.iterrows():
        raw_sid = row["student_id"]
        sid = str(raw_sid).strip() if pd.notna(raw_sid) else ""
        if not sid:
            raise ValidationError(
                f"Attendance sheet contains missing or blank student_id at row {idx + 2}."
            )
        if sid in seen_students:
            raise ValidationError(
                f"Duplicate student_id found in Attendance sheet: '{sid}' at row {idx + 2}."
            )
        seen_students.add(sid)
        df_att.at[idx, "student_id"] = sid

    # 3. Validate Student Emails and Names present and formatted
    for idx, row in df_att.iterrows():
        raw_email = row["email"]
        email = str(raw_email).strip() if pd.notna(raw_email) else ""
        if not email or not EMAIL_REGEX.match(email):
            raise ValidationError(
                f"Invalid or missing email '{raw_email}' for student ID '{df_att.at[idx, 'student_id']}' at row {idx + 2}."
            )
        df_att.at[idx, "email"] = email

        raw_name = row["name"]
        clean_name = str(raw_name).strip() if pd.notna(raw_name) else ""
        if not clean_name:
            raise ValidationError(
                f"Missing student name for student ID '{df_att.at[idx, 'student_id']}' at row {idx + 2}."
            )
        df_att.at[idx, "name"] = clean_name

    # 4. Validate Class IDs in Schedule present and unique
    seen_classes: Set[str] = set()
    for idx, row in df_sch.iterrows():
        raw_cid = row["class_id"]
        cid = str(raw_cid).strip() if pd.notna(raw_cid) else ""
        if not cid:
            raise ValidationError(
                f"Class_Schedule sheet contains missing or blank class_id at row {idx + 2}."
            )
        if cid in seen_classes:
            raise ValidationError(
                f"Duplicate class_id found in Class_Schedule sheet: '{cid}' at row {idx + 2}."
            )
        seen_classes.add(cid)
        df_sch.at[idx, "class_id"] = cid

    # 5. Parse and validate Class Dates and Subjects
    schedule_map: Dict[str, datetime.date] = {}
    subject_map: Dict[str, str] = {}

    for idx, row in df_sch.iterrows():
        cid = df_sch.at[idx, "class_id"]
        raw_date = row["class_date"]
        raw_subject = str(row["subject"]).strip() if pd.notna(row["subject"]) else ""

        if not raw_subject:
            raise ValidationError(
                f"Missing subject for class_id '{cid}' in Class_Schedule at row {idx + 2}."
            )

        try:
            parsed_dt = pd.to_datetime(raw_date, errors="raise")
            parsed_date = parsed_dt.date()
        except Exception as exc:
            raise ValidationError(
                f"Invalid date format '{raw_date}' for class_id '{cid}' in Class_Schedule at row {idx + 2}."
            ) from exc

        schedule_map[cid] = parsed_date
        subject_map[cid] = raw_subject

    # 6. Validate 1-to-1 Mapping between Schedule Class IDs and Attendance Class Columns
    scheduled_class_ids = set(df_sch["class_id"])
    all_att_cols = set(df_att.columns) - req_att_cols

    att_class_cols: Set[str] = set()
    extra_metadata_cols: Set[str] = set()

    class_id_pattern = re.compile(r"^(C\d+|CLASS_\d+|CLASS\d+|[A-Z]+\d+)$", re.IGNORECASE)

    for col in all_att_cols:
        if col in scheduled_class_ids:
            att_class_cols.add(col)
        elif class_id_pattern.match(col):
            att_class_cols.add(col)
        else:
            # Check if column values consist of attendance marks P/A/blank
            non_null_vals = df_att[col].dropna().astype(str).str.strip().str.upper()
            unique_vals = set(non_null_vals.unique())
            if unique_vals and unique_vals.issubset({"P", "A", ""}):
                att_class_cols.add(col)
            else:
                extra_metadata_cols.add(col)

    missing_in_schedule = att_class_cols - scheduled_class_ids
    if missing_in_schedule:
        raise ValidationError(
            f"Attendance columns exist without a corresponding schedule entry: {sorted(missing_in_schedule)}"
        )

    missing_in_attendance = scheduled_class_ids - att_class_cols
    if missing_in_attendance:
        raise ValidationError(
            f"Scheduled class IDs missing from Attendance sheet columns: {sorted(missing_in_attendance)}"
        )

    # 7. Normalize attendance marks & check for invalid/incomplete data
    for cid in sorted(att_class_cols):
        class_date = schedule_map[cid]
        is_past_or_current = class_date <= reporting_date

        for idx, row in df_att.iterrows():
            st_id = df_att.at[idx, "student_id"]
            raw_mark = row[cid]

            if pd.isna(raw_mark) or str(raw_mark).strip() == "":
                mark = ""
            else:
                mark = str(raw_mark).strip().upper()

            if mark not in {"P", "A", ""}:
                raise ValidationError(
                    f"Invalid attendance mark '{raw_mark}' for student '{st_id}' in class '{cid}' at row {idx + 2}."
                )

            if is_past_or_current and mark == "":
                raise IncompleteDataError(
                    f"Incomplete attendance data: Class '{cid}' (Date: {class_date}) on or before "
                    f"reporting date ({reporting_date}) has a blank mark for student '{st_id}'."
                )

            df_att.at[idx, cid] = mark

    logger.info("Workbook validation completed successfully.")
    return ValidatedData(
        df_attendance=df_att,
        schedule_map=schedule_map,
        subject_map=subject_map,
    )
