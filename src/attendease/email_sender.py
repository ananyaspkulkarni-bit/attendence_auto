"""Secure email generation and delivery module for AttendEase reports."""

from email.message import EmailMessage
import logging
from pathlib import Path
import re
import socket
import ssl
import smtplib
from typing import Dict, Optional, Tuple, Union

from attendease.attendance import StudentAttendanceSummary, PeriodAttendance
from attendease.config import (
    ATTENDANCE_THRESHOLD,
    DB_PATH,
    DRY_RUN,
    SENDER_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    TEST_RECIPIENT_EMAIL,
)
from attendease.history import (
    generate_report_key,
    start_delivery_attempt,
    record_delivery_success,
    record_delivery_failure,
    DuplicateSendError,
    DatabaseAccessError,
)
from attendease.validator import AttendanceError, ValidationError, EMAIL_REGEX

logger = logging.getLogger(__name__)


class EmailError(AttendanceError):
    """Base exception for email module errors."""
    pass


class RecipientSafetyError(EmailError):
    """Raised when a recipient email fails safety checks or target mismatch occurs."""
    pass


class SMTPConfigError(EmailError):
    """Raised when required SMTP configuration is missing or invalid."""
    pass


class EmailSendError(EmailError):
    """Raised when email delivery via SMTP fails."""
    pass


def validate_email_syntax(email_str: str) -> str:
    """Validates email syntax using regex pattern.

    Args:
        email_str: Email address string to validate.

    Returns:
        Stripped valid email string.

    Raises:
        ValidationError: If email syntax is invalid.
    """
    clean_email = email_str.strip() if email_str else ""
    if not clean_email or not EMAIL_REGEX.match(clean_email):
        raise ValidationError(f"Invalid email address syntax: '{email_str}'")
    return clean_email


def format_period_email_line(period: PeriodAttendance) -> str:
    """Formats period statistics for plain-text email representation."""
    if not period.has_data:
        return "No classes held in this period (N/A)"
    
    pct_str = f"{period.attendance_percentage:.2f}%" if period.attendance_percentage is not None else "N/A"
    return (
        f"{pct_str} ({period.classes_attended}/{period.classes_held} attended, "
        f"{period.classes_missed} missed)"
    )


