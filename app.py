import os
import time
from typing import Any, Dict, Tuple, Optional

import requests
import streamlit as st
import pandas as pd


# -----------------------------
# Helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip().rstrip("/")
    return u


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": (resp.text or "")[:800]}


def api_get(url: str, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, timeout: int = 180) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.post(url, json={}, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
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


def show_counts_table(title: str, d: Dict[str, Any]):
    st.subheader(title)
    if not d:
        st.info("No data available.")
        return
    df = pd.DataFrame([{"Status": k, "Count": v} for k, v in d.items()])
    df = df.sort_values("Count", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)


def metric_card(label: str, value: Any, help_text: Optional[str] = None):
    st.metric(label, value if value is not None else 0, help=help_text)


def short_error(msg: str) -> str:
    # Avoid dumping long blobs into the UI
    msg = (msg or "").strip()
    return msg if len(msg) <= 220 else msg[:220] + "..."


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="SuccessFactors EC Go-Live Gates", layout="wide")
st.title("✅ SuccessFactors EC Go-Live Gates (Streamlit UI + Render API)")

with st.sidebar:
    st.header("Connection")
    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input(
        "Backend URL",
        value=default_backend,
        placeholder="https://your-render-backend",
    )
    backend_url = normalize_base_url(backend_url)

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider(
        "Refresh every (seconds)",
        10, 180, 30,
        disabled=not auto_refresh
    )

    st.divider()
    st.header("Display")
    show_raw_json = st.toggle("Show raw JSON (advanced)", value=False)

status_box = st.empty()

if not backend_url:
    status_box.warning("Enter your Render backend URL to continue.")
    st.stop()

# -----------------------------
# Health check
# -----------------------------
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok:
    status_box.success("Backend reachable ✅")
else:
    detail = data.get("detail") or data.get("message") or "Backend not reachable"
    status_box.error(f"Backend not healthy (HTTP {code}): {short_error(detail)}")
    with st.expander("Show error details"):
        st.write(detail)
    st.stop()

# -----------------------------
# Actions
# -----------------------------
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

if run_clicked:
    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", timeout=240)
    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        detail = out.get("detail", "Internal error")
        st.error(f"Run failed (HTTP {code_run}): {short_error(detail)}")
        with st.expander("Show error details"):
            st.write(detail)

if refresh_clicked:
    st.session_state["force_refresh"] = True

# Auto refresh (simple tick)
if auto_refresh:
    now_ts = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now_ts - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now_ts

# -----------------------------
# Load latest metrics
# -----------------------------
if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", timeout=30)
if not ok_m:
    detail = payload.get("detail", "Error")
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {short_error(detail)}")
    with st.expander("Show error details"):
        st.write(detail)
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# -----------------------------
# KPI row
# -----------------------------
active_users = as_int(metrics.get("active_users"))
empjob_rows = as_int(metrics.get("empjob_rows") or metrics.get("current_empjob_rows"))
inactive_users = as_int(metrics.get("inactive_users") or metrics.get("inactive_user_count"))
contingent_workers = as_int(metrics.get("contingent_workers") or metrics.get("contingent_worker_count"))
contingent_active = as_int(metrics.get("contingent_workers_active"))

missing_mgr = as_int(metrics.get("missing_manager_count"))
invalid_org = as_int(metrics.get("invalid_org_count"))
missing_email = as_int(metrics.get("missing_email_count"))
risk_score = as_int(metrics.get("risk_score"))

k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
with k1:
    metric_card("Active users", active_users, help_text="Based on EmpJob employee status (not User.status).")
with k2:
    metric_card("EmpJob rows", empjob_rows, help_text="All latest EmpJob rows (effectiveLatestChange=true).")
with k3:
    metric_card("Contingent workers", contingent_workers, help_text=f"Active contingent: {contingent_active}")
with k4:
    metric_card("Inactive users", inactive_users, help_text="Based on EmpJob employee status.")
with k5:
    metric_card("Missing managers", missing_mgr)
with k6:
    metric_card("Invalid org", invalid_org)
with k7:
    metric_card("Missing emails", missing_email, help_text="Email hygiene checked for ACTIVE employees.")
with k8:
    metric_card("Risk score", risk_score)

st.caption(f"Snapshot UTC: {snapshot_time}")

# Useful metadata (not code)
meta1, meta2, meta3 = st.columns(3)
with meta1:
    st.caption(f"Employee status source: {metrics.get('employee_status_source','-')}")
with meta2:
    st.caption(f"Contingent source: {metrics.get('contingent_source','-')}")
with meta3:
    st.caption("Samples are capped (default 200).")

# Guardrails (helps catch stale snapshots / backend mismatch)
if missing_email > 0 and not metrics.get("missing_email_sample"):
    st.warning("Missing emails count > 0 but sample is empty. Run **Run live check now** again after backend deploy.")
if inactive_users > 0 and not metrics.get("inactive_users_sample"):
    st.warning("Inactive users count > 0 but sample is empty. Run **Run live check now** again after backend deploy.")
if contingent_workers > 0 and not metrics.get("contingent_workers_sample"):
    st.warning("Contingent workers count > 0 but sample is empty. Run **Run live check now** again after backend deploy.")

# -----------------------------
# Tabs (NO CODE shown)
# -----------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce"]
)

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

with tab4:
    show_counts_table("Inactive users by employee status", metrics.get("inactive_users_by_status") or {})
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

if show_raw_json:
    st.divider()
    st.subheader("Raw JSON (advanced)")
    st.json(metrics)
