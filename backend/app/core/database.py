"""
Persistent store for experimental evaluations, resources, and protocols.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Optional

from app.core.config import DB_PATH

DB_SCHEMA = (
    "Table: evaluations\n"
    "Columns:\n"
    "  id               INTEGER — auto-increment primary key\n"
    "  condition_name   TEXT    — name of the operating condition\n"
    "  condition_value  REAL    — value of the operating condition\n"
    "  parameters       TEXT    — JSON object of free parameter name→value pairs\n"
    "  objective_name   TEXT    — name of the measured objective\n"
    "  objective_value  REAL    — measured objective value\n"
    "  timestamp        TEXT    — ISO timestamp of the measurement\n"
    "\nTable: resources\n"
    "Columns:\n"
    "  resource_id      TEXT    — UUID primary key\n"
    "  name             TEXT    — resource name\n"
    "  unit             TEXT    — unit of measurement\n"
    "  current_stock    REAL    — current quantity in stock\n"
    "  min_stock        REAL    — minimum stock alert threshold\n"
    "  description      TEXT    — description of the resource\n"
    "  consumption_rules TEXT   — JSON list of {instrument_name, amount_per_use}\n"
    "\nTable: protocols\n"
    "Columns:\n"
    "  protocol_id      TEXT    — UUID primary key\n"
    "  name             TEXT    — protocol name\n"
    "  description      TEXT    — brief description\n"
    "  created_at       TEXT    — ISO timestamp\n"
    "  optimiser_used   TEXT    — optimiser(s) used\n"
    "  results_summary  TEXT    — summary of results achieved\n"
    "  user_instructions TEXT   — JSON list of user messages\n"
    "  notes            TEXT    — scientist's notes\n"
    "  workflow_plan    TEXT    — JSON workflow plan\n"
)


@contextmanager
def _db_connection(read_only: bool = False):
    if read_only:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    else:
        con = sqlite3.connect(DB_PATH)
    try:
        yield con
    finally:
        con.close()


def ensure_db() -> None:
    with _db_connection() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                condition_name  TEXT NOT NULL,
                condition_value REAL NOT NULL,
                parameters      TEXT NOT NULL DEFAULT '{}',
                objective_name  TEXT NOT NULL,
                objective_value REAL NOT NULL,
                timestamp       TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                resource_id       TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                unit              TEXT NOT NULL DEFAULT '',
                current_stock     REAL NOT NULL DEFAULT 0,
                min_stock         REAL NOT NULL DEFAULT 0,
                description       TEXT NOT NULL DEFAULT '',
                consumption_rules TEXT NOT NULL DEFAULT '[]'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS protocols (
                protocol_id       TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                description       TEXT NOT NULL DEFAULT '',
                created_at        TEXT NOT NULL DEFAULT '',
                optimiser_used    TEXT NOT NULL DEFAULT '',
                results_summary   TEXT NOT NULL DEFAULT '',
                user_instructions TEXT NOT NULL DEFAULT '[]',
                notes             TEXT NOT NULL DEFAULT '',
                workflow_plan     TEXT NOT NULL DEFAULT '{}'
            )
        """)
        con.commit()


def reset_evaluations() -> None:
    """Drop and recreate only the evaluations table. Called on session reset."""
    with _db_connection() as con:
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS evaluations")
        cur.execute("""
            CREATE TABLE evaluations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                condition_name  TEXT NOT NULL,
                condition_value REAL NOT NULL,
                parameters      TEXT NOT NULL DEFAULT '{}',
                objective_name  TEXT NOT NULL,
                objective_value REAL NOT NULL,
                timestamp       TEXT NOT NULL
            )
        """)
        con.commit()


def write_evaluation(
    condition_name:  str,
    condition_value: float,
    parameters:      Dict[str, float],
    objective_name:  str,
    objective_value: float,
    timestamp:       str,
) -> None:
    with _db_connection() as con:
        con.execute(
            "INSERT INTO evaluations "
            "(condition_name, condition_value, parameters, objective_name, objective_value, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (condition_name, condition_value, json.dumps(parameters),
             objective_name, objective_value, timestamp),
        )
        con.commit()


