import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
MODEL_NAME   = os.getenv("MODEL_NAME", "gpt-4o-mini")

# ── Server ────────────────────────────────────────────────────────────────────
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = "maestro.db"

# ── Virtual Lab Clock ─────────────────────────────────────────────────────────
LAB_START_HOUR   = 9
LAB_START_MINUTE = 0
LAB_END_HOUR     = 17
LAB_END_MINUTE   = 0

# ── Equipment Timing (virtual minutes) ───────────────────────────────────────
VIRTUAL_MIN_SAMPLER = 2
VIRTUAL_MIN_TESTER  = 5

# ── Stochastic Parameters ─────────────────────────────────────────────────────
SAMPLER_BASE_FAIL_PROB  = 0.06   # 6% baseline failure rate
TESTER_NOISE_SIGMA      = 0.5    # Wh/kg measurement noise
MAX_TOTAL_ATTEMPTS_FACTOR = 3    # max retries = n_calls * this