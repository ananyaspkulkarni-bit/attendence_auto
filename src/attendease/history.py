"""Persistent delivery history and duplicate-send prevention module for AttendEase."""

from dataclasses import dataclass
import datetime
import logging
from pathlib import Path
import sqlite3
from typing import List, Optional, Union

from attendease.validator import AttendanceError
from attendease.config import DB_PATH

logger = logging.getLogger(__name__)


class HistoryError(AttendanceError):
    """Base exception for delivery history database errors."""
    pass


class DuplicateSendError(HistoryError):
    """Raised when attempting to send a report that has already been successfully delivered."""
    pass


class DatabaseAccessError(HistoryError):
    """Raised when SQLite database cannot be accessed or is corrupted."""
    pass


@dataclass
class DeliveryRecord:
    """Represents a delivery attempt record in the database."""
    id: int
    report_key: str
    student_id: str
    report_type: str
    reporting_date: str
    recipient: str
    status: str  # 'SUCCESS', 'FAILED', 'IN_PROGRESS'
    error_summary: Optional[str]
    created_at: str
    updated_at: Optional[str] = None


def generate_report_key(
    student_id: str,
    reporting_date: Union[str, datetime.date, datetime.datetime],
    report_type: str = "attendance_summary",
) -> str:
    """Generates a deterministic unique report key.

    Format: <student_id>:<report_type>:<YYYY-MM-DD>

    Args:
        student_id: Unique identifier for the student.
        reporting_date: Date object or YYYY-MM-DD string.
        report_type: Type of report (default: 'attendance_summary').

    Returns:
        Formatted key string.
    """
    if isinstance(reporting_date, (datetime.date, datetime.datetime)):
        date_str = reporting_date.strftime("%Y-%m-%d")
    else:
        date_str = str(reporting_date).strip()
    clean_student = str(student_id).strip()
    clean_type = str(report_type).strip().lower()
    return f"{clean_student}:{clean_type}:{date_str}"


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """Opens a SQLite connection with WAL mode and busy timeout configured.

    Args:
        db_path: Path to SQLite database file.

    Returns:
        Configured sqlite3.Connection object.

    Raises:
        DatabaseAccessError: If database connection cannot be established.
    """
    try:
        target_path = Path(db_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn
    except sqlite3.Error as exc:
        logger.error(f"Failed to connect to database at {db_path}: {exc}")
        raise DatabaseAccessError(f"Database access error for '{db_path}': {exc}") from exc


def init_db(db_path: Path = DB_PATH) -> None:
    """Initializes delivery history database table and indexes.

    Args:
        db_path: Path to SQLite database file.

    Raises:
        DatabaseAccessError: If database table initialization fails.
    """
    try:
        with get_db_connection(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delivery_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_key TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    reporting_date TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_report_key ON delivery_history(report_key);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_student_id ON delivery_history(student_id);")
            conn.commit()
    except sqlite3.Error as exc:
        logger.error(f"Failed to initialize database schema: {exc}")
        raise DatabaseAccessError(f"Database schema initialization failed: {exc}") from exc


def is_report_sent(report_key: str, db_path: Path = DB_PATH) -> bool:
    """Checks whether a report key has already been successfully delivered.

    Args:
        report_key: Unique report identifier key.
        db_path: Path to SQLite database file.

    Returns:
        True if report was successfully delivered, False otherwise.

    Raises:
        DatabaseAccessError: If database query fails.
    """
    init_db(db_path)
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM delivery_history WHERE report_key = ? AND status = 'SUCCESS'",
                (report_key,)
            )
            count = cursor.fetchone()[0]
            return count > 0
    except sqlite3.Error as exc:
        logger.error(f"Failed to query delivery status for key '{report_key}': {exc}")
        raise DatabaseAccessError(f"Database error checking report status: {exc}") from exc


def get_last_successful_delivery(report_key: str, db_path: Path = DB_PATH) -> Optional[DeliveryRecord]:
    """Retrieves the most recent successful delivery record for a report key.

    Args:
        report_key: Unique report identifier key.
        db_path: Path to SQLite database file.

    Returns:
        DeliveryRecord if found, None otherwise.
    """
    init_db(db_path)
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, report_key, student_id, report_type, reporting_date, recipient, status, error_summary, created_at, updated_at
                FROM delivery_history
                WHERE report_key = ? AND status = 'SUCCESS'
                ORDER BY id DESC LIMIT 1
                """,
                (report_key,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return DeliveryRecord(
                id=row["id"],
                report_key=row["report_key"],
                student_id=row["student_id"],
                report_type=row["report_type"],
                reporting_date=row["reporting_date"],
                recipient=row["recipient"],
                status=row["status"],
                error_summary=row["error_summary"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    except sqlite3.Error as exc:
        logger.error(f"Failed to fetch last successful delivery for '{report_key}': {exc}")
        raise DatabaseAccessError(f"Database error fetching report history: {exc}") from exc


def get_delivery_history(
    student_id: Optional[str] = None,
    limit: int = 50,
    db_path: Path = DB_PATH
) -> List[DeliveryRecord]:
    """Retrieves recent delivery records.

    Args:
        student_id: Optional filter for student ID.
        limit: Max records to return (default: 50).
        db_path: Path to SQLite database file.

    Returns:
        List of DeliveryRecord objects sorted newest first.
    """
    init_db(db_path)
    records: List[DeliveryRecord] = []
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            if student_id:
                cursor.execute(
                    """
                    SELECT id, report_key, student_id, report_type, reporting_date, recipient, status, error_summary, created_at, updated_at
                    FROM delivery_history
                    WHERE student_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (student_id, limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, report_key, student_id, report_type, reporting_date, recipient, status, error_summary, created_at, updated_at
                    FROM delivery_history
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,)
                )
            for row in cursor.fetchall():
                records.append(
                    DeliveryRecord(
                        id=row["id"],
                        report_key=row["report_key"],
                        student_id=row["student_id"],
                        report_type=row["report_type"],
                        reporting_date=row["reporting_date"],
                        recipient=row["recipient"],
                        status=row["status"],
                        error_summary=row["error_summary"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
        return records
    except sqlite3.Error as exc:
        logger.error(f"Failed to fetch delivery history: {exc}")
        raise DatabaseAccessError(f"Database error fetching delivery history: {exc}") from exc


def start_delivery_attempt(
    report_key: str,
    student_id: str,
    reporting_date: str,
    recipient: str,
    report_type: str = "attendance_summary",
    allow_resend: bool = False,
    db_path: Path = DB_PATH,
) -> int:
    """Checks duplicate send rules and pre-registers an IN_PROGRESS delivery attempt.

    Args:
        report_key: Unique report identifier key.
        student_id: Student ID string.
        reporting_date: Reporting date string (YYYY-MM-DD).
        recipient: Destination recipient email address.
        report_type: Report type classification.
        allow_resend: If True, bypasses duplicate check.
        db_path: Path to SQLite database file.

    Returns:
        Integer delivery ID of created record.

    Raises:
        DuplicateSendError: If report was already sent and allow_resend is False, or if send in progress.
        DatabaseAccessError: If database read or write operation fails.
    """
    init_db(db_path)
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()

            # Check if successful delivery already exists
            if not allow_resend:
                cursor.execute(
                    """
                    SELECT recipient, created_at FROM delivery_history
                    WHERE report_key = ? AND status = 'SUCCESS'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (report_key,)
                )
                existing = cursor.fetchone()
                if existing:
                    prev_recipient = existing["recipient"]
                    prev_time = existing["created_at"]
                    raise DuplicateSendError(
                        f"Report '{report_key}' was already successfully sent to '{prev_recipient}' "
                        f"on {prev_time}. Use --resend to explicitly authorize resending."
                    )

            # Check for concurrent in-progress attempt
            cursor.execute(
                """
                SELECT id, created_at FROM delivery_history
                WHERE report_key = ? AND status = 'IN_PROGRESS'
                ORDER BY id DESC LIMIT 1
                """,
                (report_key,)
            )
            in_progress = cursor.fetchone()
            if in_progress:
                created_str = in_progress["created_at"]
                try:
                    dt_created = datetime.datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=datetime.timezone.utc)
                    age_seconds = (datetime.datetime.now(datetime.timezone.utc) - dt_created).total_seconds()
                except Exception:
                    age_seconds = 0

                if age_seconds < 300:
                    raise DuplicateSendError(
                        f"A delivery attempt for report '{report_key}' is currently in progress (started at {created_str})."
                    )

            # Insert new IN_PROGRESS attempt record
            cursor.execute(
                """
                INSERT INTO delivery_history
                (report_key, student_id, report_type, reporting_date, recipient, status, error_summary, created_at)
                VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', NULL, ?)
                """,
                (report_key, student_id, report_type, reporting_date, recipient, now_str)
            )
            delivery_id = cursor.lastrowid
            conn.commit()
            return delivery_id

    except DuplicateSendError:
        raise
    except sqlite3.Error as exc:
        logger.error(f"Database error during start_delivery_attempt for '{report_key}': {exc}")
        raise DatabaseAccessError(f"Database error starting delivery attempt: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def record_delivery_success(delivery_id: int, db_path: Path = DB_PATH) -> None:
    """Updates a delivery record status to SUCCESS.

    Args:
        delivery_id: ID of delivery record to update.
        db_path: Path to SQLite database file.

    Raises:
        DatabaseAccessError: If database update fails.
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        with get_db_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE delivery_history
                SET status = 'SUCCESS', updated_at = ?
                WHERE id = ?
                """,
                (now_str, delivery_id)
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error(f"Failed to record delivery success for record #{delivery_id}: {exc}")
        raise DatabaseAccessError(f"Database update failed recording delivery success: {exc}") from exc


def record_delivery_failure(delivery_id: int, error_summary: str, db_path: Path = DB_PATH) -> None:
    """Updates a delivery record status to FAILED with error summary.

    Args:
        delivery_id: ID of delivery record to update.
        error_summary: Minimal error description string.
        db_path: Path to SQLite database file.

    Raises:
        DatabaseAccessError: If database update fails.
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    clean_error = error_summary[:255] if error_summary else "Unknown error"
    try:
        with get_db_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE delivery_history
                SET status = 'FAILED', error_summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (clean_error, now_str, delivery_id)
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error(f"Failed to record delivery failure for record #{delivery_id}: {exc}")
        raise DatabaseAccessError(f"Database update failed recording delivery failure: {exc}") from exc
