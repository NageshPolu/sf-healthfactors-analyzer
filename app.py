# app.py
import os
import time
from typing import Any, Dict, Tuple, Optional
from urllib.parse import urlparse

import requests
import streamlit as st
import pandas as pd


# -----------------------------
# Streamlit safety: avoid showing Python stack/code in UI
# -----------------------------
try:
    st.set_option("client.showErrorDetails", False)
except Exception:
    pass


# -----------------------------
# Helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    return u.rstrip("/")


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": (resp.text or "")[:800]}


def api_get(url: str, params: Dict[str, Any] | None = None, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
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


def derive_sf_api_base(instance_url: str) -> str:
    """
    Derive API base host from instance URL.
    Known patterns:
      - *.successfactors.<tld> -> api<subdomain>.successfactors.<tld>  (e.g. salesdemo2 -> apisalesdemo2)
      - hcmNN.sapsf.com        -> apiNN.sapsf.com                      (e.g. hcm41 -> api41)  :contentReference[oaicite:1]{index=1}
      - otherwise: return the instance origin
    """
    u = normalize_base_url(instance_url)
    if not u:
        return ""

    if "://" not in u:
        u = "https://" + u

    p = urlparse(u)
    host = (p.hostname or "").lower()
    scheme = p.scheme or "https"
    if not host:
        return ""

    # hcmNN.sapsf.com -> apiNN.sapsf.com
    # example: hcm41.sapsf.com -> api41.sapsf.com
    if host.endswith(".sapsf.com") and host.startswith("hcm"):
        num = host.replace("hcm", "").split(".")[0]
        if num.isdigit():
            return f"{scheme}://api{num}.sapsf.com"

    # *.successfactors.eu / *.successfactors.com etc -> api<subdomain>.successfactors.<tld>
    if ".successfactors." in host and not host.startswith("api"):
        sub = host.split(".successfactors.")[0]  # e.g. salesdemo2
        rest = host.split(".successfactors.")[1]  # e.g. eu
        return f"{scheme}://api{sub}.successfactors.{rest}"

    # already api* host OR unknown pattern
    return f"{scheme}://{host}"


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - EC Health Check", layout="wide")
st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

with st.sidebar:
    st.header("Connection")

    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = normalize_base_url(
        st.text_input("Backend URL", value=default_backend, placeholder="https://your-render-backend")
    )

    # NEW: instance url + derived api
    st.subheader("Instance")
    instance_url = st.text_input("Instance URL", value="", placeholder="https://hcm41.sapsf.com")
    instance_url = normalize_base_url(instance_url)

    derived_api = derive_sf_api_base(instance_url) if instance_url else ""
    st.text_input("Derived API base URL", value=derived_api, disabled=True)

    api_override = normalize_base_url(
        st.text_input("API base override (optional)", value="", placeholder="https://apisalesdemo2.successfactors.eu")
    )
    api_base_url = api_override or derived_api

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

    st.divider()
    st.header("Display")
    show_raw_json = st.toggle("Show raw JSON (advanced)", value=False)


status_box = st.empty()

if not backend_url:
    status_box.warning("Enter your Backend URL to continue.")
    st.stop()

# Health check backend
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok:
    status_box.success("Backend reachable ✅")
else:
    msg = data.get("detail") or data.get("message") or "Backend not reachable"
    status_box.error(f"Backend not healthy (HTTP {code}): {msg}")
    st.stop()

# Instance validation (optional but recommended)
if instance_url and not api_base_url:
    st.warning("Instance URL provided but API base could not be derived. Use API base override.")
if not instance_url:
    st.info("Tip: Enter an **Instance URL** to scope metrics per instance and avoid mixing old snapshots.")

# Actions row
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

# Run now (send instance + api base to backend)
if run_clicked:
    payload = {
        "instance_url": instance_url,
        "api_base_url": api_base_url,
    }
    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", payload=payload, timeout=240)
    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        st.error(f"Run failed (HTTP {code_run}): {out.get('detail','Internal error')}")
        st.stop()

if refresh_clicked:
    st.session_state["force_refresh"] = True

# Auto refresh tick
if auto_refresh:
    now = time.time()
    last = st.session_state.get("last_refresh_ts", 0)
    if (now - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now

# Fetch latest metrics (scoped by instance_url so old instance snapshots don't show)
params = {}
if instance_url:
    params["instance_url"] = instance_url

ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", params=params, timeout=30)
if not ok_m:
    st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail','Error')}")
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet for this instance. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# captions (sources + instance)
employee_status_source = metrics.get("employee_status_source") or "unknown"
contingent_source = metrics.get("contingent_source") or "unknown"
inst_used = metrics.get("instance_url") or instance_url or "(not provided)"
api_used = metrics.get("api_base_url") or api_base_url or "(not provided)"

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
st.caption(
    f"Instance: {inst_used}  |  API base: {api_used}\n\n"
    f"Employee status source: {employee_status_source}  •  Contingent source: {contingent_source}"
)

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🧩 Org checks", "👥 Workforce", "🔎 Raw JSON"])

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
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

    st.subheader("Inactive by status (top)")
    inactive_by_status = metrics.get("inactive_by_status") or {}
    if inactive_by_status:
        # show as a small table sorted desc
        items = sorted(inactive_by_status.items(), key=lambda x: x[1], reverse=True)[:30]
        st.dataframe(pd.DataFrame(items, columns=["Status", "Count"]), use_container_width=True, hide_index=True)
    else:
        st.info("No employee status breakdown available.")

with tab4:
    if show_raw_json:
        st.json(metrics)
    else:
        st.info("Enable **Show raw JSON (advanced)** in the sidebar to view raw metrics.")
