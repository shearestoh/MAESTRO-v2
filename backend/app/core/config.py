import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
MODEL_NAME   = os.getenv("MODEL_NAME", "gpt-4o-mini")

BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

DB_PATH = "maestro.db"

# Maximum total BO attempts = n_calls × this factor.
# Prevents infinite loops when sample failure rate is high.
MAX_TOTAL_ATTEMPTS_FACTOR = 3