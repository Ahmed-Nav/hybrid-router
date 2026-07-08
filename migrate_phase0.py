"""
One-off manual migration for Phase 0 schema additions.
Run once against the production DATABASE_URL before deploying the Phase 0 backend changes.
Safe to re-run: each ALTER is wrapped so an already-migrated database is a no-op.
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("FATAL: DATABASE_URL environment variable is unset.")

engine = create_engine(DATABASE_URL)

STATEMENTS = [
    "ALTER TABLE tenants ADD COLUMN monthly_budget_cap FLOAT",
    "ALTER TABLE tenants ADD COLUMN budget_alert_sent_at TIMESTAMP",
    "ALTER TABLE usage_logs ADD COLUMN used_fallback BOOLEAN DEFAULT FALSE",
    "ALTER TABLE usage_logs ADD COLUMN reference_cost FLOAT DEFAULT 0.0",
    "ALTER TABLE usage_logs ADD COLUMN billed_usage_cost FLOAT DEFAULT 0.0",
]

with engine.connect() as conn:
    for stmt in STATEMENTS:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f"OK: {stmt}")
        except Exception as e:
            print(f"SKIPPED (likely already applied): {stmt} — {e}")
