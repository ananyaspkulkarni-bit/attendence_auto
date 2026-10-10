"""AttendEase — Attendance Reporting Automation Package."""

from attendease.excel_reader import load_workbook, ExcelReadError
from attendease.validator import validate_workbook, ValidationError, IncompleteDataError, ValidatedData
from attendease.attendance import calculate_student_attendance, StudentAttendanceSummary, PeriodAttendance
from attendease.report import generate_report_markdown, save_report_to_file
from attendease.config import (
    ATTENDANCE_THRESHOLD,
    EXCEL_PATH,
    REPORT_OUTPUT_DIR,
    DB_PATH,
    ConfigError,
    validate_config,
)
from attendease.history import (
    HistoryError,
    DuplicateSendError,
    DatabaseAccessError,
    DeliveryRecord,
    generate_report_key,
    init_db,
    is_report_sent,
    get_delivery_history,
)

__all__ = [
    "load_workbook",
    "ExcelReadError",
    "validate_workbook",
    "ValidationError",
    "IncompleteDataError",
    "ValidatedData",
    "calculate_student_attendance",
    "StudentAttendanceSummary",
    "PeriodAttendance",
    "generate_report_markdown",
    "save_report_to_file",
    "ATTENDANCE_THRESHOLD",
    "EXCEL_PATH",
    "REPORT_OUTPUT_DIR",
    "DB_PATH",
    "ConfigError",
    "validate_config",
    "HistoryError",
    "DuplicateSendError",
    "DatabaseAccessError",
    "DeliveryRecord",
    "generate_report_key",
    "init_db",
    "is_report_sent",
    "get_delivery_history",
]
