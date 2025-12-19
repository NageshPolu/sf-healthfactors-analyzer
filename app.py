import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests
import pandas as pd
import streamlit as st


# -----------------------------
# Helpers
# -----------------------------
def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    return u.rstrip("/")


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": resp.text[:800]}


def api_get(url: str, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, payload: Dict[str, Any], timeout: int = 240) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.post(url, json=payload, timeout=timeout)
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


def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Best-effort derivation:
    https://hcm41.sapsf.com -> https://api41.sapsf.com
    https://hcm10preview.sapsf.com -> https://api10preview.sapsf.com
    If domain doesn't match known pattern, return normalized instance base.
    """
    instance_url = normalize_url(instance_url)
    if not instance_url:
        return ""

    p = urlparse(instance_url if "://" in instance_url else f"https://{instance_url}")
    host = (p.netloc or "").lower()

    # Handle hcmXX.sapsf.com / hcmXXpreview.sapsf.com patterns
    if host.startswith("hcm") and host.endswith(".sapsf.com"):
        # swap leading "hcm" -> "api"
        new_host = "api" + host[3:]
        return urlunparse((p.scheme or "https", new_host, "", "", "", "")).rstrip("/")

    # Some tenants already use api*.successfactors.* or custom domains
    return urlunparse((p.scheme or "https", host, "", "", "", "")).rstrip("/")


def on_connection_change():
    # Force refresh whenever backend/instance/api changes
    st.session_state["force_refresh"] = True
    # Clear last shown snapshot to avoid confusing stale display
    st.session_state.pop("last_metrics", None)
    st.session_state.pop("last_snapshot_time", None)


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - EC Health Check", layout="wide")
st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

with st.sidebar:
    st.header("Connection")

    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input(
        "Backend URL",
        value=st.session_state.get("backend_url", default_backend),
        placeholder="https://your-render-backend",
        key="backend_url",
        on_change=on_connection_change,
    )
    backend_url = normalize_url(backend_url)

    st.divider()
    st.subheader("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        placeholder="https://hcm41.sapsf.com",
        key="instance_url",
        on_change=on_connection_change,
    )
    instance_url = normalize_url(instance_url)

    derived_api = derive_api_base_from_instance(instance_url) if instance_url else ""
    st.text_input(
        "Derived API base URL",
        value=derived_api or "",
        disabled=True,
        key="derived_api",
    )

    # IMPORTANT: default should be EMPTY so you don't accidentally keep old tenant
    api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_override", ""),
        placeholder="Leave empty to use derived API base",
        key="api_override",
        on_change=on_connection_change,
    )
    api_override = normalize_url(api_override)

    api_base_url = api_override or derived_api

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")
    st.caption(f"Using API base: **{api_base_url or '—'}**")

    st.divider()
    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

    st.divider()
    show_debug = st.toggle("Show debug (recommended while fixing)", value=True)

status_box = st.empty()

# Guardrails
if not backend_url:
    status_box.warning("Enter your Render backend URL to continue.")
    st.stop()

if not instance_url:
    status_box.warning("Enter your SuccessFactors Instance URL to continue.")
    st.stop()

if not api_base_url:
    status_box.warning("Could not derive API base URL. Provide API base override.")
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

# Run now (THIS is what ties instance -> api_base to backend)
if run_clicked:
    payload = {"instance_url": instance_url, "api_base_url": api_base_url}
    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", payload=payload, timeout=300)

    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        # If backend is fixed correctly, you will see the REAL reason here (401/403/404/500)
        st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")
        if show_debug:
            st.subheader("Run debug")
            st.json({"request": payload, "response": out})
        st.stop()

# Auto refresh / manual refresh
if refresh_clicked:
    st.session_state["force_refresh"] = True

if auto_refresh:
    now = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now

# Always load latest snapshot FOR THIS INSTANCE
# This prevents showing “old url” snapshots
metrics_url = f"{backend_url}/metrics/latest?instance_url={requests.utils.quote(instance_url)}"
ok_m, code_m, payload = api_get(metrics_url, timeout=30)

if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    if show_debug:
        st.subheader("Metrics debug")
        st.json({"metrics_url": metrics_url, "payload": payload})
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet for this instance. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# Save last snapshot (helps detect stale state)
st.session_state["last_metrics"] = metrics
st.session_state["last_snapshot_time"] = snapshot_time

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

# Helpful context lines (if backend returns them)
inst_line = metrics.get("instance_url") or instance_url
api_line = metrics.get("api_base_url") or api_base_url
st.caption(f"Instance: {inst_line}  |  API base: {api_line}")

status_source = metrics.get("employee_status_source")
cont_source = metrics.get("contingent_source")
if status_source or cont_source:
    st.caption(f"Employee status source: {status_source or 'unknown'} • Contingent source: {cont_source or 'unknown'}")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce"])

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
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

if show_debug:
    st.divider()
    st.subheader("Debug")
    st.json(
        {
            "backend_url": backend_url,
            "instance_url": instance_url,
            "derived_api_base": derived_api,
            "api_override": api_override,
            "api_base_used": api_base_url,
            "metrics_endpoint": metrics_url,
        }
    )
