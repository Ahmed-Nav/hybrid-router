# database.py
import os
import hmac
import hashlib
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("FATAL: DATABASE_URL environment variable is unset. Cannot start application.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
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

def hash_password(password: str, salt: bytes = None) -> str:
    """Encrypts cleartext dashboard credentials for storage isolation using PBKDF2."""
    import secrets
    if salt is None:
        salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.strip().encode('utf-8'), salt, 100000)
    return f"{salt.hex()}${pwd_hash.hex()}"

def verify_password(password: str, hashed_value: str) -> bool:
    """Verifies a plain password against its PBKDF2 salt and hash representation."""
    try:
        salt_hex, hash_hex = hashed_value.split('$')
        salt = bytes.fromhex(salt_hex)
        new_hash = hashlib.pbkdf2_hmac('sha256', password.strip().encode('utf-8'), salt, 100000)
        return hmac.compare_digest(new_hash.hex(), hash_hex)
    except Exception:
        return False

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

import secrets

def provision_new_tenant(db_session, tenant_id: str, plan_tier: str) -> str:
    """
    Programmatically creates a new B2B customer profile and generates 
    a unique, cryptographically secure root API key.
    """
    # 1. Generate a secure random token identifier string
    raw_secret_key = f"sk_live_{secrets.token_hex(16)}"
    hashed_key = hash_api_key(raw_secret_key)
    
    # 2. Inject a new tenant entry into the relational schema
    new_tenant = Tenant(
        id=tenant_id,
        api_key=hashed_key,
        plan_tier=plan_tier.upper(),
        routing_mode="SMART",  # High-ROI default routing protocol
        fallback_provider="groq",
        is_active=True
    )
    
    db_session.add(new_tenant)
    db_session.commit()
    
    print(f"📦 [PROVISIONER] Programmatically deployed tenant profile: {tenant_id} ({plan_tier})")
    return raw_secret_key