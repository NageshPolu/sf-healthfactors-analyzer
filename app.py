import streamlit as st
import requests
from requests.auth import HTTPBasicAuth

st.title("SF Live Risk Analyzer")

# Read secrets
base_url = st.secrets["SF_BASE_URL"]
username = st.secrets["SF_USERNAME"]
password = st.secrets["SF_PASSWORD"]

st.info("Connecting to SuccessFactors (read-only)...")

# Correct OData call for user count
url = f"{base_url}/odata/v2/PerPerson?$top=1&$inlinecount=allpages&$format=json"


response = requests.get(
    url,
    auth=HTTPBasicAuth(username, password)
)

if response.status_code == 200:
    data = response.json()
    user_count = data["d"]["__count"]

    st.success("✅ Live SuccessFactors connection successful")
    st.metric("Total Users (Live)", user_count)

else:
    st.error("❌ Connection failed")
    st.text(response.text)

# Pull Permission Roles (RBP) - LIVE
rbp_url = f"{base_url}/odata/v2/PermissionRole?$format=json"

rbp_response = requests.get(
    rbp_url,
    auth=HTTPBasicAuth(username, password)
)

if rbp_response.status_code == 200:
    rbp_data = rbp_response.json()
    role_count = len(rbp_data["d"]["results"])
    st.metric("Permission Roles (Live)", role_count)
else:
    st.warning("⚠️ Unable to fetch Permission Roles")
