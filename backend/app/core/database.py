"""
Persistent store for experimental evaluations.

Schema uses a generic design: condition_name/condition_value capture the
primary operating condition, and a JSON 'parameters' column stores all
free parameters. This makes the schema instrument-agnostic.
"""
import json
import sqlite3
from typing import Any, Dict, List, Optional

from app.core.config import DB_PATH

DB_SCHEMA = (
    "Table: evaluations\n"
    "Columns:\n"
    "  id               INTEGER — auto-increment primary key\n"
    "  condition_name   TEXT    — name of the operating condition (e.g. 'power_W')\n"
    "  condition_value  REAL    — value of the operating condition\n"
    "  parameters       TEXT    — JSON object of free parameter name→value pairs\n"
    "  objective_name   TEXT    — name of the measured objective (e.g. 'specific_energy')\n"
    "  objective_value  REAL    — measured objective value\n"
    "  timestamp        TEXT    — ISO timestamp of the measurement\n"
)


def init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS evaluations")
    cur.execute("""
        CREATE TABLE evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_name  TEXT    NOT NULL,
            condition_value REAL    NOT NULL,
            parameters      TEXT    NOT NULL DEFAULT '{}',
            objective_name  TEXT    NOT NULL,
            objective_value REAL    NOT NULL,
            timestamp       TEXT    NOT NULL
        )
    """)
    con.commit()
    con.close()


def ensure_db() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_name  TEXT    NOT NULL,
            condition_value REAL    NOT NULL,
            parameters      TEXT    NOT NULL DEFAULT '{}',
            objective_name  TEXT    NOT NULL,
            objective_value REAL    NOT NULL,
            timestamp       TEXT    NOT NULL
        )
    """)
    con.commit()
    con.close()


def write_evaluation(
    condition_name:  str,
    condition_value: float,
    parameters:      Dict[str, float],
    objective_name:  str,
    objective_value: float,
    timestamp:       str,
) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO evaluations "
        "(condition_name, condition_value, parameters, objective_name, objective_value, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            condition_name,
            condition_value,
            json.dumps(parameters),
            objective_name,
            objective_value,
            timestamp,
        ),
    )
    con.commit()
    con.close()


def query_database(sql: str, max_rows: int = 100) -> dict:
    sql = sql.strip()
    if not sql.upper().startswith("SELECT"):
        return {"status": "error", "message": "Only SELECT statements are permitted."}

    if "LIMIT" not in sql.upper():
        sql = f"{sql} LIMIT {max_rows}"

    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        cur = con.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows    = cur.fetchall()
        con.close()
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