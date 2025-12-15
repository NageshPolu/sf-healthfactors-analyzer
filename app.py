import streamlit as st
import requests

st.set_page_config(page_title="SF EC Live Gates", layout="wide")
st.title("SF EC Go-Live Gates (API-only)")

BACKEND = st.secrets["BACKEND_BASE"]
r = requests.get(f"{BACKEND}/metrics/latest", timeout=30).json()

if r.get("status") != "ok":
    st.warning("No snapshot yet. Run /run once, then automation will keep it updated.")
    st.stop()

m = r["metrics"]
st.caption(f"Last snapshot (UTC): {m['snapshot_time_utc']}")

c1, c2, c3 = st.columns(3)
c1.metric("Active users", m["active_users"])
c2.metric("Missing managers", f"{m['missing_manager_count']} ({m['missing_manager_pct']}%)")
c3.metric("Invalid org", f"{m['invalid_org_count']} ({m['invalid_org_pct']}%)")

st.metric("Go-Live Risk Score", f"{m['risk_score']} / 100")
