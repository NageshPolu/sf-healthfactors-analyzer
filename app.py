import os
import json
import time
from typing import Any, Dict, Tuple, Optional

import requests
import streamlit as st
import pandas as pd


# -----------------------------
# Helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    u = u.rstrip("/")
    return u


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": resp.text[:500]}


def api_get(url: str, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, timeout: int = 120) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.post(url, json={}, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def show_table(title: str, rows: Any):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def metric_card(label: str, value: Any, help_text: Optional[str] = None):
    v = value if value is not None else 0
    st.metric(label, v, help=help_text)


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="SuccessFactors EC Go-Live Gates", layout="wide")

st.title("✅ SuccessFactors EC Go-Live Gates (Streamlit UI + Render API)")

with st.sidebar:
    st.header("Connection")
    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input("Backend URL", value=default_backend, placeholder="https://your-render-backend")

    backend_url = normalize_base_url(backend_url)

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

    st.divider()
    st.header("PDF export")
    include_samples_pdf = st.toggle("Include samples in PDF", value=False)

# Status banner
status_box = st.empty()

if not backend_url:
    status_box.warning("Enter your Render backend URL to continue.")
    st.stop()

# Health check
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok:
    status_box.success("Backend reachable ✅")
else:
    msg = data.get("detail") or data.get("message") or "Backend not reachable"
    status_box.error(f"Backend not healthy (HTTP {code}): {msg}")
    st.stop()

# Actions row
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

# Run now
if run_clicked:
    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", timeout=240)
    if ok_run:
        st.success("Run completed ✅")
    else:
        st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")

# Always refresh snapshot after a run, or on refresh button
if run_clicked or refresh_clicked:
    st.session_state["force_refresh"] = True

# Auto-refresh loop
if auto_refresh:
    # simple timer tick (no infinite loops)
    now = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now

# Load latest metrics
if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", timeout=30)
if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# KPI row
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)

with k1:
    metric_card("Active users", as_int(metrics.get("active_users")))
with k2:
    metric_card("EmpJob rows", as_int(metrics.get("empjob_rows") or metrics.get("current_empjob_rows")))
with k3:
    metric_card("Contingent workers", as_int(metrics.get("contingent_workers")))
with k4:
    metric_card("Inactive users", as_int(metrics.get("inactive_users")))
with k5:
    metric_card("Missing managers", as_int(metrics.get("missing_manager_count")))
with k6:
    metric_card("Invalid org", as_int(metrics.get("invalid_org_count")))
with k7:
    metric_card("Missing emails", as_int(metrics.get("missing_email_count")))
with k8:
    metric_card("Risk score", as_int(metrics.get("risk_score")))

st.caption(f"Snapshot UTC: {snapshot_time}")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "🔎 Raw JSON"])

with tab1:
    show_table("Missing emails (sample)", metrics.get("missing_email_sample"))
    show_table("Duplicate emails (sample)", metrics.get("duplicate_email_sample"))

with tab2:
    show_table("Invalid org assignments (sample)", metrics.get("invalid_org_sample"))
    st.subheader("Missing org field counts")
    counts = metrics.get("org_missing_field_counts") or {}
    if counts:
        st.dataframe(pd.DataFrame([counts]), use_container_width=True, hide_index=True)
    else:
        st.info("No org missing-field breakdown available.")

with tab3:
    show_table("Missing managers (sample)", metrics.get("missing_manager_sample"))
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

with tab4:
    st.json(metrics)

# NOTE: PDF export can be added here if you want; keeping UI clean (no debug output).
