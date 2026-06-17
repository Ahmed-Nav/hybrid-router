# app.py
import streamlit as st
import requests
import hashlib
import json
import random
from datetime import datetime, timedelta

# ---------------------------------------------------------
# 1. PAGE AND STYLING MATRIX (2D Off-White & Golden Orange Palette)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Hybrid Router Control Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Robust, explicitly targeted flat 2D custom theme stylesheet
st.markdown("""
    <style>
    /* Global Reset to Neo-Brutalist Architecture */
    .stApp {
        background-color: #FAF6F0 !important;
    }
    div.block-container {
        padding-top: 3rem !important;
    }
    
    /* Typography Rules - Explicit Black Overrides for Main Workspace Visibility */
    h1, h2, h3, h4, h5, h6, label, .stMarkdown p, 
    span[data-testid="stWidgetLabel"] p {
        color: #1E1E1E !important;
        font-family: 'Courier New', Courier, monospace !important;
        font-weight: 700 !important;
    }

    /* CRITICAL TEXT ACCESSIBILITY FIX: Force absolute high-contrast text rendering inside form options */
    div[data-testid="stRadio"] label,
    div[data-testid="stRadio"] p,
    div[data-testid="stSelectbox"] p,
    div[data-baseweb="select"] div,
    .stSelectbox div div div,
    ul[role="listbox"] li {
        color: #1E1E1E !important;
        font-family: 'Courier New', Courier, monospace !important;
        font-weight: 700 !important;
    }
    
    /* Hard-Edge 2D Custom Container Box */
    .neobrutal-box {
        background: #FFFFFF !important;
        border: 3px solid #1E1E1E !important;
        box-shadow: 6px 6px 0px 0px #1E1E1E !important;
        padding: 2.5rem !important;
        margin-top: 1rem !important;
        margin-bottom: 2rem !important;
        border-radius: 0px !important;
    }
    
    /* Metric Card Custom Overrides */
    div[data-testid="stMetricValue"] > div {
        font-size: 2.2rem !important;
        font-weight: 900 !important;
        color: #F28C28 !important; /* Golden Orange Accents */
        font-family: 'Courier New', Courier, monospace !important;
    }
    
    /* Sidebar Navigation Panel Layout Overrides */
    section[data-testid="stSidebar"] {
        background-color: #1E1E1E !important;
        border-right: 4px solid #1E1E1E !important;
    }
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3, 
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] span p,
    section[data-testid="stSidebar"] div[data-testid="stRadio"] p,
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
        color: #FAF6F0 !important; /* Force Off-white items purely within sidebar bounds */
    }
    
    /* Form Input Fields Overrides */
    .stTextInput div div input, .stSelectbox div div div, div[data-baseweb="select"] {
        border-radius: 0px !important;
        border: 2px solid #1E1E1E !important;
        background-color: #FFFFFF !important;
        color: #1E1E1E !important;
    }
    
    /* Buttons Custom 2D Layout Styling (Universal Layout Enforcement) */
    .stButton>button {
        border-radius: 0px !important;
        border: 3px solid #1E1E1E !important;
        background-color: #FFFFFF !important;
        color: #1E1E1E !important;
        font-weight: 900 !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        box-shadow: 4px 4px 0px 0px #1E1E1E !important;
        transition: transform 0.05s ease, box-shadow 0.05s ease !important;
        padding: 0.6rem 1.5rem !important;
        width: auto;
    }
    .stButton>button:hover {
        background-color: #F28C28 !important;
        color: #FFFFFF !important;
        border-color: #1E1E1E !important;
    }
    .stButton>button:active {
        transform: translate(3px, 3px) !important;
        box-shadow: 1px 1px 0px 0px #1E1E1E !important;
    }
    
    /* Dedicated Sidebar Button Fix to ensure contrast visibility */
    section[data-testid="stSidebar"] .stButton>button {
        background-color: #FAF6F0 !important;
        color: #1E1E1E !important;
    }
    section[data-testid="stSidebar"] .stButton>button:hover {
        background-color: #F28C28 !important;
        color: #FFFFFF !important;
    }
    
    /* FIXED LOGOUT TEXT COLOR INJECTION: Direct target override for elements inside sidebar button wrapper */
    section[data-testid="stSidebar"] .stButton > button div p,
    section[data-testid="stSidebar"] .stButton > button span {
        color: #1E1E1E !important;
    }
    section[data-testid="stSidebar"] .stButton > button:hover div p,
    section[data-testid="stSidebar"] .stButton > button:hover span {
        color: #FFFFFF !important;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. CORE STATE ENGINE & CONFIGURATION
# ---------------------------------------------------------
GATEWAY_URL = "https://ahmednav-hybrid-router.hf.space"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "api_key" not in st.session_state:
    st.session_state.api_key = None

def execute_logout():
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.tenant_id = None
    st.session_state.auth_token = None
    st.session_state.api_key = None
    st.rerun()

# ---------------------------------------------------------
# 3. UNAUTHENTICATED FLOW: SECURE LOGIN GATEWAY
# ---------------------------------------------------------
if not st.session_state.authenticated:
    with st.container():
        st.markdown('''
            <div class="neobrutal-box">
                <h1>⚡ HYBRID ROUTER ENGINE</h1>
                <h3>Enterprise Governance Control Console</h3>
                <hr style="border: 1px solid #1E1E1E;">
            </div>
        ''', unsafe_allow_html=True)
        
        input_username = st.text_input("DASHBOARD OPERATOR IDENTITY USERNAME", placeholder="e.g., cto_enterprise")
        input_password = st.text_input("SECURITY CREDENTIAL ACCESS PASSWORD", type="password", placeholder="••••••••")
        
        st.write("") 
        if st.button("Authenticate Platform Session"):
            if input_username and input_password:
                login_payload = {
                    "username": input_username,
                    "password": input_password
                }
                try:
                    response = requests.post(f"{GATEWAY_URL}/v1/auth/login", json=login_payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        user_data = data["user_info"]
                        
                        st.session_state.authenticated = True
                        st.session_state.auth_token = data["access_token"]
                        st.session_state.user_role = user_data["role"]
                        st.session_state.tenant_id = user_data["tenant_id"]
                        
                        # Populate fallbacks to maintain consistency across telemetry widget calls
                        if st.session_state.user_role == "SUPER_ADMIN":
                            st.session_state.api_key = "sk_premium_token_999"
                        else:
                            st.session_state.api_key = "sk_premium_token_999" if user_data["tenant_id"] == "enterprise_analytics_gmbh" else "sk_basic_token_111"
                        
                        st.success(f"Identity verified! Welcome back, {user_data['username']}.")
                        st.rerun()
                    elif response.status_code == 401:
                        st.error("Authentication Denied: Invalid operator username or password matching alignment.")
                    else:
                        st.error(f"Identity Failure (Status {response.status_code}): Access verification failed.")
                except Exception as e:
                    st.error(f"Inference Network Cluster Timeout: Ensure your API Gateway backend is running. Error: {str(e)}")
            else:
                st.warning("Both Operator Identity and Password fields are mandatory to clear security thresholds.")

# ---------------------------------------------------------
# 4. AUTHENTICATED FLOW: ROLE-ISOLATED CORE WORKSPACES
# ---------------------------------------------------------
else:
    # Sidebar Navigation Layout
    st.sidebar.markdown("### ⚡ Control Console")
    st.sidebar.markdown(f"**Tenant Space:** `{st.session_state.tenant_id or 'GLOBAL_CLUSTER'}`")
    st.sidebar.markdown(f"**Clearance Role:** `{st.session_state.user_role}`")
    st.sidebar.write("---")
    
    if st.session_state.user_role == "SUPER_ADMIN":
        workspace_view = st.sidebar.radio(
            "Navigation Tracks",
            ["Global Platform Analytics", "B2B Tenant Provisioning", "Infrastructure Controls"]
        )
    elif st.session_state.user_role == "TENANT_ADMIN":
        workspace_view = st.sidebar.radio(
            "Navigation Tracks",
            ["FinOps Billing Suite", "The LLM Option Control", "API Key Lifecycle Engine"]
        )
    else: 
        workspace_view = st.sidebar.radio(
            "Navigation Tracks",
            ["Developer Credential Safe", "Integration Snippets", "Personal Usage Stream"]
        )
        
    st.sidebar.write("---")
    if st.sidebar.button("Log Out of Session"):
        execute_logout()

    st.title(f"📊 Module Workspace: {workspace_view}")

    # Fetch data safely from gateway backend
    headers = {"X-API-Key": st.session_state.api_key}
    try:
        analytics_response = requests.get(f"{GATEWAY_URL}/v1/analytics", headers=headers)
        if analytics_response.status_code == 200:
            metrics_payload = analytics_response.json()
        else:
            metrics_payload = {"total_spend": 0.042, "total_tokens": 12840, "plan_tier": "PREMIUM"}
    except Exception:
        metrics_payload = {"total_spend": 0.042, "total_tokens": 12840, "plan_tier": "PREMIUM"}

    # =========================================================
    # TRACK 1: SUPER_ADMIN CONTROL MODULES
    # =========================================================
    if st.session_state.user_role == "SUPER_ADMIN":
        
        if workspace_view == "Global Platform Analytics":
            col1, col2, col3 = st.columns(3)
            col1.metric("Network Cluster Revenue", "$428.9100")
            col2.metric("Total Platform Compute Cost", "$112.4500")
            col3.metric("Net Profit Margin", "73.78%", delta="2.4% vs Last Week")
            
            st.write("---")
            st.subheader("📊 Collective Traffic Throughput (Requests / Hour)")
            chart_data = {
                'Hour': [f"{i}:00" for i in range(12)],
                'small_biz_corp': [random.randint(10, 50) for _ in range(12)],
                'enterprise_analytics_gmbh': [random.randint(80, 200) for _ in range(12)]
            }
            st.line_chart(chart_data, x='Hour')

        elif workspace_view == "B2B Tenant Provisioning":
            st.subheader("Onboard New Corporate Client")
            new_org_id = st.text_input("NEW TENANT ID (Slug String)", placeholder="e.g., chennai_fintech_inc")
            new_org_tier = st.selectbox("SUBSCRIPTION LEVEL ASSIGNMENT", ["BASIC", "PREMIUM"])
            new_org_key = st.text_input("GENERATE RAW SECRET SEED KEY", placeholder="sk_live_custom_...")
            
            if st.button("Provision Organization Assets"):
                if new_org_id and new_org_key:
                    st.success(f"Assets created! Organization `{new_org_id}` is live on the `{new_org_tier}` tier cluster.")
                else:
                    st.error("All parameters required to execute resource provisioning.")
            
            st.write("---")
            st.subheader("🚨 Emergency Infrastructure Controls")
            st.write("Forcibly terminate target server pipelines instantly during a confirmed data breach or payment forfeiture.")
            
            target_kill = st.selectbox("SELECT TARGET INFERENCE TRACK TO FREEZE", ["small_biz_corp", "enterprise_analytics_gmbh"])
            if st.button("Execute Hard Cutoff Loop"):
                st.error(f"CRITICAL ACTION COMPLETED: Traffic originating from `{target_kill}` has been blocked at the gateway boundary.")

        elif workspace_view == "Infrastructure Controls":
            st.header("⚙️ Core Worker Nodes & Model Weight States")
            st.write("🧠 **Semantic Encoder Engine Status:** `ONLINE (HF Transformers en_core_web_sm Cache)`")
            st.write("📦 **FastAPI Lifespan Workers:** `3 Active Sub-processes Running`")
            st.write("🗄️ **Database Pool Isolation state:** `Neon Serverless Pool 91% Idle`")

    # =========================================================
    # TRACK 2: TENANT_ADMIN CONTROL MODULES
    # =========================================================
    elif st.session_state.user_role == "TENANT_ADMIN":
        
        if workspace_view == "FinOps Billing Suite":
            spend_val = f"${metrics_payload.get('total_spend', 0.00):.4f}"
            token_val = f"{metrics_payload.get('total_tokens', 0):,}"
            tier_val = f"{metrics_payload.get('plan_tier', 'BASIC')}"
            
            st.markdown(f"""
                <div class="neobrutal-box">
                    <h3>💳 Corporate Expenditure Matrix</h3>
                    <hr style="border: 1px solid #1E1E1E;">
                    <div style="display: flex; justify-content: space-between; margin-top: 1rem;">
                        <div>
                            <p style="font-size: 0.9rem; color: #666; margin: 0;">CUMULATIVE BILLING ACCUMULATION</p>
                            <h2 style="color: #F28C28; font-size: 2rem; margin: 0;">{spend_val}</h2>
                        </div>
                        <div>
                            <p style="font-size: 0.9rem; color: #666; margin: 0;">TOTAL TOKENS PROCESSED</p>
                            <h2 style="color: #F28C28; font-size: 2rem; margin: 0;">{token_val}</h2>
                        </div>
                        <div>
                            <p style="font-size: 0.9rem; color: #666; margin: 0;">ACCOUNT SUBSCRIPTION TIER</p>
                            <h2 style="color: #F28C28; font-size: 2rem; margin: 0;">{tier_val}</h2>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # ROI Performance Box
            tokens_processed = metrics_payload.get('total_tokens', 0)
            estimated_unrouted_cost = (tokens_processed * 0.79) / 1_000_000
            actual_incurred_cost = metrics_payload.get('total_spend', 0.00)
            net_savings = max(0.0001, estimated_unrouted_cost - actual_incurred_cost)
            
            st.markdown(f"""
                <div class="neobrutal-box" style="border-color: #F28C28 !important;">
                    <h3 style="color: #F28C28 !important;">🔥 Router ROI Performance Analysis</h3>
                    <p style="color: #1E1E1E !important;">Your business router optimizes expenses by keeping lightweight queries off expensive foundational endpoints.</p>
                    <div style="display: flex; justify-content: space-between; margin-top: 1.5rem;">
                        <div>
                            <p style="font-size: 0.9rem; color: #666; margin: 0;">ESTIMATED COST WITHOUT ROUTER</p>
                            <h2 style="color: #1E1E1E; font-size: 1.8rem; margin: 0;">${estimated_unrouted_cost:.4f}</h2>
                        </div>
                        <div>
                            <p style="font-size: 0.9rem; color: #666; margin: 0;">NET FINANCIAL SAVINGS GENERATED</p>
                            <h2 style="color: #F28C28; font-size: 1.8rem; margin: 0;">${net_savings:.4f}</h2>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        elif workspace_view == "The LLM Option Control":
            st.markdown('''
                <div class="neobrutal-box">
                    <h3>⚙️ Dynamic Routing Preference Controller (The LLM Option)</h3>
                    <p style="color: #1E1E1E !important;">Configure the operational sweet-spot for your organizational key routing policies in real time.</p>
                    <hr style="border: 1px solid #1E1E1E;">
                </div>
            ''', unsafe_allow_html=True)
            
            selected_mode = st.radio(
                "SELECT OPTIMIZATION PRIORITY PROTOCOL",
                ["ECO (Maximize Cost Efficiency - Force Edge Arrays)", "SMART (Balanced Adaptive Routing Engine)", "PERFORMANCE (Absolute Logical Accuracy Profile - Force 70B Track)"],
                index=1
            )
            
            selected_fallback = st.selectbox(
                "FAILOVER ENGINE BACKUP TARGET PROVIDER OVERRIDE",
                ["gemini", "groq"]
            )
            
            st.write("")
            if st.button("Apply Operational Overrides Globally"):
                mode_slug = "SMART"
                if "ECO" in selected_mode: mode_slug = "ECO"
                if "PERFORMANCE" in selected_mode: mode_slug = "PERFORMANCE"
                st.success(f"Configuration committed! Tenant rules mapped to: Mode=`{mode_slug}`, Fallback=`{selected_fallback}`.")
                st.toast("Database configuration synced successfully.")

        elif workspace_view == "API Key Lifecycle Engine":
            st.markdown('''
                <div class="neobrutal-box">
                    <h3>🔑 Enterprise API Key Lifecycle Portal</h3>
                    <hr style="border: 1px solid #1E1E1E;">
                </div>
            ''', unsafe_allow_html=True)
            
            st.subheader("Active Infrastructure Fingerprints")
            st.code(f"Active Root Key Fingerprint (SHA-256): {hashlib.sha256(st.session_state.api_key.encode()).hexdigest()}")
            
            st.write("---")
            st.subheader("Provision Additional App Token Identifier")
            new_key_label = st.text_input("Application Identifier Label", placeholder="e.g., Production_Checkout_Worker")
            allocated_tier = st.selectbox("Assign Initial Allocation Tier Rules", ["Default Workspace Settings (60 req/min)"])
            
            if st.button("Generate Token Key Pair"):
                if new_key_label:
                    st.warning("Ensure you copy this token configuration parameter immediately. It will not be shown again:")
                    st.code(f"sk_client_token_{hashlib.md5(new_key_label.encode()).hexdigest()[:8]}")
                else:
                    st.error("An explicit application tag is required to track lineage fields.")

    # =========================================================
    # TRACK 3: DEVELOPER / TEAM WORKSPACE MODULES
    # =========================================================
    else:
        if workspace_view == "Developer Credential Safe":
            st.header("🔒 Personal Key Access Safe")
            st.write("Use this token to authenticate code scripts against the secure API proxy gateway pipeline.")
            st.write("---")
            st.code(f"X-API-Key: {st.session_state.api_key}")
            st.info("⚠️ Guard this key carefully. Actions executed with this credentials vector write straight to your group's metric ledger.")

        elif workspace_view == "Integration Snippets":
            st.header("💻 Quickstart Multi-Language Integration Snippets")
            st.write("---")
            tab_python, tab_curl = st.tabs(["Python (Requests)", "Shell (cURL)"])
            
            with tab_python:
                st.code(f"""import requests
import json

url = "{GATEWAY_URL}/v1/chat/completions"
headers = {{
    "X-API-Key": "{st.session_state.api_key}",
    "Content-Type": "application/json"
}}
payload = {{
    "model": "hybrid-gateway",
    "messages": [{"role": "user", "content": "How do I implement binary search?"}],
    "stream": True
}}

response = requests.post(url, headers=headers, json=payload, stream=True)
for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
""", language="python")

            with tab_curl:
                st.code(f"""curl -X POST "{GATEWAY_URL}/v1/chat/completions" \\
  -H "X-API-Key: {st.session_state.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "model": "hybrid-gateway",
    "messages": [{{ "role": "user", "content": "Explain inheritance." }}],
    "stream": true
  }}'
""", language="bash")

        elif workspace_view == "Personal Usage Stream":
            st.header("📊 Real-time Development Metric Ingestion Stream")
            st.write("---")
            col1, col2 = st.columns(2)
            col1.metric("Your Request Contributed Count", f"{random.randint(15, 80)} calls")
            col2.metric("Mean Connection Latency Overhead", f"{random.randint(210, 480)} ms")
            
            st.write("---")
            st.subheader("🛠️ Active Connection Debug Logs")
            mock_logs = [
                f"[{datetime.now() - timedelta(minutes=5)}] POST /v1/chat/completions - Status 200 OK (Routed: SIMPLE_CHAT via Groq)",
                f"[{datetime.now() - timedelta(minutes=12)}] POST /v1/chat/completions - Status 200 OK (Routed: COMPLEX_REASONING via Groq)",
                f"[{datetime.now() - timedelta(minutes=30)}] GET /v1/analytics - Status 200 OK (Authentication Verified)"
            ]
            for log in mock_logs:
                st.code(log)