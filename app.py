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
url = f"{base_url}/odata/v2/PerPerson?$top=1&$inlinecount=allpages"

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
