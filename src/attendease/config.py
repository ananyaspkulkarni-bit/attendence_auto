"""Configuration loader for AttendEase using python-dotenv and environment variables."""

import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

from attendease.validator import AttendanceError

# Load environment variables from .env if present
load_dotenv()

# Base directory of project
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class ConfigError(AttendanceError):
    """Raised when application configuration settings are invalid or missing."""
    pass


def parse_float_setting(key: str, default: str, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Parses and validates a numeric float environment setting.

    Args:
        key: Environment variable key name.
        default: Default string value if key is not set.
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).

    Returns:
        Validated float value.

    Raises:
        ConfigError: If value cannot be parsed as float or falls outside range.
    """
    val_str = os.getenv(key, default).strip()
    try:
        val = float(val_str)
    except ValueError:
        raise ConfigError(f"Configuration setting '{key}' must be a valid number, got '{val_str}'.")
    if not (min_val <= val <= max_val):
        raise ConfigError(f"Configuration setting '{key}' must be between {min_val} and {max_val}, got {val}.")
    return val


def parse_int_setting(key: str, default: str, min_val: int = 1, max_val: int = 65535) -> int:
    """Parses and validates an integer environment setting.

    Args:
        key: Environment variable key name.
        default: Default string value if key is not set.
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).

    Returns:
        Validated int value.

    Raises:
        ConfigError: If value cannot be parsed as int or falls outside range.
    """
    val_str = os.getenv(key, default).strip()
    try:
        val = int(val_str)
    except ValueError:
        raise ConfigError(f"Configuration setting '{key}' must be a valid integer, got '{val_str}'.")
    if not (min_val <= val <= max_val):
        raise ConfigError(f"Configuration setting '{key}' port must be between {min_val} and {max_val}, got {val}.")
    return val


# Core settings
ATTENDANCE_THRESHOLD: float = parse_float_setting("ATTENDANCE_THRESHOLD", "75.0", 0.0, 100.0)
EXCEL_PATH: Path = BASE_DIR / os.getenv("EXCEL_PATH", "data/sample_attendance.xlsx")
REPORT_OUTPUT_DIR: Path = BASE_DIR / os.getenv("REPORT_OUTPUT_DIR", "reports")
DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/delivery_history.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# Email & SMTP Settings
DRY_RUN: bool = os.getenv("DRY_RUN", "true").strip().lower() in ("true", "1", "yes")
SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT: int = parse_int_setting("SMTP_PORT", "587", 1, 65535)
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "").strip()
TEST_RECIPIENT_EMAIL: str = os.getenv("TEST_RECIPIENT_EMAIL", "").strip()

# Reporting & calendar assumptions
WEEK_START_DAY: int = 0  # Monday (0) to Sunday (6)
TIMEZONE_ASSUMPTION: str = "Naive local date (YYYY-MM-DD)"


def validate_config() -> Dict[str, Any]:
    """Validates runtime configuration settings.

    Returns:
        Dict of validated configuration settings.

    Raises:
        ConfigError: If any configuration setting is invalid or out of bounds.
    """
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if LOG_LEVEL not in valid_levels:
        raise ConfigError(
            f"Invalid LOG_LEVEL '{LOG_LEVEL}'. Must be one of: {sorted(valid_levels)}"
        )

    # Validate numeric threshold
    threshold = parse_float_setting("ATTENDANCE_THRESHOLD", str(ATTENDANCE_THRESHOLD), 0.0, 100.0)

    # Validate port number
    port = parse_int_setting("SMTP_PORT", str(SMTP_PORT), 1, 65535)

    return {
        "ATTENDANCE_THRESHOLD": threshold,
        "EXCEL_PATH": EXCEL_PATH,
        "REPORT_OUTPUT_DIR": REPORT_OUTPUT_DIR,
        "DB_PATH": DB_PATH,
        "LOG_LEVEL": LOG_LEVEL,
        "DRY_RUN": DRY_RUN,
        "SMTP_HOST": SMTP_HOST,
        "SMTP_PORT": port,
        "SMTP_USERNAME": SMTP_USERNAME,
        "SENDER_EMAIL": SENDER_EMAIL,
        "TEST_RECIPIENT_EMAIL": TEST_RECIPIENT_EMAIL,
    }
