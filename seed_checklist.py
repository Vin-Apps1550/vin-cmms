import csv, sqlite3, pathlib

# File paths
DATA = pathlib.Path("data")
DB = DATA / "pm_scheduler.db"
CSV_FILE = DATA / "checklist.csv"

# Connect to the database
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Create checklist_templates table (if not exists)
cur.execute("""
CREATE TABLE IF NOT EXISTS checklist_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_type TEXT,
    pm_type TEXT,
    task TEXT
)
""")

# Optional: Clear existing checklist_templates before inserting
cur.execute("DELETE FROM checklist_templates")

# Load checklist.csv and insert rows
with open(CSV_FILE, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = [
        (row['Equipment Type'].strip(), row['PM Type'].strip(), row['Checklist Item'].strip())
        for row in reader
    ]
    cur.executemany(
        "INSERT INTO checklist_templates (equipment_type, pm_type, task) VALUES (?, ?, ?)",
        rows
    )

conn.commit()
conn.close()
print(f"✅ Checklist templates seeded from: {CSV_FILE}")