"""CLI entry-point for AttendEase attendance reporting and email dispatch."""

import argparse
import datetime
import logging
import sys
from pathlib import Path

from attendease.config import (
    ATTENDANCE_THRESHOLD,
    DB_PATH,
    DRY_RUN,
    EXCEL_PATH,
    LOG_LEVEL,
    REPORT_OUTPUT_DIR,
    SENDER_EMAIL,
    TEST_RECIPIENT_EMAIL,
    ConfigError,
    validate_config,
)
from attendease.excel_reader import load_workbook
from attendease.validator import validate_workbook, AttendanceError
from attendease.attendance import calculate_student_attendance
from attendease.report import generate_report_markdown, save_report_to_file
from attendease.email_sender import send_email_report, EmailError, validate_recipient_safety
from attendease.history import (
    DatabaseAccessError,
    DuplicateSendError,
    generate_report_key,
    get_delivery_history,
    get_last_successful_delivery,
    is_report_sent,
)


def setup_logging(level_name: str = "INFO") -> None:
    """Configures root logger."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def handle_history_command(target_db: Path, student_id: str = None) -> None:
    """Prints recent delivery history records and exits."""
    try:
        records = get_delivery_history(student_id=student_id, db_path=target_db)
        if not records:
            print("\nNo delivery history records found.")
        else:
            print("\n================================================================================")
            print("                        ATTENDEASE DELIVERY HISTORY                             ")
            print("================================================================================")
            print(f"{'ID':<5} {'Date':<11} {'Student ID':<11} {'Recipient':<26} {'Status':<11} {'Created At'}")
            print("-" * 80)
            for r in records:
                err_str = f" ({r.error_summary})" if r.error_summary else ""
                print(f"{r.id:<5} {r.reporting_date:<11} {r.student_id:<11} {r.recipient:<26} {r.status:<11} {r.created_at}{err_str}")
            print("================================================================================\n")
        sys.exit(0)
    except Exception as exc:
        print(f"\n❌ ERROR: Failed to read delivery history: {exc}", file=sys.stderr)
        sys.exit(1)


def handle_check_sent_command(target_db: Path, student_id: str, date_str: str) -> None:
    """Checks whether a report was already sent and exits."""
    try:
        reporting_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"\n❌ ERROR: Invalid date format '{date_str}'. Expected YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    clean_student_id = student_id or "S1001"
    key = generate_report_key(clean_student_id, reporting_date)
    print(f"\nChecking delivery history for report key: '{key}'...")

    try:
        record = get_last_successful_delivery(key, db_path=target_db)
        if record:
            print(f"✅ STATUS    : ALREADY SENT")
            print(f"   Report Key: {record.report_key}")
            print(f"   Recipient : {record.recipient}")
            print(f"   Sent At   : {record.created_at}")
        else:
            print(f"ℹ️ STATUS    : NOT SENT YET")
            print(f"   Report Key: {key}")
        sys.exit(0)
    except Exception as exc:
        print(f"\n❌ ERROR: Failed to query delivery status: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main execution entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 1. Startup Configuration Validation
    try:
        validate_config()
    except ConfigError as cfg_err:
        print(f"\n❌ CONFIGURATION ERROR: {cfg_err}", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="AttendEase — Attendance Reporting Automation & Email Dispatch")
    parser.add_argument(
        "--excel", "-e",
        type=str,
        default=str(EXCEL_PATH),
        help=f"Path to attendance Excel workbook (default: {EXCEL_PATH})"
    )
    parser.add_argument(
        "--student-id", "-s",
        type=str,
        default=None,
        help="Target student ID (defaults to first student found)"
    )
    parser.add_argument(
        "--date", "-d",
        type=str,
        default="2026-10-15",
        help="Reporting date in YYYY-MM-DD format (default: 2026-10-15)"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=ATTENDANCE_THRESHOLD,
        help=f"Minimum attendance target percentage (default: {ATTENDANCE_THRESHOLD})"
    )
    parser.add_argument(
        "--validate-only", "--validate",
        dest="validate_only",
        action="store_true",
        default=False,
        help="Validate workbook schema and integrity without generating reports or sending email"
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        default=False,
        help="Preview attendance report in terminal without saving to file or sending email"
    )
    parser.add_argument(
        "--send", "--no-dry-run",
        dest="send_real_email",
        action="store_true",
        default=False,
        help="Attempt real email delivery over SMTP (disables dry-run mode)"
    )
    parser.add_argument(
        "--recipient", "-r",
        type=str,
        default=None,
        help=f"Target test recipient email address (defaults to TEST_RECIPIENT_EMAIL: '{TEST_RECIPIENT_EMAIL}')"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        help="Bypass interactive confirmation prompt for real email sending"
    )
    parser.add_argument(
        "--resend", "--force-resend",
        dest="allow_resend",
        action="store_true",
        default=False,
        help="Explicitly authorize resending a report that was previously delivered successfully"
    )
    parser.add_argument(
        "--history",
        action="store_true",
        default=False,
        help="View recent delivery history records and exit"
    )
    parser.add_argument(
        "--check-sent",
        action="store_true",
        default=False,
        help="Check whether the specified report has already been delivered and exit"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DB_PATH),
        help=f"Path to SQLite delivery history database (default: {DB_PATH})"
    )

    args = parser.parse_args()

    # Validate CLI threshold range if provided
    if args.threshold < 0.0 or args.threshold > 100.0:
        print(f"\n❌ CONFIGURATION ERROR: Threshold must be between 0.0 and 100.0, got {args.threshold}", file=sys.stderr)
        sys.exit(1)

    setup_logging(LOG_LEVEL)
    logger = logging.getLogger(__name__)
    target_db = Path(args.db_path)

    # Handle standalone history subcommands
    if args.history:
        handle_history_command(target_db, student_id=args.student_id)

    if args.check_sent:
        handle_check_sent_command(target_db, student_id=args.student_id, date_str=args.date)

    try:
        reporting_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid date format '{args.date}'. Expected YYYY-MM-DD.")
        print(f"\n❌ CONFIGURATION ERROR: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading workbook: {args.excel}")
    try:
        df_att, df_sch = load_workbook(args.excel)
        validated_data = validate_workbook(df_att, df_sch, reporting_date)
    except AttendanceError as err:
        logger.error(f"Workbook validation failed: {err}")
        print(f"\n❌ VALIDATION ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Unexpected error loading workbook: {exc}", exc_info=True)
        print(f"\n❌ FILE ERROR: Could not read workbook '{args.excel}': {exc}", file=sys.stderr)
        sys.exit(1)

    if args.validate_only:
        num_students = len(validated_data.df_attendance)
        num_classes = len(validated_data.schedule_map)
        print("\n================================================================================")
        print("                        ✅ WORKBOOK VALIDATION SUCCESSFUL                       ")
        print("================================================================================")
        print(f"Workbook Path     : {args.excel}")
        print(f"Reporting Date    : {reporting_date}")
        print(f"Total Students    : {num_students}")
        print(f"Scheduled Classes : {num_classes}")
        print("================================================================================\n")
        sys.exit(0)

    # Determine target student ID
    if args.student_id:
        target_student_id = args.student_id
    else:
        target_student_id = validated_data.df_attendance["student_id"].iloc[0]

    print(f"Generating attendance summary for student ID: {target_student_id} as of {reporting_date}...")

    try:
        summary = calculate_student_attendance(validated_data, target_student_id, reporting_date)
        report_markdown = generate_report_markdown(summary, threshold=args.threshold)
        
        if args.preview_only:
            print("\n" + report_markdown + "\n")
            sys.exit(0)

        # Save preview report to local file
        report_path = save_report_to_file(report_markdown, target_student_id, REPORT_OUTPUT_DIR)
        print(f"Report preview saved to: {report_path}")

    except Exception as exc:
        logger.error(f"Failed to calculate attendance or generate report: {exc}", exc_info=True)
        print(f"\n❌ REPORT ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Determine dry-run status
    if args.send_real_email:
        is_dry_run = False
    else:
        is_dry_run = DRY_RUN

    # Determine recipient
    recipient = args.recipient or TEST_RECIPIENT_EMAIL or summary.email

    if is_dry_run:
        # Dry-run execution
        send_email_report(summary, recipient_email=recipient, dry_run=True, db_path=target_db)
    else:
        # Real send execution requested
        report_key = generate_report_key(summary.student_id, summary.reporting_date)
        print("\n================================================================================")
        print("                        ⚠️ REAL EMAIL SEND REQUESTED                             ")
        print("================================================================================")
        print(f"Target Student ID   : {summary.student_id} ({summary.name})")
        print(f"Report Key          : {report_key}")
        print(f"Test Recipient      : {recipient}")
        print(f"Sender Email        : {SENDER_EMAIL}")
        print("--------------------------------------------------------------------------------")

        # 1. Recipient Safety Check
        try:
            validate_recipient_safety(recipient)
        except EmailError as err:
            logger.error(f"Recipient safety validation failed: {err}")
            print(f"\n❌ SAFETY REJECTION: {err}", file=sys.stderr)
            sys.exit(1)

        # 2. Check Duplicate-Send Rules & Delivery History
        try:
            prev_record = get_last_successful_delivery(report_key, db_path=target_db)
            if prev_record and not args.allow_resend:
                print(
                    f"\n❌ DUPLICATE SEND BLOCKED: Report '{report_key}' was already successfully sent to "
                    f"'{prev_record.recipient}' on {prev_record.created_at}.",
                    file=sys.stderr
                )
                print("Use --resend to explicitly authorize resending this report.", file=sys.stderr)
                sys.exit(1)
            elif prev_record and args.allow_resend:
                print(
                    f"\n⚠️ WARNING: EXPLICIT RESEND OVERRIDE ACTIVE!\n"
                    f"Report '{report_key}' was previously delivered on {prev_record.created_at}.\n"
                    f"Proceeding with explicit manual resend..."
                )
        except DatabaseAccessError as err:
            logger.error(f"Database delivery check failed: {err}")
            print(f"\n❌ DATABASE ERROR: Delivery history check failed: {err}", file=sys.stderr)
            print("Real email send aborted because delivery history could not be verified.", file=sys.stderr)
            sys.exit(1)

        # 3. Interactive Confirmation Check
        if not args.yes:
            if not sys.stdin.isatty():
                print(
                    "\n❌ CONFIRMATION ABORTED: Non-interactive terminal session detected. "
                    "Use --yes to confirm real email sending in scripted environments.",
                    file=sys.stderr
                )
                sys.exit(1)

            prompt_msg = f"Are you sure you want to send a real email to '{recipient}'? (y/N): "
            if prev_record and args.allow_resend:
                prompt_msg = f"Report ALREADY SENT previously! Are you SURE you want to RESEND to '{recipient}'? (y/N): "

            answer = input(prompt_msg).strip().lower()
            if answer not in ("y", "yes"):
                print("Real email send cancelled by user.")
                sys.exit(0)

        # 4. Attempt Real Email Delivery
        try:
            success, msg = send_email_report(
                summary,
                recipient_email=recipient,
                dry_run=False,
                allow_resend=args.allow_resend,
                db_path=target_db,
            )
            print(f"\n✅ SUCCESS: {msg}")
        except DuplicateSendError as err:
            logger.error(f"Duplicate send blocked: {err}")
            print(f"\n❌ DUPLICATE SEND BLOCKED: {err}", file=sys.stderr)
            sys.exit(1)
        except EmailError as err:
            logger.error(f"Real email delivery failed: {err}")
            print(f"\n❌ DELIVERY FAILURE: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            logger.error(f"Unexpected delivery error: {exc}", exc_info=True)
            print(f"\n❌ SYSTEM ERROR: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
