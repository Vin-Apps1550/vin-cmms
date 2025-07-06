import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

# ── Flask & DB helpers ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "super-secret-vin-key"

DB_PATH = "data/pm_scheduler.db"
os.makedirs("data", exist_ok=True)

# Which PM comes next, and how many hours until it’s due
NEXT_INTERVAL = {
    "250H":  ("500H", 250),   # after a 250-hour, next service is 500H, +250 hrs
    "500H":  ("1000H", 500),  # after a 500-hour, next is 1000H, +500 hrs
    "1000H": ("250H", 250)    # after 1000-hour, cycle restarts at 250H, +250 hrs
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row         # rows act like dicts
    return conn

try:
    with get_db() as db:
        db.execute("ALTER TABLE equipment ADD COLUMN status TEXT DEFAULT 'Active'")
        db.commit()
except sqlite3.OperationalError as e:
    if "duplicate column" not in str(e).lower():
        raise  # re-raise if it's some other SQL problem

# Create the completed_pm table if it doesn't exist
with get_db() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS completed_pm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id TEXT,
            pm_type      TEXT,
            done_date    TEXT,
            hours_done   REAL,
            ts           TEXT      -- UTC timestamp
        )
    """)
    db.commit()

# ── Load equipment IDs once for the dropdown ─────────────────────────
with get_db() as db:
    EQUIPS  = [r["id"] for r in db.execute("SELECT id FROM equipment ORDER BY id")]
    TYPES   = [r["description"] for r in db.execute(
                 "SELECT DISTINCT description FROM equipment ORDER BY description")]

# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("home.html")

# --- PM Schedule -----------------------------------------------------
@app.route("/schedule")
def schedule():
    overdue_only = request.args.get("overdue") == "1"

    sql = """
      SELECT e.id             AS equipment_id,
             p.interval_label AS interval_label,
             p.interval_hrs   AS interval_hrs,
             p.last_pm_hrs    AS last_pm_hrs,
             p.next_pm_due    AS next_pm_due,
             p.last_pm_date   AS last_pm_date,
             e.hour_meter     AS hour_meter,
             CASE WHEN e.hour_meter >= p.next_pm_due THEN 1 ELSE 0 END AS overdue
        FROM pm_schedule p
        JOIN equipment   e ON e.id = p.equipment_id
    """
    if overdue_only:
        sql += " WHERE e.hour_meter >= p.next_pm_due "

    sql += " ORDER BY overdue DESC, e.id "

    with get_db() as db:
        rows = db.execute(sql).fetchall()

    return render_template("schedule.html", rows=rows, overdue_only=overdue_only)

# --- Reports & Status placeholders ----------------------------------
@app.route("/reports")
def reports():
    UPCOMING_WINDOW = 100      # hrs ahead to treat as “upcoming”

    with get_db() as db:
        rows = db.execute("""
            SELECT e.id               AS equipment_id,
                   e.description,
                   e.hour_meter,
                   p.interval_label,
                   p.next_pm_due,
                   p.last_pm_date,
                   CASE
                     WHEN e.hour_meter >= p.next_pm_due THEN 'Overdue'
                     WHEN p.next_pm_due - e.hour_meter <= ? THEN 'Upcoming'
                     ELSE 'OK'
                   END AS status
              FROM pm_schedule p
              JOIN equipment   e ON e.id = p.equipment_id
          ORDER BY status DESC, e.id
        """, (UPCOMING_WINDOW,)).fetchall()

    overdue   = [r for r in rows if r["status"] == "Overdue"]
    upcoming  = [r for r in rows if r["status"] == "Upcoming"]

    return render_template("reports.html",
                           overdue=overdue,
                           upcoming=upcoming,
                           window=UPCOMING_WINDOW)

STATUS_CHOICES = ["Active", "PM Ongoing", "Down"]

@app.post("/status/update/<equip_id>")
def update_status(equip_id):
    new_status = request.form.get("status")
    if new_status not in STATUS_CHOICES:
        flash("Invalid status.", "error")
        return redirect(url_for("status"))

    with get_db() as db:
        db.execute("UPDATE equipment SET status = ? WHERE id = ?", (new_status, equip_id))
        db.commit()

    flash(f"Status for {equip_id} updated to {new_status}.", "success")
    return redirect(url_for("status"))


@app.route("/status")
def status():
    with get_db() as db:
        rows = db.execute("""
            SELECT e.id, e.description, e.hour_meter, e.status,
                   p.last_pm_date
              FROM equipment e
              LEFT JOIN pm_schedule p ON e.id = p.equipment_id
          ORDER BY e.id
        """).fetchall()
    return render_template("status.html", rows=rows, STATUS_CHOICES=STATUS_CHOICES)

# --- Log Running Hours ----------------------------------------------


# --- Log Running Hours ------------------------------------------------
@app.route("/running-hours", methods=["GET", "POST"])
def running_hours():
    if request.method == "POST":
        equip_id  = request.form["equip_id"].strip()
        hours     = request.form["hours"].strip()
        date_log  = request.form["date_logged"].strip()
        notes     = request.form.get("notes", "").strip()

        if not equip_id or not hours or not date_log:
            flash("Equipment, Hours and Date are required.", "error")
            return redirect(url_for("running_hours"))

        with get_db() as db:
            # 1) insert the new log
            db.execute(
                """INSERT INTO running_hours
                     (equipment_id, reading, date_logged, notes, ts)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (equip_id, hours, date_log, notes)
            )

            # 2) bump the hour-meter only if the reading is newer / larger
            db.execute(
                """UPDATE equipment
                      SET hour_meter = ?
                    WHERE id = ?
                      AND ? > hour_meter""",
                (hours, equip_id, hours)
            )
            db.commit()

        flash("Running hours logged ✔️", "success")
        return redirect(url_for("running_hours"))

    # ---------- GET: show form + newest 25 logs ----------
    with get_db() as db:
        entries = db.execute("""
            SELECT equipment_id,
                   reading        AS current_hours,
                   date_logged,
                   notes
              FROM running_hours
          ORDER BY id DESC
             LIMIT 25
        """).fetchall()

    return render_template("running_hours.html",
                           equips=EQUIPS,
                           entries=entries)

