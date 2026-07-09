"""
Local-only preview launcher. Sets throwaway env vars BEFORE importing main/uvicorn
so the real .env (which points at production Postgres) is never loaded here —
python-dotenv's load_dotenv() does not override already-set env vars by default.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

os.environ["DATABASE_URL"] = "sqlite:///./preview.db"
os.environ["JWT_SECRET"] = "preview_jwt_secret_at_least_32_bytes_long_xx"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "preview_secret"

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=7860, reload=False)
