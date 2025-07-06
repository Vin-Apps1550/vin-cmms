import csv, sqlite3, pathlib, os

DATA = pathlib.Path("data")
DB   = DATA / "pm_scheduler.db"

conn = sqlite3.connect(DB)
cur  = conn.cursor()

# ── fresh schema ───────────────────────────────────────────────
cur.executescript("""
DROP TABLE IF EXISTS equipment;
DROP TABLE IF EXISTS pm_schedule;
DROP TABLE IF EXISTS running_hours;
DROP TABLE IF EXISTS pm_checklist_templates;      -- new

CREATE TABLE equipment (
  id           TEXT PRIMARY KEY,
  description  TEXT,
  make         TEXT,
  model        TEXT,
  in_service   TEXT,
  hour_meter   REAL
);

CREATE TABLE pm_schedule (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment_id   TEXT,
  interval_label TEXT,
  interval_hrs   REAL,
  last_pm_hrs    REAL,
  next_pm_due    REAL,
  last_pm_date   TEXT,
  FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);

CREATE TABLE running_hours (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment_id TEXT,
  reading      REAL,
  date_logged  TEXT,
  notes        TEXT,
  ts           TEXT
);

CREATE TABLE pm_checklist_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pm_type     TEXT,
  step_order  INTEGER,
  step_text   TEXT
);
""")

# ── helper to import any CSV safely ────────────────────────────
def import_csv(csv_file, table, col_map):
    path = DATA / csv_file
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        raw_headers = [h.lstrip("\ufeff").strip() for h in next(reader)]
        header_idx  = {h: i for i, h in enumerate(raw_headers)}

        rows = [
            [row[header_idx[csv_h]].strip() for csv_h, _ in col_map]
            for row in reader
        ]

    db_cols = [db_h for _, db_h in col_map]
    placeholders = ",".join("?" * len(db_cols))
    cur.executemany(
        f"INSERT INTO {table} ({','.join(db_cols)}) VALUES ({placeholders})",
        rows
    )

# equipment.csv  →  equipment table
import_csv(
    "equipment_master.csv",
    "equipment",
    [
        ("equipment_id", "id"),
        ("description",  "description"),
        ("make",         "make"),
        ("model",        "model"),
        ("in_service",   "in_service"),
        ("hour_meter",   "hour_meter")
    ]
)

# pm_schedule.csv  → pm_schedule table
import_csv(
    "pm_schedule.csv",
    "pm_schedule",
    [
        ("equipment_id",   "equipment_id"),
        ("pm_type",        "interval_label"),
        ("interval_hrs",   "interval_hrs"),
        ("last_pm_hrs",    "last_pm_hrs"),
        ("next_pm_due",    "next_pm_due"),
        ("last_pm_date",   "last_pm_date")
    ]
)

# ── seed 25 demo checklist steps per PM type ──────────────────
steps_250 = [
    "Check engine oil level", "Inspect hydraulic hoses", "Check tire pressure",
    "Inspect lights & horn", "Check coolant level", "Check fuel level",
    "Check battery terminals", "Inspect belts for wear", "Look for leaks",
    "Inspect air filter", "Clean cab interior", "Grease all fittings",
    "Inspect mirrors", "Check fire extinguisher", "Inspect wipers",
    "Test backup alarm", "Test seatbelt", "Check DEF level",
    "Check fan operation", "Test brakes", "Test steering",
    "Inspect undercarriage", "Inspect engine bay", "Clean radiator",
    "Final visual inspection"
]
steps_500 = [f"500-hour task {i}" for i in range(1,26)]
steps_1000= [f"1000-hour task {i}" for i in range(1,26)]

def seed_checklist(pm_type, steps):
    cur.executemany(
        """INSERT INTO pm_checklist_templates (pm_type, step_order, step_text)
           VALUES (?, ?, ?)""",
        [(pm_type, i+1, txt) for i, txt in enumerate(steps)]
    )

seed_checklist("250H",  steps_250)
seed_checklist("500H",  steps_500)
seed_checklist("1000H", steps_1000)

conn.commit()
conn.close()
print("✅ SQLite database seeded:", DB)