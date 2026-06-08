import os
from sqlalchemy import Column, Integer, String, Float, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

# Get your Neon/Supabase URL from HF Secrets
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UsageLog(Base):
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True)
    model_used = Column(String)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    cost_incurred = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

# Ensure table exists
Base.metadata.create_all(bind=engine)

def log_request(tenant_id, model, p_tokens, c_tokens, cost):
    """Synchronous logging function for now; 
    easy to call from main.py."""
    db = SessionLocal()
    try:
        log = UsageLog(
            tenant_id=tenant_id, 
            model_used=model, 
            prompt_tokens=p_tokens, 
            completion_tokens=c_tokens, 
            cost_incurred=cost
        )
        db.add(log)
        db.commit()
    finally:
        db.close()