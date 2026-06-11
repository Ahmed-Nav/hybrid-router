import streamlit as st
import requests

# Configuration
GATEWAY_URL = "https://ahmednav-hybrid-router.hf.space"
API_KEY = st.sidebar.text_input("Enter API Key", type="password")

st.title("🚀 Hybrid Router: Enterprise ROI Dashboard")

if API_KEY:
    headers = {"X-API-Key": API_KEY}
    response = requests.get(f"{GATEWAY_URL}/v1/analytics", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        
        # Dashboard Layout
        col1, col2 = st.columns(2)
        col1.metric("Total API Spend", f"${data['total_spend']}")
        col2.metric("Total Tokens", f"{data['total_tokens']:,}")
        
        st.write("---")
        st.subheader("Efficiency Analysis")
        st.info(f"You are optimizing for Tenant: {data['tenant_id']}")
    else:
        st.error("Could not fetch analytics. Check your API Key.")