# app.py
import os
import time
import re
from typing import Any, Dict, Tuple, Optional
from urllib.parse import urlparse

import requests
import streamlit as st
import pandas as pd


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
        return {"detail": (resp.text or "")[:500]}


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


def metric_card(label: str, value: Any, help_text: Optional[str] = None):
    v = value if value is not None else 0
    st.metric(label, v, help=help_text)


def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Derive API base URL from instance URL.
    - hcm41.sapsf.com      -> api41.sapsf.com
    - hcm41preview.sapsf.com -> api41preview.sapsf.com
    - *.successfactors.*   -> assume same host is valid base (often true)
    Otherwise: return scheme://host (best effort)
    """
    instance_url = normalize_url(instance_url)
    if not instance_url:
        return ""

    # Ensure scheme
    if not re.match(r"^https?://", instance_url, re.IGNORECASE):
        instance_url = "https://" + instance_url

    p = urlparse(instance_url)
    host = (p.hostname or "").lower()
    scheme = p.scheme or "https"

    if not host:
        return ""

    # sapsf pattern
    m = re.match(r"^hcm(\d+)(preview)?\.sapsf\.com$", host)
    if m:
        num = m.group(1)
        prev = m.group(2) or ""
        return f"{scheme}://api{num}{prev}.sapsf.com"

    # If it's already an api host on sapsf, keep it
    m2 = re.match(r"^api(\d+)(preview)?\.sapsf\.com$", host)
    if m2:
        return f"{scheme}://{host}"

    # For successfactors.* tenants, API base is usually the same host
    if "successfactors." in host:
        return f"{scheme}://{host}"

    # Fallback best-effort
    return f"{scheme}://{host}"


def metrics_latest_url(backend_url: str, instance_url: str) -> str:
    backend_url = normalize_url(backend_url)
    instance_url = normalize_url(instance_url)
    if instance_url:
        # FastAPI expects instance_url query param
        return f"{backend_url}/metrics/latest?instance_url={requests.utils.quote(instance_url, safe='')}"
    return f"{backend_url}/metrics/latest"


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - SF EC Health Check", layout="wide")
st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

# Session defaults
if "force_refresh" not in st.session_state:
    st.session_state["force_refresh"] = False
if "last_refresh_ts" not in st.session_state:
    st.session_state["last_refresh_ts"] = 0.0

with st.sidebar:
    st.header("Connection")

    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input(
        "Backend URL",
        value=default_backend,
        placeholder="https://your-render-backend",
        help="Streamlit calls this backend. Backend calls SuccessFactors.",
    )
    backend_url = normalize_url(backend_url)

    st.divider()
    st.header("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        placeholder="https://hcm41.sapsf.com",
        help="The SuccessFactors instance URL (for scoping snapshots).",
    )
    instance_url = normalize_url(instance_url)
    st.session_state["instance_url"] = instance_url

    derived_api = derive_api_base_from_instance(instance_url)
    st.text_input("Derived API base URL", value=derived_api, disabled=True)

    api_base_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_base_override", ""),
        placeholder="https://apisalesdemo2.successfactors.eu",
        help="If your credentials belong to a different tenant than the derived api*.sapsf.com host, paste the correct API base here.",
    )
    api_base_override = normalize_url(api_base_override)
    st.session_state["api_base_override"] = api_base_override

    effective_api_base = api_base_override or derived_api
    st.caption("Effective API base:")
    st.markdown(effective_api_base if effective_api_base else "_(not set)_")

    st.divider()
    st.header("Refresh")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

    st.divider()
    st.header("Display")
    show_raw = st.toggle("Show raw JSON (advanced)", value=False)

status_box = st.empty()

# Must have backend
if not backend_url:
    status_box.warning("Enter your Backend URL to continue.")
    st.stop()

# Health check
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok:
    status_box.success("Backend reachable ✅")
else:
    msg = data.get("detail") or data.get("message") or "Backend not reachable"
    status_box.error(f"Backend not healthy (HTTP {code}): {msg}")
    st.stop()

# Action buttons
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance.")

# Auto-refresh tick (no infinite loops)
if auto_refresh:
    now = time.time()
    last = st.session_state.get("last_refresh_ts", 0.0)
    if (now - last) > float(refresh_secs):
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now

# Run now
if run_clicked:
    if not instance_url:
        st.error("Instance URL is required (used to scope snapshots).")
        st.stop()

    if not effective_api_base:
        st.error("Could not derive API base. Provide an API base override.")
        st.stop()

    payload = {"instance_url": instance_url, "api_base_url": effective_api_base}

    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", payload=payload, timeout=300)

    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")
        # Still allow viewing last snapshot for this instance
        st.session_state["force_refresh"] = True

# Manual refresh
if refresh_clicked:
    st.session_state["force_refresh"] = True

# Load latest metrics (scoped by instance_url if provided)
if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

latest_url = metrics_latest_url(backend_url, instance_url)
ok_m, code_m, payload = api_get(latest_url, timeout=30)
if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet for this instance. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}

# Header/meta
snapshot_time = metrics.get("snapshot_time_utc", "unknown")
inst_used = metrics.get("instance_url") or ""
api_used = metrics.get("api_base_url") or ""
empl_src = metrics.get("employee_status_source") or "unknown"
cont_src = metrics.get("contingent_source") or "unknown"
fallback_used = bool(metrics.get("employee_status_fallback_used"))

st.caption(f"Snapshot UTC: {snapshot_time}")
if inst_used or api_used:
    st.caption(f"Instance: {inst_used or '(blank)'} | API base: {api_used or '(blank)'}")
st.caption(
    f"Employee status source: {empl_src}"
    + (" (fallback(User.status) used)" if fallback_used else "")
    + f" • Contingent source: {cont_src}"
)

# KPIs
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
with k1:
    metric_card("Active users", as_int(metrics.get("active_users")))
with k2:
    metric_card("EmpJob rows", as_int(metrics.get("empjob_rows")))
with k3:
    metric_card("Contingent workers", as_int(metrics.get("contingent_worker_count")))
with k4:
    metric_card("Inactive users", as_int(metrics.get("inactive_user_count")))
with k5:
    metric_card("Missing managers", as_int(metrics.get("missing_manager_count")))
with k6:
    metric_card("Invalid org", as_int(metrics.get("invalid_org_count")))
with k7:
    metric_card("Missing emails", as_int(metrics.get("missing_email_count")))
with k8:
    metric_card("Risk score", as_int(metrics.get("risk_score")))

# Tabs (IMPORTANT: count must match variables)
tabs = ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce"]
if show_raw:
    tabs.append("🔎 Raw JSON")

tab_objs = st.tabs(tabs)

# Tab 1: Email
with tab_objs[0]:
    show_table("Missing emails (sample)", metrics.get("missing_email_sample"))
    show_table("Duplicate emails (sample)", metrics.get("duplicate_email_sample"))
    st.caption(
        f"Duplicate email count = {as_int(metrics.get('duplicate_email_count'))} "
        f"(counts additional users beyond the first occurrence per email)."
    )

# Tab 2: Org
with tab_objs[1]:
    show_table("Invalid org assignments (sample)", metrics.get("invalid_org_sample"))
    st.subheader("Missing org field counts")
    counts = metrics.get("org_missing_field_counts") or {}
    if counts:
        st.dataframe(pd.DataFrame([counts]), use_container_width=True, hide_index=True)
    else:
        st.info("No org missing-field breakdown available.")

# Tab 3: Manager
with tab_objs[2]:
    show_table("Missing managers (sample)", metrics.get("missing_manager_sample"))
    by_status = metrics.get("inactive_users_by_status") or {}
    if by_status:
        st.subheader("Inactive users by status")
        df = pd.DataFrame([{"status": k, "count": v} for k, v in by_status.items()]).sort_values("count", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)

# Tab 4: Workforce
with tab_objs[3]:
    st.subheader("Inactive users (sample)")
    st.caption("Shows employee status as: Name (Code) when available.")
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))

    st.subheader("Contingent workers (sample)")
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

# Optional Raw JSON
if show_raw:
    with tab_objs[4]:
        st.json(metrics)