# --- Completed PM & Checklist ---------------------------------------


# --- Log a Completed PM -------------------------------------------------
@app.route("/completed-pm", methods=["GET", "POST"])
def completed_pm():
    if request.method == "POST":
        equip_id  = request.form["equip_id"].strip()
        pm_type   = request.form["pm_type"].strip()
        hours_done = request.form["hours_done"].strip()
        done_date  = request.form["done_date"].strip()

        if not equip_id or not pm_type or not hours_done or not done_date:
            flash("All fields are required.", "error")
            return redirect(url_for("completed_pm"))

        next_label, next_interval = NEXT_INTERVAL.get(pm_type, (pm_type, int(hours_done)))

        with get_db() as db:
            # 1) archive the completion
            db.execute("""
                INSERT INTO completed_pm (equipment_id, pm_type, done_date, hours_done, ts)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (equip_id, pm_type, done_date, hours_done))

            # 2) update pm_schedule row
            db.execute("""
                UPDATE pm_schedule
                   SET interval_label = ?,
                       interval_hrs   = ?,
                       last_pm_hrs    = ?,
                       next_pm_due    = ? + ?,
                       last_pm_date   = ?
                 WHERE equipment_id = ?
            """, (next_label, next_interval, hours_done,
                  hours_done, next_interval, done_date, equip_id))

            # 3) (optional) bump equipment hour-meter if operator entered a larger number
            db.execute("""
                UPDATE equipment
                   SET hour_meter = ?
                 WHERE id = ? AND ? > hour_meter
            """, (hours_done, equip_id, hours_done))

            db.commit()

        flash(f"{pm_type} completed. Next service set to {next_label}.", "success")
        return redirect(url_for("completed_pm"))

    # --- GET: render the form ------------------------------------------
    return render_template("completed_pm.html", equips=EQUIPS, pm_labels=NEXT_INTERVAL.keys())

#---------#


@app.route("/checklist", methods=["GET", "POST"])
def checklist():
    if request.method == "POST":
        equip_id = request.form["equip_id"]
        pm_type  = request.form["pm_type"]
        return redirect(url_for("checklist_view",    # ← back to ID route
                                equip_id=equip_id, pm_type=pm_type))

    return render_template(
        "checklist_form.html",
        equips=EQUIPS,                       # list of IDs
        pm_types=list(NEXT_INTERVAL.keys())
    )


# ── printable checklist page ──────────────────────────────────────

@app.route("/checklist/<equip_id>/<pm_type>")
def checklist_view(equip_id, pm_type):
    with get_db() as db:
        steps = db.execute("""
            SELECT task
              FROM checklist_templates
             WHERE pm_type = ?
               AND equipment_type = 'ALL'
          ORDER BY id
        """, (pm_type,)).fetchall()

        equip = db.execute("SELECT description FROM equipment WHERE id = ?",
                           (equip_id,)).fetchone()

    return render_template(
        "checklist_print.html",
        equip_id=equip_id,
        equip_desc=equip["description"] if equip else "",
        pm_type=pm_type,
        steps=steps,
        today=datetime.utcnow().strftime("%Y-%m-%d")
    )

@app.route("/")
def home():
    return redirect(url_for("menu"))  # or use render_template if needed

# ── printable checklist page ──────────────────────────────────────────


# ── Run the app ──────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)        # set debug=False in production