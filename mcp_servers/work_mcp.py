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
def add_lesson(lessons: list[dict]) -> str:
    """Add one or more lesson records to the CSV. Each item in the list is a dict with keys:
    student_name, date (YYYY-MM-DD), time (HH:MM), price (NIS),
    paid ('yes' or 'no', default 'yes'), payment_date (YYYY-MM-DD or empty).
    All lessons are checked for duplicates and added in a single batch."""
    _ensure_csv()
    # Read existing rows to check for duplicates
    existing_slots = set()
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_slots.add((row["date"], row["time"]))

    results = []
    new_rows = []
    for lesson in lessons:
        date = lesson["date"]
        time = lesson["time"]
        student_name = lesson["student_name"]
        price = lesson["price"]
        paid = lesson.get("paid", "yes")
        payment_date = lesson.get("payment_date", "")

        if (date, time) in existing_slots:
            results.append(f"Lesson already exists on {date} at {time} — skipped.")
        else:
            new_rows.append([student_name, date, time, price, paid, payment_date])
            existing_slots.add((date, time))
            results.append(f"Lesson added: {student_name} on {date} at {time}, {price} NIS, paid={paid}.")

    if new_rows:
        with open(_CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(new_rows)

    return "\n".join(results)


@mcp.tool()
def update_payment(payments: list[dict]) -> str:
    """Update payment status for one or more lessons. Each item in the list is a dict with keys:
    student_name, date (YYYY-MM-DD), time (HH:MM), paid ('yes' or 'no'),
    payment_date (YYYY-MM-DD or empty, optional).
    All updates are applied in a single batch read/write."""
    _ensure_csv()
    rows = []
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Build lookup of updates by (date, time)
    updates = {}
    for p in payments:
        key = (p["date"], p["time"])
        updates[key] = p

    results = []
    matched_keys = set()
    for row in rows:
        key = (row["date"], row["time"])
        if key in updates:
            p = updates[key]
            row["paid"] = p["paid"]
            row["payment_date"] = p.get("payment_date", "")
            matched_keys.add(key)
            results.append(f"Payment updated: {p['student_name']} on {p['date']} → paid={p['paid']}.")

    for p in payments:
        key = (p["date"], p["time"])
        if key not in matched_keys:
            results.append(f"No lesson found on {p['date']} at {p['time']}.")

    if matched_keys:
        with open(_CSV_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_HEADERS)
            writer.writeheader()
            writer.writerows(rows)

    return "\n".join(results)


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
