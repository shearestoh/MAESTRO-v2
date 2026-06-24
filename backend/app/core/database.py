"""
SQLite database for storing experimental evaluations.

Why SQLite?
- Zero config, single file, perfect for a research prototype
- The agent can query it with SQL via the query_database tool
- Easy to inspect with DB Browser for SQLite
"""
import sqlite3
from app.core.config import DB_PATH

# Schema description injected into the LLM system prompt
# so the agent knows what it can query
DB_SCHEMA = (
    "Table: evaluations\n"
    "Columns:\n"
    "  id              INTEGER — auto-increment primary key\n"
    "  power_W         REAL    — discharge power in watts\n"
    "  active_material REAL    — active material wt%\n"
    "  porosity        REAL    — porosity %\n"
    "  specific_energy REAL    — measured specific energy (Wh/kg)\n"
    "  timestamp       TEXT    — lab clock time (HH:MM)\n"
)


def init_db():
    """Drop and recreate the evaluations table (used on reset)."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS evaluations")
    cur.execute("""
        CREATE TABLE evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            power_W         REAL NOT NULL,
            active_material REAL NOT NULL,
            porosity        REAL NOT NULL,
            specific_energy REAL NOT NULL,
            timestamp       TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def ensure_db():
    """Create the table if it doesn't exist (used on startup)."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            power_W         REAL NOT NULL,
            active_material REAL NOT NULL,
            porosity        REAL NOT NULL,
            specific_energy REAL NOT NULL,
            timestamp       TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def write_evaluation(power_W: float, am: float, por: float,
                     energy: float, timestamp: str):
    """Write one successful experiment result to the database."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO evaluations (power_W, active_material, porosity, specific_energy, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (power_W, am, por, energy, timestamp),
    )
    con.commit()
    con.close()


def query_database(sql: str, max_rows: int = 100) -> dict:
    """
    Execute a read-only SELECT query.
    The agent calls this tool to answer questions like
    'what was the best result at 150W?'
    """
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
        rows     = cur.fetchall()
        con.close()
        return {"status": "ok", "columns": columns, "rows": [list(r) for r in rows], "n_rows": len(rows)}
    except sqlite3.OperationalError as e:
        return {"status": "error", "message": f"Database error: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}