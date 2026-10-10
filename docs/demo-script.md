# AttendEase Portfolio Demonstration Script (3–5 Minutes)

This script provides a structured step-by-step presentation for showcasing **AttendEase** during technical interviews, portfolio reviews, or project demonstrations.

---

## 📋 Presentation Overview & Agenda

- **Target Audience**: Technical Recruiters, Engineering Managers, Peer Developers
- **Duration**: ~4 Minutes
- **Key Themes**: Automation Reliability, Data Validation, Recipient Safety Policies, SQLite History Locks, Clean Modular Python Architecture.
- **Safety Guarantee**: All demonstration steps use synthetic student data and offline dry-run previews. Zero real emails are dispatched.

---

## 🎙️ Step-by-Step Demonstration Walkthrough

### Part 1: Project Introduction & Problem Statement (0:00 – 0:45)

**Speaker Script**:
> "Hi everyone. Today I'm presenting **AttendEase**, a Python-based attendance reporting automation system built for academic courses.
> 
> In many college departments, attendance is logged in Excel workbooks. Manually checking attendance metrics, generating individual weekly and monthly updates, and emailing students is time-consuming and error-prone. Common issues include calculation mistakes, sending updates to wrong recipients, or accidentally sending duplicate emails.
> 
> AttendEase solves this by providing automated two-sheet schema validation, deterministic multi-period percentage calculations, recipient safety locks, and persistent SQLite duplicate-send prevention."

---

### Part 2: Synthetic Data & Workbook Structure (0:45 – 1:30)

**Speaker Action**: Show `data/sample_attendance.xlsx` structure or run the sample generator script.

**PowerShell Command**:
```powershell
python scripts/generate_sample_data.py
```

**Speaker Script**:
> "First, let's look at the input dataset. AttendEase reads standard `.xlsx` workbooks containing two required sheets: `Attendance` and `Class_Schedule`.
> 
> - The `Attendance` sheet contains student IDs, names, emails, and attendance marks (`P` for Present, `A` for Absent).
> - The `Class_Schedule` sheet maps class IDs to dates and subjects.
> 
> Our synthetic dataset includes three student profiles:
> 1. `S1001` (Alex Taylor) — Good Standing (77.78% attendance).
> 2. `S1002` (Jordan Lee) — Below Threshold Warning (55.56% attendance vs 75% target).
> 3. `S1003` (Morgan Smith) — Perfect Attendance (100.00%)."

---

### Part 3: Workbook Validation & Report Preview (1:30 – 2:30)

**Speaker Action**: Run the `--validate-only` command, followed by `--preview-only` for student `S1002` (Warning Profile).

**PowerShell Commands**:
```powershell
# 1. Validate workbook schema & integrity
python -m attendease.main --validate-only

# 2. Preview attendance report for student S1002 as of 2026-10-15
python -m attendease.main --preview-only --student-id S1002 --date 2026-10-15
```

**Expected Output Highlights**:
- Validation output confirming 3 students and 10 scheduled classes found.
- Report preview for `S1002` showing:
  - Weekly: `50.00% (1/2 attended)`
  - Monthly: `60.00% (3/5 attended)`
  - Overall: `55.56% (5/9 attended)`
  - Prominent warning banner: `⚠️ WARNING: OVERALL ATTENDANCE IS BELOW THE REQUIRED TARGET!`

**Speaker Script**:
> "Notice how AttendEase validates the workbook structure before processing. It normalizes whitespace and attendance mark capitalization automatically.
> 
> When we preview the report for `S1002`, AttendEase calculates weekly, monthly, and overall attendance up to the cutoff date (`2026-10-15`). Classes scheduled after the cutoff date are strictly excluded. Because `S1002` falls below our configured 75% threshold, a clear warning banner is automatically generated."

---

### Part 4: Dry-Run Email Preview & Safety Guards (2:30 – 3:30)

**Speaker Action**: Run the standard CLI command (Default Dry-Run Mode).

**PowerShell Command**:
```powershell
python -m attendease.main --student-id S1001 --date 2026-10-15
```

**Expected Output Highlights**:
- Terminal header: `================ DRY RUN — EMAIL REPORT PREVIEW ================`
- Local file saved message: `Report preview saved to: reports/report_S1001.txt`
- Verification note: `[DRY-RUN MODE ACTIVE] No SMTP connection established. No email sent.`

**Speaker Script**:
> "Safety is a top priority in AttendEase. By default, the application runs in **Dry-Run Mode**. It renders a complete plain-text email preview to the terminal and saves a report text file to disk (`reports/report_S1001.txt`).
> 
> It never connects to an SMTP server or opens a network socket in dry-run mode, ensuring zero accidental emails can ever be dispatched during testing or preparation."

---

### Part 5: Duplicate Prevention & History Inspection (3:30 – 4:30)

**Speaker Action**: Show delivery history and check sent status commands.

**PowerShell Commands**:
```powershell
# 1. Check if report for S1001 has been sent
python -m attendease.main --check-sent --student-id S1001 --date 2026-10-15

# 2. View SQLite delivery history table
python -m attendease.main --history
```

**Speaker Script**:
> "AttendEase tracks every real email delivery attempt in a local SQLite database (`data/delivery_history.db`).
> 
> It derives a deterministic report key formatted as `<student_id>:<report_type>:<reporting_date>`. Before any real email delivery attempt, AttendEase checks the database. If a successful send record already exists for that report key, the send is blocked by default.
> 
> To resend a report, an operator must explicitly pass the `--resend` flag and confirm the action interactively.
> 
> In summary, AttendEase provides a clean, reliable, recipient-safe CLI for automating attendance reporting. Thank you!"

---

## 📊 Demo Execution Summary Matrix

| Step | Command | Goal | Safety Feature |
| :--- | :--- | :--- | :--- |
| **1. Data Setup** | `python scripts/generate_sample_data.py` | Create synthetic 3-student dataset. | 100% synthetic data (`@example.edu`). |
| **2. Validation** | `python -m attendease.main --validate-only` | Verify workbook schema & mapping. | Read-only mode; no file creation. |
| **3. Report Preview** | `python -m attendease.main --preview-only --student-id S1002` | Test threshold warning rendering. | Terminal display only; no email. |
| **4. Dry-Run Mode** | `python -m attendease.main --student-id S1001` | Test full report pipeline & disk save. | Zero network/SMTP connection. |
| **5. History Check** | `python -m attendease.main --history` | Inspect delivery log table. | SQLite read transaction. |
