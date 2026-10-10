"""Excel workbook reader for AttendEase attendance sheets."""

import logging
from pathlib import Path
from typing import Tuple, Union
import pandas as pd

logger = logging.getLogger(__name__)


class ExcelReadError(Exception):
    """Raised when the Excel file cannot be loaded or opened."""
    pass


def load_workbook(file_path: Union[str, Path]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Loads Attendance and Class_Schedule sheets from an Excel workbook.

    Args:
        file_path: Path to the .xlsx workbook file.

    Returns:
        Tuple containing (df_attendance, df_schedule).

    Raises:
        FileNotFoundError: If the file does not exist.
        ExcelReadError: If pandas/openpyxl fails to read the Excel file.
    """
    path = Path(file_path)
    if not path.is_file():
        logger.error(f"Excel workbook not found at path: {path}")
        raise FileNotFoundError(f"Attendance workbook not found at path: {path}")

    try:
        excel_file = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        logger.error(f"Failed to open Excel file {path}: {exc}")
        raise ExcelReadError(f"Could not open Excel file '{path}': {exc}") from exc

    available_sheets = excel_file.sheet_names
    logger.info(f"Opened workbook '{path}'. Sheets found: {available_sheets}")

    try:
        # Read raw sheets keeping string columns clean
        df_attendance = pd.read_excel(excel_file, sheet_name="Attendance", dtype=str)
        df_schedule = pd.read_excel(excel_file, sheet_name="Class_Schedule", dtype=str)
    except ValueError as val_err:
        logger.error(f"Required sheet missing in {path}: {val_err}")
        raise ExcelReadError(f"Workbook missing required sheets: {val_err}") from val_err

    return df_attendance, df_schedule