def build_email_message(
    summary: StudentAttendanceSummary,
    recipient_email: str,
    sender_email: str,
    threshold: float = ATTENDANCE_THRESHOLD
) -> EmailMessage:
    """Builds a personalized plain-text EmailMessage object.

    Args:
        summary: StudentAttendanceSummary containing calculated attendance metrics.
        recipient_email: Destination recipient address.
        sender_email: Origin sender address.
        threshold: Target attendance percentage threshold.

    Returns:
        Configured EmailMessage object.
    """
    clean_recipient = validate_email_syntax(recipient_email)
    clean_sender = validate_email_syntax(sender_email)

    overall_pct = summary.overall.attendance_percentage
    is_warning = (overall_pct is not None) and (overall_pct < threshold)

    subject = f"Attendance Report: {summary.name} ({summary.student_id}) - {summary.reporting_date.strftime('%Y-%m-%d')}"

    body_lines = [
        "================================================================================",
        "                         ATTENDEASE REPORT PREVIEW                              ",
        "================================================================================",
        f"Student Name   : {summary.name}",
        f"Student ID     : {summary.student_id}",
        f"Student Email  : {summary.email}",
        f"Reporting Date : {summary.reporting_date.strftime('%Y-%m-%d')}",
        "--------------------------------------------------------------------------------",
        "ATTENDANCE SUMMARY",
        "--------------------------------------------------------------------------------",
        f"• Weekly Attendance  ({summary.weekly.start_date} to {summary.weekly.end_date}):",
        f"  {format_period_email_line(summary.weekly)}",
        f"• Monthly Attendance ({summary.monthly.start_date.strftime('%B %Y')}):",
        f"  {format_period_email_line(summary.monthly)}",
        f"• Overall Attendance (Up to {summary.reporting_date}):",
        f"  {format_period_email_line(summary.overall)}",
        "--------------------------------------------------------------------------------",
    ]

    if is_warning:
        body_lines.extend([
            "WARNING: OVERALL ATTENDANCE IS BELOW THE REQUIRED TARGET!",
            f"   Current Overall: {overall_pct:.2f}% | Required Minimum: {threshold:.2f}%",
            "   Action Recommended: Please contact your academic advisor or course instructor.",
            "--------------------------------------------------------------------------------",
        ])
    else:
        body_lines.extend([
            "STATUS: Good Standing",
            f"   Current Overall: {overall_pct:.2f}% | Target Minimum: {threshold:.2f}%",
            "--------------------------------------------------------------------------------",
        ])

    body_lines.extend([
        "DISCLAIMER:",
        "This report is an automated summary based on supplied attendance data and is not an",
        "official college attendance record.",
        "================================================================================",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = clean_sender
    msg["To"] = clean_recipient
    msg.set_content("\n".join(body_lines))

    return msg


def validate_recipient_safety(
    recipient: str,
    allowed_test_recipient: Optional[str] = None
) -> str:
    """Enforces safety policy: only allow sending to configured test recipient in Stage 2.

    Args:
        recipient: Target recipient email.
        allowed_test_recipient: Expected test recipient email (defaults to config).

    Returns:
        Validated recipient email string.

    Raises:
        RecipientSafetyError: If recipient does not match allowed test recipient.
    """
    clean_target = validate_email_syntax(recipient)
    configured = allowed_test_recipient or TEST_RECIPIENT_EMAIL
    
    if not configured:
        raise RecipientSafetyError("TEST_RECIPIENT_EMAIL is not configured in environment settings.")

    clean_configured = validate_email_syntax(configured)

    if clean_target.lower() != clean_configured.lower():
        raise RecipientSafetyError(
            f"Recipient safety violation: Targeted recipient '{clean_target}' does not match "
            f"configured test recipient '{clean_configured}'. Multi-student / bulk sending is disabled in Stage 2."
        )

    return clean_target


def validate_smtp_config(
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    sender: Optional[str] = None,
) -> Tuple[str, int, str, str, str]:
    """Validates SMTP connection configuration values for real email sending.

    Returns:
        Tuple of (host, port, username, password, sender).

    Raises:
        SMTPConfigError: If required SMTP credentials or server options are missing.
    """
    cfg_host = (host or SMTP_HOST).strip()
    cfg_port = port if port is not None else SMTP_PORT
    cfg_user = (username or SMTP_USERNAME).strip()
    cfg_pass = password if password is not None else SMTP_PASSWORD
    cfg_sender = (sender or SENDER_EMAIL).strip()

    missing = []
    if not cfg_host:
        missing.append("SMTP_HOST")
    if not cfg_user:
        missing.append("SMTP_USERNAME")
    if not cfg_pass:
        missing.append("SMTP_PASSWORD")
    if not cfg_sender:
        missing.append("SENDER_EMAIL")

    if missing:
        raise SMTPConfigError(
            f"Missing required SMTP configuration setting(s) for real send: {', '.join(missing)}"
        )

    validate_email_syntax(cfg_sender)
    return cfg_host, cfg_port, cfg_user, cfg_pass, cfg_sender


def send_email_report(
    summary: StudentAttendanceSummary,
    recipient_email: str,
    sender_email: Optional[str] = None,
    dry_run: bool = DRY_RUN,
    allow_resend: bool = False,
    db_path: Optional[Union[str, Path]] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
    test_recipient_email: Optional[str] = None,
) -> Tuple[bool, str]:
    """Handles report email preview or SMTP delivery.

    Args:
        summary: StudentAttendanceSummary metrics object.
        recipient_email: Destination recipient address.
        sender_email: Origin sender address (defaults to config).
        dry_run: If True, previews email locally without SMTP connection.
        allow_resend: If True, bypasses duplicate check.
        db_path: SQLite database path override.
        smtp_host: SMTP server hostname override.
        smtp_port: SMTP server port override.
        smtp_username: SMTP username override.
        smtp_password: SMTP password override.
        test_recipient_email: Test recipient safety override.

    Returns:
        Tuple of (success_boolean, status_message).
    """
    effective_sender = sender_email or SENDER_EMAIL or "attendease@example.com"

    # DRY RUN MODE
    if dry_run:
        msg = build_email_message(summary, recipient_email, effective_sender)
        preview_output = [
            "================================================================================",
            "                        DRY RUN — EMAIL REPORT PREVIEW                          ",
            "================================================================================",
            f"FROM    : {msg['From']}",
            f"TO      : {msg['To']}",
            f"SUBJECT : {msg['Subject']}",
            "--------------------------------------------------------------------------------",
            msg.get_content(),
            "================================================================================",
            "[DRY-RUN MODE ACTIVE] No SMTP connection established. No email sent.",
        ]
        preview_text = "\n".join(preview_output)
        print("\n" + preview_text + "\n")
        logger.info("Dry-run email preview generated successfully.")
        return True, "Dry-run preview generated successfully. No email sent."

    # REAL SEND MODE
    # 1. Enforce Recipient Safety Policy
    clean_recipient = validate_recipient_safety(recipient_email, test_recipient_email)

    # 2. Validate SMTP Credentials & Server Config
    host, port, user, pwd, sender = validate_smtp_config(
        host=smtp_host,
        port=smtp_port,
        username=smtp_username,
        password=smtp_password,
        sender=sender_email,
    )

    # 3. Check Delivery History and Register Delivery Attempt
    target_db = Path(db_path) if db_path else DB_PATH
    report_key = generate_report_key(summary.student_id, summary.reporting_date)
    date_str = summary.reporting_date.strftime("%Y-%m-%d")

    delivery_id = start_delivery_attempt(
        report_key=report_key,
        student_id=summary.student_id,
        reporting_date=date_str,
        recipient=clean_recipient,
        report_type="attendance_summary",
        allow_resend=allow_resend,
        db_path=target_db,
    )

    # 4. Build Email Message
    msg = build_email_message(summary, clean_recipient, sender)

    # 5. Connect over TLS and send email
    ssl_context = ssl.create_default_context()
    logger.info(f"Connecting to SMTP server {host}:{port} via TLS...")

    try:
        if port == 465:
            # Implicit TLS connection
            with smtplib.SMTP_SSL(host, port, context=ssl_context, timeout=15) as server:
                server.login(user, pwd)
                server.send_message(msg)
        else:
            # STARTTLS connection (typically port 587 or 25)
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ssl_context)
                server.ehlo()
                server.login(user, pwd)
                server.send_message(msg)

        record_delivery_success(delivery_id, db_path=target_db)

        success_msg = (
            f"Email accepted by SMTP server '{host}:{port}' for recipient '{clean_recipient}'. "
            "Note: Acceptance does not guarantee final inbox delivery."
        )
        logger.info(success_msg)
        return True, success_msg

    except smtplib.SMTPAuthenticationError as exc:
        err_msg = f"SMTP Authentication failed: {exc.smtp_error.decode('utf-8', errors='ignore') if isinstance(exc.smtp_error, bytes) else exc.smtp_error}"
        logger.error(err_msg)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc

    except smtplib.SMTPRecipientsRefused as exc:
        err_msg = f"SMTP Recipient refused: {exc.recipients}"
        logger.error(err_msg)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc

    except (socket.timeout, TimeoutError) as exc:
        err_msg = f"SMTP connection timed out connecting to {host}:{port}."
        logger.error(err_msg)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc

    except ssl.SSLError as exc:
        err_msg = f"TLS/SSL Certificate Verification Error connecting to {host}:{port}: {exc}"
        logger.error(err_msg)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc

    except smtplib.SMTPException as exc:
        err_msg = f"SMTP Protocol Error: {exc}"
        logger.error(err_msg)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc

    except Exception as exc:
        err_msg = f"Unexpected error during email delivery: {exc}"
        logger.error(err_msg, exc_info=True)
        record_delivery_failure(delivery_id, err_msg, db_path=target_db)
        raise EmailSendError(err_msg) from exc
