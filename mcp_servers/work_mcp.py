import csv
import logging
import os
from mcp.server.fastmcp import FastMCP

logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("work-tools")

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV_PATH = os.path.join(_DIR, "data", "work_ledger.csv")
_HEADERS = ["student_name", "date", "time", "price", "paid", "payment_date"]


def _ensure_csv():
    """Create the CSV file with headers if it doesn't exist."""
    os.makedirs(os.path.dirname(_CSV_PATH), exist_ok=True)
    if not os.path.exists(_CSV_PATH):
        with open(_CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(_HEADERS)


@mcp.tool()
def read_lessons(month: str) -> str:
    """Read all lessons for a given month. month should be in YYYY-MM format."""
    _ensure_csv()
    rows = []
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"].startswith(month):
                rows.append(row)
    if not rows:
        return f"No lessons found for {month}."
    lines = []
    for r in rows:
        lines.append(
            f"Student: {r['student_name']}, Date: {r['date']}, "
            f"Time: {r['time']}, Price: {r['price']} NIS, Paid: {r['paid']}, "
            f"Payment Date: {r['payment_date'] or 'N/A'}"
        )
    return "\n".join(lines)


@mcp.tool()
def add_lesson(
    student_name: str,
    date: str,
    time: str,
    price: str,
    paid: str = "yes",
    payment_date: str = "",
) -> str:
    """Add a lesson record to the CSV.
    date in YYYY-MM-DD, time in HH:MM (lesson start time), price in NIS.
    paid is 'yes' or 'no'. payment_date in YYYY-MM-DD or empty."""
    _ensure_csv()
    # Check for duplicate by date + time (same slot = same lesson regardless of name)
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] == date and row["time"] == time:
                return f"Lesson already exists on {date} at {time} ({row['student_name']})."
    with open(_CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([student_name, date, time, price, paid, payment_date])
    return f"Lesson added: {student_name} on {date} at {time}, {price} NIS, paid={paid}."


@mcp.tool()
def update_payment(student_name: str, date: str, time: str, paid: str, payment_date: str = "") -> str:
    """Update payment status for a lesson. paid is 'yes' or 'no'.
    date (YYYY-MM-DD) and time (HH:MM) identify the lesson."""
    _ensure_csv()
    rows = []
    updated = False
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] == date and row["time"] == time:
                row["paid"] = paid
                row["payment_date"] = payment_date
                updated = True
            rows.append(row)
    if not updated:
        return f"No lesson found on {date} at {time}."
    with open(_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return f"Payment updated: {student_name} on {date} → paid={paid}."


@mcp.tool()
def get_all_lessons() -> str:
    """Read all lessons from the CSV file."""
    _ensure_csv()
    rows = []
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    if not rows:
        return "No lessons recorded yet."
    lines = []
    for r in rows:
        lines.append(
            f"Student: {r['student_name']}, Date: {r['date']}, "
            f"Time: {r['time']}, Price: {r['price']} NIS, Paid: {r['paid']}, "
            f"Payment Date: {r['payment_date'] or 'N/A'}"
        )
    return "\n".join(lines)



if __name__ == "__main__":
    mcp.run()
