import streamlit as st
import requests
from requests.auth import HTTPBasicAuth

st.title("SF Live Risk Analyzer")

# --- Read secrets ---
base_url = st.secrets["SF_BASE_URL"]
username = st.secrets["SF_USERNAME"]
password = st.secrets["SF_PASSWORD"]

st.info("Connecting to SuccessFactors (read-only)...")

# --------------------------------------------------
# STEP 1: Get TOTAL USER COUNT (already working)
# --------------------------------------------------
user_url = (
    f"{base_url}/odata/v2/PerPerson"
    "?$top=1"
    "&$inlinecount=allpages"
    "&$format=json"
)

user_response = requests.get(
    user_url,
    auth=HTTPBasicAuth(username, password)
)

if user_response.status_code != 200:
    st.error("❌ Failed to fetch user count")
    st.text(user_response.text)
    st.stop()

user_data = user_response.json()
user_count = user_data["d"]["__count"]

st.success("✅ Live SuccessFactors connection successful")
st.metric("Total Users (Live)", user_count)

# --------------------------------------------------
# STEP 2: Get PERMISSION METADATA (THIS IS meta_url)
# --------------------------------------------------
meta_url = (
    f"{base_url}/odata/v2/getPermissionMetadata"
    "?locale=en_US"
    "&$format=json"
)

meta_response = requests.get(
    meta_url,
    auth=HTTPBasicAuth(username, password)
)

if meta_response.status_code != 200:
    st.error("❌ Failed to fetch permission metadata")
    st.text(meta_response.text)
    st.stop()

meta_data = meta_response.json()

# Extract unique roleIds
# Handle different SF response shapes for function imports
d_block = meta_data.get("d")

if isinstance(d_block, list):
    records = d_block
elif isinstance(d_block, dict):
    records = d_block.get("results") or d_block.get("value") or []
else:
    records = []

if not records:
    st.warning("⚠️ Permission metadata returned no roles")
else:
    role_ids = {
        r.get("roleId")
        for r in records
        if isinstance(r, dict) and r.get("roleId")
    }

    st.metric("Permission Roles (Live)", len(role_ids))

