"""SQLite schema, connection helper and sample master data."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.environ.get("PRESS_DB", os.path.join(BASE_DIR, "data", "press.db"))

# Shop-floor clock. India has no daylight saving, so a fixed offset is enough.
TZ = timezone(timedelta(minutes=int(os.environ.get("PRESS_TZ_OFFSET_MIN", "330"))))


def now() -> datetime:
    return datetime.now(TZ)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def stamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


def financial_year(d: datetime | None = None) -> str:
    """Indian financial year (April-March), e.g. '2026-27'."""
    d = d or now()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('manager','desk','superintendent','operator')),
  salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  contact_person TEXT NOT NULL DEFAULT '',
  phone1 TEXT NOT NULL DEFAULT '',
  phone2 TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  pin TEXT NOT NULL DEFAULT '',
  gstin TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS papers(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  gsm INTEGER NOT NULL DEFAULT 0,
  width_in REAL NOT NULL,
  height_in REAL NOT NULL,
  rate_per_ream REAL NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS machines(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'offset',
  rate_per_1000 REAL NOT NULL DEFAULT 0,
  per_color INTEGER NOT NULL DEFAULT 1,
  setup_per_plate REAL NOT NULL DEFAULT 0,
  min_charge REAL NOT NULL DEFAULT 0,
  makeready_sheets INTEGER NOT NULL DEFAULT 0,
  needs_plate INTEGER NOT NULL DEFAULT 1,
  max_colors INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS plate_types(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  rate REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS finishing(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  group_name TEXT NOT NULL DEFAULT 'Finishing',
  basis TEXT NOT NULL DEFAULT 'per_copy',
  rate REAL NOT NULL DEFAULT 0,
  min_charge REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS counters(
  kind TEXT NOT NULL,
  fy TEXT NOT NULL,
  last INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(kind, fy)
);

CREATE TABLE IF NOT EXISTS quotations(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  quote_date TEXT NOT NULL,
  valid_until TEXT NOT NULL DEFAULT '',
  copies INTEGER NOT NULL,
  spec_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  total REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  job_id INTEGER,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status);
CREATE INDEX IF NOT EXISTS idx_quotations_customer ON quotations(customer_id);

CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY,
  order_no TEXT NOT NULL UNIQUE,
  quotation_id INTEGER REFERENCES quotations(id),
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  title TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'approved',
  priority TEXT NOT NULL DEFAULT 'normal',
  quotation_date TEXT NOT NULL DEFAULT '',
  proof_date TEXT NOT NULL DEFAULT '',
  delivery_date TEXT NOT NULL DEFAULT '',
  copies INTEGER NOT NULL DEFAULT 0,
  total REAL NOT NULL DEFAULT 0,
  gst_pct REAL NOT NULL DEFAULT 0,
  hsn TEXT NOT NULL DEFAULT '',
  advance REAL NOT NULL DEFAULT 0,
  receipt_no TEXT NOT NULL DEFAULT '',
  bill_no TEXT NOT NULL DEFAULT '',
  ok_for_delivery INTEGER NOT NULL DEFAULT 0,
  designer TEXT NOT NULL DEFAULT '',
  extra_details TEXT NOT NULL DEFAULT '',
  work_json TEXT NOT NULL DEFAULT '{}',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  stage_changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(stage);
CREATE INDEX IF NOT EXISTS idx_jobs_customer ON jobs(customer_id);

CREATE TABLE IF NOT EXISTS job_events(
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id),
  kind TEXT NOT NULL,
  stage TEXT,
  note TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id);

CREATE TABLE IF NOT EXISTS paper_sizes(
  id INTEGER PRIMARY KEY,
  paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  width_in REAL NOT NULL,
  height_in REAL NOT NULL,
  kg_per_100 REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_sizes ON paper_sizes(paper_id);

CREATE TABLE IF NOT EXISTS stock_items(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'paper',
  unit TEXT NOT NULL DEFAULT 'sheets',
  paper_id INTEGER REFERENCES papers(id),
  reorder_level REAL NOT NULL DEFAULT 0,
  location TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_moves(
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES stock_items(id),
  qty REAL NOT NULL,
  kind TEXT NOT NULL,
  job_id INTEGER REFERENCES jobs(id),
  ref TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  user_id INTEGER REFERENCES users(id),
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moves_item ON stock_moves(item_id);
CREATE INDEX IF NOT EXISTS idx_moves_job ON stock_moves(job_id);
"""

