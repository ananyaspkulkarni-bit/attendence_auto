# AttendEase Testing Strategy & Test Suite Documentation

## 1. Testing Philosophy & Design Principles

The **AttendEase** test suite is built around three fundamental quality assurance guarantees:

1. **Zero Real Email Dispatches**: Network connections to SMTP servers are 100% mocked using Python's `unittest.mock.patch`. Running `pytest` will **never** attempt a real network connection or dispatch real emails.
2. **Database Isolation**: All tests involving SQLite delivery history use temporary, isolated database files managed by `pytest`'s `tmp_path` fixture. Production database files (`data/delivery_history.db`) are never touched or modified during test execution.
3. **Comprehensive Edge-Case Coverage**: The test suite covers schema errors, data corruption, date cutoffs, boundary cases, recipient safety violations, network failures, database errors, and real-world Excel formatting anomalies.

---

## 2. Test Suite Architecture & Summary

The test suite consists of **74 automated unit and integration tests** distributed across 8 test modules:

```
tests/
├── test_attendance.py       # (5 tests)  Attendance metrics, date boundaries & zero-division
├── test_validator.py        # (12 tests) Schema validation, 1-to-1 mapping & incomplete data
├── test_report.py           # (5 tests)  Markdown report formatting & disk persistence
├── test_email_sender.py     # (12 tests) MIME construction, recipient safety & TLS SMTP mocks
├── test_cli.py              # (4 tests)  CLI options, non-interactive aborts & safety guards
├── test_history.py          # (11 tests) Delivery history, duplicate prevention & transaction locks
├── test_e2e_real_world.py   # (14 tests) Real-world Excel fixtures & full E2E pipeline
└── test_config_and_cli.py   # (11 tests) Config validation, bounds checking & CLI flags
```

---

## 3. Module Test Coverage Breakdown

### `tests/test_attendance.py`
- `test_get_week_range`: Verifies Monday-to-Sunday date range calculation for any input date.
- `test_calculate_student_attendance_metrics`: Validates weekly, monthly, and overall percentage calculations.
- `test_future_class_excluded`: Ensures classes with `class_date > reporting_date` are strictly excluded.
- `test_zero_classes_in_period`: Verifies `classes_held == 0` returns `attendance_percentage = None` (N/A) rather than `0%`.
- `test_unequal_classes_across_weeks`: Tests attendance calculation when weeks contain different class counts.

### `tests/test_validator.py`
- Schema validation for required `Attendance` and `Class_Schedule` columns.
- Detection of duplicate `student_id` and duplicate `class_id` entries.
- Unmapped class columns (`C999`) and scheduled classes missing from attendance sheet.
- Invalid date format handling (`not-a-valid-date`).
- Malformed email address rejection.
- Invalid attendance mark detection (e.g. `'X'`).
- Incomplete data detection (`IncompleteDataError`) for past/current classes with blank marks.
- Permitted blank marks for future classes (`class_date > reporting_date`).

### `tests/test_report.py`
- Formatting period attendance display strings for regular and zero-class periods.
- Markdown report generation for Good Standing status.
- Warning banner insertion when overall attendance falls below `--threshold`.
- Saving generated markdown report text to local disk files (`reports/report_<student_id>.txt`).

### `tests/test_email_sender.py`
- `validate_email_syntax`: Regex validation for email strings.
- `build_email_message`: Verifies MIME subject headers, recipient/sender fields, and body text formatting.
- `validate_recipient_safety`: Restricts real dispatches strictly to `TEST_RECIPIENT_EMAIL`.
- `validate_smtp_config`: Raises `SMTPConfigError` when required server credentials are missing.
- `send_email_report` dry-run mode: Verifies zero SMTP connections are opened.
- `send_email_report` real send mode: Mocks `smtplib.SMTP` (STARTTLS) and `smtplib.SMTP_SSL` (Implicit TLS).
- Error handling for `SMTPAuthenticationError`, `socket.timeout`, and `ssl.SSLError`.

### `tests/test_cli.py`
- Default dry-run CLI execution.
- Student ID selection via `--student-id`.
- Non-interactive shell abort (`sys.stdin.isatty() == False`) when real send `--send` is attempted without `--yes`.
- Recipient safety rejection when target recipient differs from `TEST_RECIPIENT_EMAIL`.

### `tests/test_history.py`
- Deterministic report key generation: `<student_id>:<type>:<date>`.
- Creating and reading delivery records in SQLite.
- Detecting previously successful deliveries (`is_report_sent`).
- Blocking duplicate sends (`DuplicateSendError`).
- Resend override path (`allow_resend=True`).
- Verifying dry-run previews leave 0 records in delivery history.
- Verifying SMTP failures mark status as `FAILED` with error summary.
- Verifying database errors block real email delivery before SMTP call.
- Handling distinct student IDs and reporting periods independently.
- Testing CLI `--history` and `--check-sent` subcommands.

### `tests/test_e2e_real_world.py`
- Real-world Excel fixtures:
  - Whitespace around headers (`" student_id "`) and lowercase marks (`" p "`) normalized cleanly.
  - Extra irrelevant non-class columns (`department`, `phone`, `instructor`, `room`) permitted and ignored.
  - Missing sheets, missing required columns, duplicate student IDs, unknown class columns (`C999`).
  - Invalid marks (`"Late"`), blank past marks, malformed emails, and invalid dates.
- Full End-to-End Pipeline test:
  1. Load physical Excel file from disk.
  2. Validate workbook schema & normalize marks.
  3. Calculate attendance metrics.
  4. Render preview & save local report file.
  5. Exercise dry-run mode.
  6. Exercise real send with mocked SMTP.
  7. Verify delivery history updated to `SUCCESS`.
  8. Verify second send attempt blocked as duplicate.
  9. Force resend with `--resend` and verify 2nd history record added.
- Invalid input safety test: Verifies invalid workbook input halts process before any SMTP network call.

### `tests/test_config_and_cli.py`
- `validate_config()` success and parsing helpers.
- Configuration errors for out-of-range thresholds (`ATTENDANCE_THRESHOLD = 150.0` or `"invalid"`).
- Invalid `SMTP_PORT` out of bounds (`999999`).
- Invalid `LOG_LEVEL` string (`"INVALID_LEVEL"`).
- CLI `--validate-only` flag execution.
- CLI `--preview-only` flag execution.
- Clear error handling for nonexistent workbook paths (`--excel nonexistent.xlsx`).
- Clear error handling for invalid date formats (`--date invalid-date`).
- Threshold CLI bounds checking (`--threshold 200.0`).
- Verifying dry-run report preview works with zero SMTP credentials configured.

---

## 4. How to Run the Test Suite

Run the full test suite using `pytest`:

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run all 74 tests with verbose output
python -m pytest -v
```

### Running Specific Test Modules
```powershell
python -m pytest tests/test_e2e_real_world.py -v
python -m pytest tests/test_history.py -v
python -m pytest tests/test_config_and_cli.py -v
```

### Running with Code Coverage (Optional)
If `pytest-cov` is installed:
```powershell
python -m pytest --cov=attendease --cov-report=term-missing
```
