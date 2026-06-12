# database.py
import os
import hashlib
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String, primary_key=True, index=True)
    api_key = Column(String, unique=True, index=True)
    plan_tier = Column(String, default="BASIC")
    is_active = Column(Boolean, default=True)
    
    routing_mode = Column(String, default="SMART")           
    fallback_provider = Column(String, default="gemini")
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "dashboard_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)                            
    role = Column(String, default="DEVELOPER")                
    
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")

class UsageLog(Base):
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True)
    model_used = Column(String)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    cost_incurred = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)

def hash_api_key(key: str) -> str:
    """Cryptographic fingerprint engine ensuring zero plain-text leaks of consumer API keys."""
    return hashlib.sha256(key.strip().encode('utf-8')).hexdigest()

def hash_password(password: str) -> str:
    """Encrypts cleartext dashboard credentials for storage isolation."""
    return hashlib.sha256(password.strip().encode('utf-8')).hexdigest()

def log_request(tenant_id, model, p_tokens, c_tokens, cost):
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