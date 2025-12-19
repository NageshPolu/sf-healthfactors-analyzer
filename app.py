import os
import time
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
        return {"detail": (resp.text or "")[:800]}


def api_get(url: str, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, payload: Dict[str, Any], timeout: int = 180) -> Tuple[bool, int, Dict[str, Any]]:
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
    instance_url = normalize_url(instance_url)
    if not instance_url:
        return ""

    if "://" not in instance_url:
        instance_url = "https://" + instance_url

    host = (urlparse(instance_url).hostname or "").lower()
    if not host:
        return ""

    # common pattern: hcmXX.sapsf.com -> apiXX.sapsf.com
    if host.startswith("hcm") and host.endswith(".sapsf.com"):
        return "https://" + host.replace("hcm", "api", 1)

    # otherwise try same host
    return "https://" + host


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
        value=default_backend,
        placeholder="https://your-render-backend",
    )
    backend_url = normalize_url(backend_url)

    st.divider()
    st.subheader("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        placeholder="https://hcm41.sapsf.com",
    )
    instance_url = normalize_url(instance_url)
    st.session_state["instance_url"] = instance_url

    derived_api_base = derive_api_base_from_instance(instance_url)
    st.text_input("Derived API base URL", value=derived_api_base, disabled=True)

    api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_override", ""),
        placeholder="https://apisalesdemo2.successfactors.eu",
    )
    api_override = normalize_url(api_override)
    st.session_state["api_override"] = api_override

    effective_api_base = api_override or derived_api_base
    st.caption("Effective API base:")
    st.write(effective_api_base or "—")

    st.divider()
    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

# Status banner
status_box = st.empty()

if not backend_url:
    status_box.warning("Enter your Backend URL to continue.")
    st.stop()

# Health check
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok and data.get("ok") is True:
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
    st.info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance.")

# Run now
if run_clicked:
    if not instance_url:
        st.error("Instance URL is required.")
    else:
        payload = {
            "instance_url": instance_url,
            "api_base_url": effective_api_base,  # may be empty; backend should auto-detect
        }
        with st.spinner("Running checks via backend..."):
            ok_run, code_run, out = api_post(f"{backend_url}/run", payload=payload, timeout=240)
        if ok_run:
            st.success("Run completed ✅")
            st.session_state["force_refresh"] = True
        else:
            st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")
            st.session_state["force_refresh"] = True

# Refresh button
if refresh_clicked:
    st.session_state["force_refresh"] = True

# Auto-refresh tick
if auto_refresh:
    now = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now

# Load latest metrics (ALWAYS scoped by instance if present)
query_instance = requests.utils.quote(instance_url or "")
metrics_url = f"{backend_url}/metrics/latest?instance_url={query_instance}" if instance_url else f"{backend_url}/metrics/latest"

if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

ok_m, code_m, payload = api_get(metrics_url, timeout=30)
if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet for this instance. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# Header facts
st.caption(f"Snapshot UTC: {snapshot_time}")
if metrics.get("instance_url") or metrics.get("api_base_url_effective"):
    st.caption(
        f"Instance: {metrics.get('instance_url','—')} | API base: {metrics.get('api_base_url_effective','—')}"
    )

# KPI row
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)

with k1:
    metric_card("Active users", as_int(metrics.get("active_users")))
with k2:
    metric_card("EmpJob rows", as_int(metrics.get("empjob_rows") or metrics.get("current_empjob_rows")))
with k3:
    metric_card("Contingent workers", as_int(metrics.get("contingent_worker_count") or metrics.get("contingent_workers")))
with k4:
    metric_card("Inactive users", as_int(metrics.get("inactive_user_count") or metrics.get("inactive_users")))
with k5:
    metric_card("Missing managers", as_int(metrics.get("missing_manager_count")))
with k6:
    metric_card("Invalid org", as_int(metrics.get("invalid_org_count")))
with k7:
    metric_card("Missing emails", as_int(metrics.get("missing_email_count")))
with k8:
    metric_card("Risk score", as_int(metrics.get("risk_score")))

st.caption(metrics.get("employee_status_source") or "")

# ✅ FIX: 5 tabs -> 5 variables
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👔 Workforce", "🔎 Raw JSON"]
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
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))

with tab4:
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))
    show_table("Employee status breakdown (top)", metrics.get("employee_status_breakdown"))

with tab5:
    st.json(metrics)