# Columns added after the first release: (table, column, definition)
MIGRATIONS = [
    ("papers", "pricing", "TEXT NOT NULL DEFAULT 'ream'"),
    ("papers", "rate_per_kg", "REAL NOT NULL DEFAULT 0"),
    ("papers", "weight_mode", "TEXT NOT NULL DEFAULT 'auto'"),
    ("users", "department", "TEXT NOT NULL DEFAULT ''"),
    ("jobs", "assigned_to", "INTEGER REFERENCES users(id)"),
    ("jobs", "assigned_at", "TEXT NOT NULL DEFAULT ''"),
    ("jobs", "progress_pct", "INTEGER NOT NULL DEFAULT 0"),
]


def migrate(conn: sqlite3.Connection) -> None:
    for table, col, ddl in MIGRATIONS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

DEFAULT_SETTINGS = {
    "company_name": "St. Joseph's Orphanage Press",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_gstin": "",
    "gst_pct": "12",
    "hsn_default": "",
    "default_margin_pct": "25",
    "wastage_pct": "5",
    "bleed_in": "0.125",
    "gripper_in": "0.5",
    "quote_valid_days": "15",
    "round_to_rupee": "1",
    "quote_terms": "Rates are valid for the period stated. Advance payment is required before work starts. "
                   "Delivery date is counted from proof approval.",
    # Cleared to 1 by the manager once the sample rates below have been replaced.
    "rates_confirmed": "0",
}

# SAMPLE RATES ONLY. They exist so the estimator works on day one; the press
# must replace them with its own rates (Rates screen) before quoting customers.
SAMPLE_REELS = [
    # name, gsm, reel width (in), cut length (in), rate per kg
    ("Apelitho 70 gsm reel (23 in, cut 36 in)", 70, 23, 36, 80),
    ("Apelitho 60 gsm reel (23 in, cut 36 in)", 60, 23, 36, 78),
]

