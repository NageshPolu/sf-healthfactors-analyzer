# app.py
import os
import time
from typing import Any, Dict, Tuple, Optional
from urllib.parse import urlparse, urlencode

import requests
import streamlit as st
import pandas as pd


# -----------------------------
# URL helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    u = u.strip().rstrip("/")
    return u


def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Best-effort:
      https://hcm41.sapsf.com  -> https://api41.sapsf.com
      https://hcm10.successfactors.eu -> https://api10.successfactors.eu
    If hostname already starts with api -> returns base.
    """
    instance_url = normalize_base_url(instance_url)
    if not instance_url:
        return ""

    # ensure it parses even if user types "hcm41.sapsf.com"
    if "://" not in instance_url:
        instance_url = "https://" + instance_url

    p = urlparse(instance_url)
    host = (p.hostname or "").lower()
    scheme = p.scheme or "https"

    if not host:
        return ""

    if host.startswith("api"):
        return f"{scheme}://{host}"

    # pattern: hcm<digits>.<rest>
    # e.g. hcm41.sapsf.com -> api41.sapsf.com
    if host.startswith("hcm"):
        tail = host[3:]  # after 'hcm'
        # tail starts with digits? then replace prefix with api
        digits = ""
        rest = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[len(digits):]
                break
        if digits and rest.startswith("."):
            return f"{scheme}://api{digits}{rest}"
        # fallback: simple replace first hcm -> api
        return f"{scheme}://{host.replace('hcm', 'api', 1)}"

    return ""


# -----------------------------
# HTTP helpers
# -----------------------------
def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": (resp.text or "")[:800]}


def api_get(url: str, params: Optional[dict] = None, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        # cache-bust
        params = dict(params or {})
        params["_ts"] = int(time.time())
        r = requests.get(url, params=params, timeout=timeout, headers={"Cache-Control": "no-cache"})
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, payload: dict, timeout: int = 180) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.post(url, json=payload, timeout=timeout, headers={"Cache-Control": "no-cache"})
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
st.set_page_config(page_title="YASH HealthFactors - SF EC Health Check", layout="wide")
st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

# Sidebar
with st.sidebar:
    st.header("Connection")

    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input(
        "Backend URL",
        value=default_backend,
        placeholder="https://your-render-backend",
    )
    backend_url = normalize_base_url(backend_url)

    st.divider()
    st.subheader("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        placeholder="https://hcm41.sapsf.com",
    )
    instance_url = normalize_base_url(instance_url)
    st.session_state["instance_url"] = instance_url

    derived_api = derive_api_base_from_instance(instance_url) if instance_url else ""
    st.text_input("Derived API base URL", value=derived_api, disabled=True)

    api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_override", ""),
        placeholder="https://apisalesdemo2.successfactors.eu",
    )
    api_override = normalize_base_url(api_override)
    st.session_state["api_override"] = api_override

    effective_api = api_override or derived_api

    if instance_url and not effective_api:
        st.warning("Could not derive API base URL. Provide API base override.")
    elif instance_url and effective_api:
        st.caption(f"Effective API base: {effective_api}")

    st.divider()
    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)


# Always show a visible status area (prevents “blank UI” feeling)
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

# Actions
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance.")

# Run now
if run_clicked:
    if not instance_url:
        st.error("Please enter Instance URL.")
        st.stop()
    if not effective_api:
        st.error("Could not derive API base URL. Please enter API base override.")
        st.stop()

    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(
            f"{backend_url}/run",
            payload={"instance_url": instance_url, "api_base_url": effective_api},
            timeout=240,
        )

    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")
        st.stop()

# Refresh logic
if refresh_clicked:
    st.session_state["force_refresh"] = True

if auto_refresh:
    now_ts = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now_ts - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now_ts

if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

# Load latest snapshot FOR THIS INSTANCE (prevents “old URL data”)
params = {"instance_url": instance_url} if instance_url else {}
ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", params=params, timeout=30)

if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found for this instance yet. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# Top KPIs
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

# Show which instance/api produced this snapshot (so you can verify no mixing)
snap_instance = metrics.get("instance_url") or ""
snap_api = metrics.get("api_base_url") or ""
if snap_instance or snap_api:
    st.caption(f"Instance: {snap_instance}  |  API base: {snap_api}")

# Sources/coverage
employee_status_source = metrics.get("employee_status_source", "unknown")
contingent_source = metrics.get("contingent_source", "unknown")
coverage = metrics.get("emplstatus_label_coverage") or {}
rows_with_label = coverage.get("rows_with_label")
total_rows = coverage.get("total_rows")
status_catalog_source = metrics.get("status_catalog_source", "not-available")

st.caption(
    f"Employee status source: {employee_status_source} | "
    f"Status catalog: {status_catalog_source} | "
    f"Label coverage: {rows_with_label}/{total_rows} | "
    f"Contingent source: {contingent_source}"
)

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce", "🔎 Raw JSON"]
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
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

    st.subheader("Inactive breakdown by Employment Status")
    by_status = metrics.get("inactive_by_status") or {}
    if by_status:
        df = pd.DataFrame(
            [{"Employment Status": k, "Count": v} for k, v in by_status.items()]
        ).sort_values("Count", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No status breakdown available.")

with tab5:
    st.json(metrics)
