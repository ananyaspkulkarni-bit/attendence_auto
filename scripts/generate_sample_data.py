"""Generate synthetic sample Excel attendance data for testing and development."""

from pathlib import Path
import pandas as pd


def generate_sample_workbook(output_path: str = "data/sample_attendance.xlsx") -> None:
    """Creates a sample Excel file with Attendance and Class_Schedule sheets.

    Synthetic Students:
    - S1001: Alex Taylor (Good Standing: 77.78%)
    - S1002: Jordan Lee (Warning: 55.56% - Below 75% Threshold)
    - S1003: Morgan Smith (Good Standing: 100.00%)
    """
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sheet 1: Attendance
    attendance_data = {
        "student_id": ["S1001", "S1002", "S1003"],
        "name": ["Alex Taylor", "Jordan Lee", "Morgan Smith"],
        "email": ["alex.taylor@example.edu", "jordan.lee@example.edu", "morgan.smith@example.edu"],
        "C001": ["P", "P", "P"],
        "C002": ["A", "A", "P"],
        "C003": ["P", "P", "P"],
        "C004": ["P", "A", "P"],
        "C005": ["P", "P", "P"],
        "C006": ["A", "A", "P"],
        "C007": ["P", "A", "P"],
        "C008": ["P", "P", "P"],
        "C009": ["P", "A", "P"],
        "C010": ["", "", ""],  # Future class scheduled after reporting date 2026-10-15
    }
    df_attendance = pd.DataFrame(attendance_data)

    # Sheet 2: Class_Schedule
    schedule_data = {
        "class_id": [
            "C001", "C002", "C003", "C004", "C005",
            "C006", "C007", "C008", "C009", "C010"
        ],
        "class_date": [
            "2026-09-07",  # Mon (W37, Sept)
            "2026-09-09",  # Wed (W37, Sept)
            "2026-09-14",  # Mon (W38, Sept)
            "2026-09-16",  # Wed (W38, Sept)
            "2026-10-05",  # Mon (W41, Oct)
            "2026-10-07",  # Wed (W41, Oct)
            "2026-10-12",  # Mon (W42, Oct - Reporting Week)
            "2026-10-14",  # Wed (W42, Oct - Reporting Week)
            "2026-10-15",  # Thu (W42, Oct - Reporting Date)
            "2026-10-20",  # Tue (W43, Oct - Future Class)
        ],
        "subject": [
            "Python Fundamentals", "Data Structures",
            "Python Fundamentals", "Data Structures",
            "Python Fundamentals", "Data Structures",
            "Python Fundamentals", "Data Structures",
            "Database Systems", "Database Systems"
        ],
    }
    df_schedule = pd.DataFrame(schedule_data)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_attendance.to_excel(writer, sheet_name="Attendance", index=False)
        df_schedule.to_excel(writer, sheet_name="Class_Schedule", index=False)

    print(f"Sample workbook generated successfully at: {output_path}")


if __name__ == "__main__":
    generate_sample_workbook()
