# app.py
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests
import streamlit as st


# -----------------------------
# Helpers
# -----------------------------
def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    # Add scheme if missing
    if not re.match(r"^https?://", u, flags=re.I):
        u = "https://" + u
    return u.rstrip("/")


def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Best-effort mapping:
      - https://hcm41.sapsf.com      -> https://api41.sapsf.com
      - https://hcm41preview.sapsf.com -> https://api41preview.sapsf.com
      - https://salesdemo2.successfactors.eu -> https://apisalesdemo2.successfactors.eu
      - https://apisalesdemo2.successfactors.eu -> https://apisalesdemo2.successfactors.eu
    """
    instance_url = normalize_url(instance_url)
    if not instance_url:
        return ""

    p = urlparse(instance_url)
    host = (p.netloc or "").lower()
    if not host:
        return ""

    # If already an API host
    if host.startswith("api"):
        return f"{p.scheme}://{host}"

    # Common SAPSF naming: hcmXX... -> apiXX...
    if host.startswith("hcm"):
        api_host = "api" + host[3:]  # replace leading "hcm" with "api"
        return f"{p.scheme}://{api_host}"

    # SuccessFactors DC style: <tenant>.successfactors.<tld> -> api<tenant>.successfactors.<tld>
    # e.g. salesdemo2.successfactors.eu -> apisalesdemo2.successfactors.eu
    api_host = "api" + host
    return f"{p.scheme}://{api_host}"


def backend_get(backend_url: str, path: str, params: dict | None = None, timeout: int = 60) -> dict:
    url = normalize_url(backend_url) + path
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def backend_post(backend_url: str, path: str, payload: dict, timeout: int = 180) -> dict:
    url = normalize_url(backend_url) + path
    r = requests.post(url, json=payload, timeout=timeout)
    # backend returns HTTPException detail as JSON body; Streamlit will show in error block below
    r.raise_for_status()
    return r.json()


def safe_list(x) -> list:
    return x if isinstance(x, list) else []


def render_table(title: str, rows: list[dict], max_rows: int = 50):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    st.dataframe(rows[:max_rows], use_container_width=True)


def metric_int(metrics: dict, key: str) -> int:
    v = metrics.get(key)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(v)
    except Exception:
        return 0


# -----------------------------
# Streamlit App
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - SAP SuccessFactors EC Health Check", layout="wide")

st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

# Defaults
DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "").strip()
if "backend_url" not in st.session_state:
    st.session_state.backend_url = DEFAULT_BACKEND_URL

if "metrics" not in st.session_state:
    st.session_state.metrics = None

if "last_scope_key" not in st.session_state:
    st.session_state.last_scope_key = ""


# Sidebar - Connection
st.sidebar.header("Connection")
backend_url = st.sidebar.text_input("Backend URL", value=st.session_state.backend_url or "", key="backend_url_input")
backend_url = normalize_url(backend_url)
st.session_state.backend_url = backend_url

st.sidebar.caption("Streamlit calls Backend. Backend calls SuccessFactors (OData).")

# Instance section
st.sidebar.header("Instance")

instance_url = st.sidebar.text_input("Instance URL", value=st.session_state.get("instance_url", ""))
instance_url = normalize_url(instance_url)
st.session_state.instance_url = instance_url

derived_api = derive_api_base_from_instance(instance_url)
st.sidebar.text_input("Derived API base URL", value=derived_api or "", disabled=True)

api_override = st.sidebar.text_input("API base override (optional)", value=st.session_state.get("api_override", ""))
api_override = normalize_url(api_override)
st.session_state.api_override = api_override

effective_api_base = api_override or derived_api
if effective_api_base:
    st.sidebar.markdown(f"**Effective API base:**  \n{effective_api_base}")
else:
    st.sidebar.markdown("**Effective API base:**  \n_(enter Instance URL)_")

# Credentials (per tenant)
st.sidebar.header("Credentials (per tenant)")
sf_username = st.sidebar.text_input("SF Username", value=st.session_state.get("sf_username", ""))
sf_password = st.sidebar.text_input("SF Password", value=st.session_state.get("sf_password", ""), type="password")
company_id = st.sidebar.text_input("Company ID (optional)", value=st.session_state.get("company_id", ""))
company_id = (company_id or "").strip()

st.session_state.sf_username = sf_username
st.session_state.sf_password = sf_password
st.session_state.company_id = company_id

st.sidebar.header("Runtime")
timeout = st.sidebar.number_input("HTTP timeout (sec)", min_value=10, max_value=300, value=int(st.session_state.get("timeout", 60)))
verify_ssl = st.sidebar.toggle("Verify SSL", value=bool(st.session_state.get("verify_ssl", True)))
st.session_state.timeout = timeout
st.session_state.verify_ssl = verify_ssl

auto_refresh = st.sidebar.toggle("Auto-refresh latest snapshot", value=bool(st.session_state.get("auto_refresh", False)))
st.session_state.auto_refresh = auto_refresh
refresh_every = st.sidebar.slider("Refresh every (seconds)", min_value=10, max_value=120, value=int(st.session_state.get("refresh_every", 30)))
st.session_state.refresh_every = refresh_every


# Backend health check
backend_ok = False
if backend_url:
    try:
        h = backend_get(backend_url, "/health", timeout=30)
        backend_ok = bool(h.get("ok"))
    except Exception:
        backend_ok = False

if backend_ok:
    st.success("Backend reachable ✅")
else:
    st.warning("Backend not reachable (or /health failed). Check Backend URL.")


# Scope key: avoid showing old tenant snapshot when instance/company changes
scope_key = f"{instance_url}||{company_id}".strip()
if scope_key != st.session_state.last_scope_key:
    # Clear metrics on scope change so old tenant data never shows
    st.session_state.metrics = None
    st.session_state.last_scope_key = scope_key


# Actions
colA, colB, colC = st.columns([1, 1, 2])

run_clicked = colA.button("🔄 Run live check now", use_container_width=True, disabled=not backend_ok)
refresh_clicked = colB.button("🧾 Refresh latest snapshot", use_container_width=True, disabled=not backend_ok)

colC.info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance/company.")

# Validate minimum inputs for running
def can_run() -> tuple[bool, str]:
    if not backend_url:
        return False, "Backend URL is required."
    if not instance_url:
        return False, "Instance URL is required."
    if not effective_api_base:
        return False, "Could not derive API base URL. Provide API base override."
    if not sf_username or not sf_password:
        return False, "SF Username and SF Password are required."
    return True, ""

# Execute run
if run_clicked:
    ok, msg = can_run()
    if not ok:
        st.error(msg)
    else:
        payload = {
            "instance_url": instance_url,
            "api_base_url": effective_api_base,
            "username": sf_username,
            "password": sf_password,
            "company_id": company_id or None,
            "timeout": int(timeout),
            "verify_ssl": bool(verify_ssl),
        }
        try:
            with st.spinner("Running gates..."):
                res = backend_post(backend_url, "/run", payload=payload, timeout=240)
            st.session_state.metrics = res.get("metrics")
            st.success("Run completed ✅")
        except requests.HTTPError as e:
            # Try to show backend error detail
            try:
                detail = e.response.json().get("detail")
            except Exception:
                detail = str(e)
            st.error(f"Run failed: {detail}")
        except Exception as e:
            st.error(f"Run failed: {str(e)}")

# Execute refresh
def refresh_latest():
    if not backend_ok:
        return
    if not backend_url:
        return
    if not instance_url:
        return

    params = {"instance_url": instance_url}
    if company_id:
        params["company_id"] = company_id

    try:
        res = backend_get(backend_url, "/metrics/latest", params=params, timeout=60)
        if res.get("status") == "ok":
            st.session_state.metrics = res.get("metrics")
        else:
            st.session_state.metrics = None
    except Exception as e:
        st.error(f"Refresh failed: {str(e)}")


if refresh_clicked:
    refresh_latest()

# Auto-refresh
if auto_refresh and backend_ok and instance_url:
    st.write("")  # spacer
    st.caption(f"Auto-refresh is ON (every {refresh_every}s).")
    st.autorefresh(interval=refresh_every * 1000, key="autorefresh_key")
    refresh_latest()


# -----------------------------
# Render Metrics + Tabs
# -----------------------------
metrics = st.session_state.metrics

if not metrics:
    st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
    st.stop()

snapshot_time = metrics.get("snapshot_time_utc") or "unknown"
st.caption(f"Snapshot UTC: {snapshot_time}")

# Show scope (so you can confirm it’s not using old tenant)
inst_disp = metrics.get("instance_url") or instance_url or ""
api_disp = metrics.get("api_base_url") or effective_api_base or ""
cid_disp = metrics.get("company_id") or company_id or ""
st.caption(f"Instance: {inst_disp}  |  API base: {api_disp}  |  Company ID: {cid_disp}")

# KPI row
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)

k1.metric("Active users", metric_int(metrics, "active_users"))
k2.metric("EmpJob rows", metric_int(metrics, "empjob_rows"))
k3.metric("Contingent workers", metric_int(metrics, "contingent_workers"))
k4.metric("Inactive users", metric_int(metrics, "inactive_users"))
k5.metric("Missing managers", metric_int(metrics, "missing_managers"))
k6.metric("Invalid org", metric_int(metrics, "invalid_org"))
k7.metric("Missing emails", metric_int(metrics, "missing_emails"))
k8.metric("Risk score", metric_int(metrics, "risk_score"))

# Tabs (5 tabs -> 5 variables, avoids your previous crash)
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "🧑‍🤝‍🧑 Workforce", "🔎 Raw JSON"]
)

with tab1:
    render_table("Missing emails (sample)", safe_list(metrics.get("missing_emails_sample")))
    render_table("Duplicate emails (sample)", safe_list(metrics.get("duplicate_emails_sample")))

with tab2:
    render_table("Invalid org (sample)", safe_list(metrics.get("invalid_org_sample")))
    render_table("Missing mandatory org fields (sample)", safe_list(metrics.get("missing_org_fields_sample")))

with tab3:
    render_table("Missing managers (sample)", safe_list(metrics.get("missing_managers_sample")))
    render_table("Manager self-loop / invalid manager (sample)", safe_list(metrics.get("invalid_manager_sample")))

with tab4:
    render_table("Inactive users (sample)", safe_list(metrics.get("inactive_users_sample")))
    render_table("Contingent workers (sample)", safe_list(metrics.get("contingent_workers_sample")))
    render_table("Workforce summary (optional)", safe_list(metrics.get("workforce_summary_sample")))

with tab5:
    st.json(metrics)
