# seed.py
from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, Tenant, User, hash_api_key, hash_password

def seed_enterprise_data():
    db = SessionLocal()
    try:
        print("🌱 Starting Database Provisioning sequence...")

        # 1. Drop and recreate all tables to align database schema with local models
        from database import Base, engine
        print("🧹 Dropping existing tables to refresh schema...")
        Base.metadata.drop_all(bind=engine)
        print("🔨 Recreating tables from models...")
        Base.metadata.create_all(bind=engine)

        # 2. Provision Tenants with different "LLM Option" defaults
        basic_tenant = Tenant(
            id="small_biz_corp",
            api_key=hash_api_key("sk_basic_token_111"),
            plan_tier="BASIC",
            routing_mode="SMART"
        )
        
        premium_tenant = Tenant(
            id="enterprise_analytics_gmbh",
            api_key=hash_api_key("sk_premium_token_999"),
            plan_tier="PREMIUM",
            routing_mode="PERFORMANCE" # Starts on premium tier track
        )
        
        db.add_all([basic_tenant, premium_tenant])
        db.commit()

        # 3. Provision Dashboard Accounts with specific Role Hierarchies
        super_admin = User(
            username="superadmin",
            password_hash=hash_password("master_password_2026"),
            role="SUPER_ADMIN",
            tenant_id=None # Super Admins transcend individual corporate borders
        )

        tenant_admin = User(
            username="cto_enterprise",
            password_hash=hash_password("secure_admin_pass"),
            role="TENANT_ADMIN",
            tenant_id="enterprise_analytics_gmbh"
        )

        developer_user = User(
            username="dev_engineer_1",
            password_hash=hash_password("dev_pass_123"),
            role="DEVELOPER",
            tenant_id="enterprise_analytics_gmbh"
        )

        db.add_all([super_admin, tenant_admin, developer_user])
        db.commit()
        
        print("✅ Production-grade data matrix provisioned successfully!")
        print("\n--- SAVE THESE API KEYS FOR LIVE TESTING ---")
        print("Basic App API Key:  sk_basic_token_111")
        print("Premium App API Key: sk_premium_token_999")
        
    except Exception as e:
        print(f"❌ Provisioning failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_enterprise_data()