SAMPLE_PAPERS = [
    # name, gsm, width, height, rate per ream (500 sheets)
    ("Maplitho 70 gsm 23x36", 70, 23, 36, 1500),
    ("Maplitho 80 gsm 23x36", 80, 23, 36, 1750),
    ("Maplitho 80 gsm 18x23 (Demy)", 80, 18, 23, 910),
    ("Art Paper 130 gsm 23x36", 130, 23, 36, 3300),
    ("Art Paper 170 gsm 23x36", 170, 23, 36, 4300),
    ("Art Card 250 gsm 23x36", 250, 23, 36, 6500),
    ("Copier 75 gsm A4", 75, 8.27, 11.69, 280),
    ("Copier 75 gsm A3", 75, 11.69, 16.54, 560),
]
SAMPLE_PLATES = [("Polymaster", 120), ("Laser plate", 60), ("Aluminium CTP", 350)]
SAMPLE_MACHINES = [
    # name, kind, rate/1000, per_color, setup/plate, min_charge, makeready sheets, needs_plate, max_colors
    ("Komori (4 colour)", "offset", 100, 1, 150, 400, 15, 1, 4),
    ("HMT 2 Color", "offset", 70, 1, 100, 300, 15, 1, 2),
    ("HMT D/Demy", "offset", 60, 1, 100, 250, 12, 1, 1),
    ("Ryobi", "offset", 60, 1, 100, 250, 12, 1, 2),
    ("Dominent", "offset", 50, 1, 80, 200, 10, 1, 1),
    ("Manugraph (sheetfed)", "offset", 80, 1, 120, 300, 15, 1, 4),
    ("Web Manugraph", "web", 30, 1, 500, 5000, 50, 1, 4),
    ("Web Orient", "web", 30, 1, 500, 5000, 50, 1, 4),
    ("RISO", "riso", 150, 0, 0, 100, 5, 0, 0),
    ("Laser (B&W)", "digital", 600, 0, 0, 50, 0, 0, 0),
    ("Laser (colour)", "digital", 6000, 0, 0, 100, 0, 0, 0),
]
SAMPLE_FINISHING = [
    # name, group, basis, rate, min charge
    ("Lamination Matt - single side", "Lamination", "per_sqft", 2.0, 150),
    ("Lamination Matt - both sides", "Lamination", "per_sqft", 4.0, 250),
    ("Lamination Gloss - single side", "Lamination", "per_sqft", 1.8, 150),
    ("Lamination Gloss - both sides", "Lamination", "per_sqft", 3.6, 250),
    ("Spot UV", "Special finish", "per_copy", 2.0, 500),
    ("3D", "Special finish", "per_copy", 3.0, 500),
    ("Dripoff", "Special finish", "per_copy", 2.0, 500),
    ("Foil", "Special finish", "per_copy", 2.5, 600),
    ("Knurling", "Special finish", "per_copy", 1.0, 300),
    ("Die cutting", "Special finish", "per_1000", 1500, 800),
    ("Folding", "Post-press", "per_1000_sheets", 150, 100),
    ("Creasing", "Post-press", "per_1000_sheets", 120, 100),
    ("Perforation", "Post-press", "per_1000", 200, 100),
    ("Numbering", "Post-press", "per_1000", 250, 150),
    ("Pasting", "Post-press", "per_1000_leaves", 300, 200),
    ("Shrinkwrap", "Post-press", "per_copy", 1.0, 100),
    ("Colour of screen printing", "Post-press", "per_copy", 3.0, 300),
    ("Stitching", "Binding", "per_copy", 0.5, 100),
    ("Centre pin", "Binding", "per_copy", 0.6, 100),
    ("Perfect binding", "Binding", "per_copy", 6.0, 300),
    ("Case binding", "Binding", "per_copy", 35.0, 500),
    ("Register binding", "Binding", "per_copy", 80.0, 500),
    ("Padmaking", "Binding", "per_copy", 1.5, 100),
]


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or DEFAULT_DB
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str | None = None) -> None:
    """Create tables and, on a brand-new database, load the sample masters."""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        seeded = conn.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()
        if not seeded:
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
            conn.executemany("INSERT INTO papers(name,gsm,width_in,height_in,rate_per_ream) VALUES(?,?,?,?,?)", SAMPLE_PAPERS)
            conn.executemany(
                "INSERT INTO papers(name,gsm,width_in,height_in,rate_per_ream,pricing,rate_per_kg) VALUES(?,?,?,?,0,'kg',?)",
                SAMPLE_REELS)
            conn.executemany("INSERT INTO plate_types(name,rate) VALUES(?,?)", SAMPLE_PLATES)
            conn.executemany(
                "INSERT INTO machines(name,kind,rate_per_1000,per_color,setup_per_plate,min_charge,"
                "makeready_sheets,needs_plate,max_colors) VALUES(?,?,?,?,?,?,?,?,?)",
                SAMPLE_MACHINES,
            )
            conn.executemany(
                "INSERT INTO finishing(name,group_name,basis,rate,min_charge) VALUES(?,?,?,?,?)",
                SAMPLE_FINISHING,
            )
            conn.execute("INSERT INTO meta(key,value) VALUES('seeded','1')")
        else:
            for k, v in DEFAULT_SETTINGS.items():  # new settings added in later versions
                conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        conn.commit()
    finally:
        conn.close()


def next_number(conn: sqlite3.Connection, kind: str, prefix: str) -> tuple[str, str]:
    """Atomically take the next running number for this financial year."""
    fy = financial_year()
    conn.execute("INSERT OR IGNORE INTO counters(kind,fy,last) VALUES(?,?,0)", (kind, fy))
    conn.execute("UPDATE counters SET last=last+1 WHERE kind=? AND fy=?", (kind, fy))
    n = conn.execute("SELECT last FROM counters WHERE kind=? AND fy=?", (kind, fy)).fetchone()["last"]
    return fy, f"{prefix}-{fy.replace('-', '')}-{n:04d}"