def query_database(sql: str, max_rows: int = 100) -> dict:
    sql = sql.strip()
    if not sql.upper().startswith("SELECT"):
        return {"status": "error", "message": "Only SELECT statements are permitted."}
    if "LIMIT" not in sql.upper():
        sql = f"{sql} LIMIT {max_rows}"
    try:
        with _db_connection(read_only=True) as con:
            cur = con.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows    = cur.fetchall()
        return {
            "status":  "ok",
            "columns": columns,
            "rows":    [list(r) for r in rows],
            "n_rows":  len(rows),
        }
    except sqlite3.OperationalError as e:
        return {"status": "error", "message": f"Database error: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


# ── Resource CRUD ─────────────────────────────────────────────────────────────

def get_all_resources() -> List[dict]:
    with _db_connection() as con:
        rows = con.execute("SELECT * FROM resources").fetchall()
    return [
        {
            "resource_id":       row[0],
            "name":              row[1],
            "unit":              row[2],
            "current_stock":     row[3],
            "min_stock":         row[4],
            "description":       row[5],
            "consumption_rules": json.loads(row[6]),
        }
        for row in rows
    ]


def upsert_resource(resource: dict) -> None:
    with _db_connection() as con:
        con.execute("""
            INSERT OR REPLACE INTO resources
            (resource_id, name, unit, current_stock, min_stock, description, consumption_rules)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            resource["resource_id"],
            resource["name"],
            resource.get("unit", ""),
            resource.get("current_stock", 0),
            resource.get("min_stock", 0),
            resource.get("description", ""),
            json.dumps(resource.get("consumption_rules", [])),
        ))
        con.commit()


def delete_resource(resource_id: str) -> bool:
    with _db_connection() as con:
        cur = con.execute("DELETE FROM resources WHERE resource_id = ?", (resource_id,))
        con.commit()
        return cur.rowcount > 0


def update_resource_stock(resource_id: str, new_stock: float) -> None:
    with _db_connection() as con:
        con.execute(
            "UPDATE resources SET current_stock = ? WHERE resource_id = ?",
            (new_stock, resource_id),
        )
        con.commit()


# ── Protocol CRUD ─────────────────────────────────────────────────────────────

def get_all_protocols() -> List[dict]:
    with _db_connection() as con:
        rows = con.execute(
            "SELECT * FROM protocols ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "protocol_id":       row[0],
            "name":              row[1],
            "description":       row[2],
            "created_at":        row[3],
            "optimiser_used":    row[4],
            "results_summary":   row[5],
            "user_instructions": json.loads(row[6]),
            "notes":             row[7],
            "workflow_plan":     json.loads(row[8]) if row[8] and row[8] != "{}" else None,
        }
        for row in rows
    ]


def upsert_protocol(protocol: dict) -> None:
    with _db_connection() as con:
        con.execute("""
            INSERT OR REPLACE INTO protocols
            (protocol_id, name, description, created_at, optimiser_used,
             results_summary, user_instructions, notes, workflow_plan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            protocol["protocol_id"],
            protocol["name"],
            protocol.get("description", ""),
            protocol.get("created_at", ""),
            protocol.get("optimiser_used", ""),
            protocol.get("results_summary", ""),
            json.dumps(protocol.get("user_instructions", [])),
            protocol.get("notes", ""),
            json.dumps(protocol.get("workflow_plan")) if protocol.get("workflow_plan") else "{}",
        ))
        con.commit()


def delete_protocol(protocol_id: str) -> bool:
    with _db_connection() as con:
        cur = con.execute("DELETE FROM protocols WHERE protocol_id = ?", (protocol_id,))
        con.commit()
        return cur.rowcount > 0


def update_protocol_notes(protocol_id: str, notes: str) -> None:
    with _db_connection() as con:
        con.execute(
            "UPDATE protocols SET notes = ? WHERE protocol_id = ?",
            (notes, protocol_id),
        )
        con.commit()