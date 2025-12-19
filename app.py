# app.py
from __future__ import annotations

import os
import time
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
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u.rstrip("/")


def derive_api_base(instance_url: str) -> str:
    """
    Derive SuccessFactors OData API base URL from an instance URL.

    Examples:
      https://hcm41.sapsf.com          -> https://api41.sapsf.com
      https://hcm41preview.sapsf.com   -> https://api41preview.sapsf.com
      https://salesdemo.successfactors.eu -> https://apisalesdemo.successfactors.eu

    If cannot derive confidently, return "" (force user to override).
    """
    iu = normalize_url(instance_url)
    if not iu:
        return ""

    host = urlparse(iu).netloc.strip().lower()
    if not host:
        return ""

    # already an api host
    if host.startswith("api"):
        return f"https://{host}"

    # SAPSF pattern: hcmXX* -> apiXX*
    if host.startswith("hcm"):
        # replace ONLY the prefix "hcm" with "api"
        return f"https://api{host[3:]}"

    # successfactors.eu / successfactors.com tenant vanity domains
    if ".successfactors." in host:
        parts = host.split(".")
        if len(parts) >= 3:
            parts[0] = "api" + parts[0]
            return "https://" + ".".join(parts)

    # unknown pattern
    return ""


def call_backend_get(backend_url: str, path: str, params: dict | None = None, timeout: int = 30):
    url = normalize_url(backend_url) + path
    return requests.get(url, params=params or {}, timeout=timeout)


def call_backend_post(backend_url: str, path: str, payload: dict, timeout: int = 120):
    url = normalize_url(backend_url) + path
    return requests.post(url, json=payload, timeout=timeout)


def show_kpi(label: str, value):
    st.metric(label, value)


def safe_list(v):
    return v if isinstance(v, list) else []


# -----------------------------
# Page
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - SF EC Health Check", layout="wide")

# Session defaults (IMPORTANT: no default API override)
if "backend_url" not in st.session_state:
    st.session_state.backend_url = os.getenv("BACKEND_URL", "").strip() or "https://sf-ec-gates-backend.onrender.com"
if "instance_url" not in st.session_state:
    st.session_state.instance_url = ""
if "api_override" not in st.session_state:
    st.session_state.api_override = ""  # MUST stay empty by default
if "username" not in st.session_state:
    st.session_state.username = ""
if "password" not in st.session_state:
    st.session_state.password = ""
if "company_id" not in st.session_state:
    st.session_state.company_id = ""
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False
if "refresh_seconds" not in st.session_state:
    st.session_state.refresh_seconds = 30

# -----------------------------
# Sidebar: Connection + Instance + Creds
# -----------------------------
with st.sidebar:
    st.header("Connection")

    st.session_state.backend_url = st.text_input(
        "Backend URL",
        value=st.session_state.backend_url,
        help="Streamlit calls Backend. Backend calls SuccessFactors (OData).",
    ).strip()

    st.divider()

    st.header("Instance")

    # Track instance changes to avoid reusing stale override
    prev_instance = st.session_state.instance_url
    st.session_state.instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.instance_url,
        placeholder="https://hcm41.sapsf.com  or  https://salesdemo.successfactors.eu",
    ).strip()

    # If instance changed, DO NOT keep an old override silently
    if normalize_url(prev_instance) != normalize_url(st.session_state.instance_url):
        st.session_state.api_override = ""  # clear override on instance change

    derived_api = derive_api_base(st.session_state.instance_url)

    st.text_input(
        "Derived API base URL",
        value=derived_api or "",
        disabled=True,
        help="Auto-derived from Instance URL. If blank/incorrect, use override below.",
    )

    st.session_state.api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.api_override,
        placeholder="(leave blank to use derived API base)",
        help="If your tenant uses a different API host, paste it here. This field is intentionally blank by default.",
    ).strip()

    effective_api = normalize_url(st.session_state.api_override) or derived_api

    st.caption("Effective API base:")
    if effective_api:
        st.write(effective_api)
    else:
        st.warning("API base could not be derived. Please provide API override.")

    st.divider()

    st.header("Credentials (per tenant)")
    st.session_state.username = st.text_input("SF Username", value=st.session_state.username).strip()
    st.session_state.password = st.text_input("SF Password", value=st.session_state.password, type="password")
    st.session_state.company_id = st.text_input(
        "Company ID (optional)",
        value=st.session_state.company_id,
        help="Only needed if your tenant requires Company ID for authentication policies or routing.",
    ).strip()

    st.divider()

    st.session_state.auto_refresh = st.toggle("Auto-refresh latest snapshot", value=st.session_state.auto_refresh)
    st.session_state.refresh_seconds = st.slider("Refresh every (seconds)", 10, 120, st.session_state.refresh_seconds)

# -----------------------------
# Header
# -----------------------------
st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

backend_ok = False
backend_msg = ""
if st.session_state.backend_url:
    try:
        r = call_backend_get(st.session_state.backend_url, "/health", timeout=10)
        backend_ok = r.status_code == 200
        backend_msg = "Backend reachable ✅" if backend_ok else f"Backend not healthy (HTTP {r.status_code})"
    except Exception as e:
        backend_ok = False
        backend_msg = f"Backend unreachable: {e}"

if backend_ok:
    st.success(backend_msg)
else:
    st.error(backend_msg)

# -----------------------------
# Actions: Run + Refresh
# -----------------------------
c1, c2, c3 = st.columns([1.3, 1.3, 3.4])
run_clicked = c1.button("🔁 Run live check now", use_container_width=True, disabled=not backend_ok)
refresh_clicked = c2.button("🧾 Refresh latest snapshot", use_container_width=True, disabled=not backend_ok)
c3.info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance/company.")

# Determine scope
instance_norm = normalize_url(st.session_state.instance_url)
company_id = (st.session_state.company_id or "").strip()
api_base = effective_api  # override OR derived; never default

# -----------------------------
# Run
# -----------------------------
if run_clicked:
    if not instance_norm:
        st.error("Please enter Instance URL.")
    elif not api_base:
        st.error("Could not derive API base URL. Please enter API base override.")
    elif not st.session_state.username or not st.session_state.password:
        st.error("Please enter SF Username + Password.")
    else:
        payload = {
            "instance_url": instance_norm,
            "api_base_url": api_base,
            "username": st.session_state.username,
            "password": st.session_state.password,
            "company_id": company_id or None,
            "timeout": 60,
            "verify_ssl": True,
        }
        with st.spinner("Running gates…"):
            try:
                resp = call_backend_post(st.session_state.backend_url, "/run", payload, timeout=180)
                if resp.status_code == 200:
                    st.success("Run completed ✅")
                else:
                    detail = ""
                    try:
                        detail = resp.json().get("detail") or resp.text
                    except Exception:
                        detail = resp.text
                    st.error(f"Run failed (HTTP {resp.status_code}): {detail}")
            except Exception as e:
                st.error(f"Run failed: {e}")

# -----------------------------
# Refresh / Auto-refresh load latest
# -----------------------------
def load_latest():
    if not backend_ok:
        return {"status": "empty"}

    params = {}
    if instance_norm:
        params["instance_url"] = instance_norm
    if company_id:
        params["company_id"] = company_id

    try:
        rr = call_backend_get(st.session_state.backend_url, "/metrics/latest", params=params, timeout=20)
        if rr.status_code != 200:
            return {"status": "empty", "error": f"HTTP {rr.status_code}: {rr.text}"}
        return rr.json()
    except Exception as e:
        return {"status": "empty", "error": str(e)}


if st.session_state.auto_refresh and backend_ok:
    # simple auto refresh (Streamlit rerun loop)
    time.sleep(st.session_state.refresh_seconds)
    st.rerun()

if refresh_clicked:
    st.session_state["_force_refresh"] = True

data = load_latest()

if data.get("status") != "ok":
    err = data.get("error")
    if err:
        st.warning(f"No snapshot loaded. Backend says: {err}")
    else:
        st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
    st.stop()

metrics = data.get("metrics") or {}

# -----------------------------
# KPIs
# -----------------------------
snapshot_time = metrics.get("snapshot_time_utc") or metrics.get("snapshotUTC") or metrics.get("snapshot_time") or "unknown"
st.caption(f"Snapshot UTC: {snapshot_time}")

k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
show_kpi("Active users", metrics.get("active_users", 0))
show_kpi("EmpJob rows", metrics.get("empjob_rows", metrics.get("current_empjob_rows", 0)))
show_kpi("Contingent", metrics.get("contingent_workers", metrics.get("contingent_worker_count", 0)))
show_kpi("Inactive users", metrics.get("inactive_users", metrics.get("inactive_user_count", 0)))
show_kpi("Missing managers", metrics.get("missing_manager_count", 0))
show_kpi("Invalid org", metrics.get("invalid_org_count", 0))
show_kpi("Missing emails", metrics.get("missing_email_count", 0))
show_kpi("Risk score", metrics.get("risk_score", 0))

st.caption(
    f"Instance: {metrics.get('instance_url', instance_norm) or instance_norm}  |  "
    f"API base: {metrics.get('api_base_url', api_base) or api_base}  |  "
    f"Company ID: {metrics.get('company_id', company_id) or company_id or '(none)'}"
)

# -----------------------------
# Tabs (MAKE SURE COUNT MATCHES)
# -----------------------------
tab_email, tab_org, tab_mgr, tab_workforce, tab_raw = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce", "🔎 Raw JSON"]
)

with tab_email:
    st.subheader("Missing emails (sample)")
    missing_email_sample = safe_list(metrics.get("missing_email_sample"))
    if missing_email_sample:
        st.dataframe(missing_email_sample, use_container_width=True)
    else:
        st.info("No sample data available.")

    st.subheader("Duplicate emails (sample)")
    dup_sample = safe_list(metrics.get("duplicate_email_sample"))
    if dup_sample:
        st.dataframe(dup_sample, use_container_width=True)
    else:
        st.info("No duplicate email sample data available.")

with tab_org:
    st.subheader("Invalid org assignments (sample)")
    invalid_org_sample = safe_list(metrics.get("invalid_org_sample"))
    if invalid_org_sample:
        st.dataframe(invalid_org_sample, use_container_width=True)
    else:
        st.info("No sample data available.")

    st.subheader("Org missing field counts")
    org_counts = metrics.get("org_missing_field_counts") or {}
    if isinstance(org_counts, dict) and org_counts:
        st.json(org_counts)
    else:
        st.info("No org missing-field counts available.")

with tab_mgr:
    st.subheader("Missing managers (sample)")
    mm_sample = safe_list(metrics.get("missing_manager_sample"))
    if mm_sample:
        st.dataframe(mm_sample, use_container_width=True)
    else:
        st.info("No sample data available.")

with tab_workforce:
    st.subheader("Inactive users (sample)")
    iu_sample = safe_list(metrics.get("inactive_users_sample"))
    if iu_sample:
        st.dataframe(iu_sample, use_container_width=True)
    else:
        st.info("No sample data available.")

    st.subheader("Contingent workers (sample)")
    cw_sample = safe_list(metrics.get("contingent_workers_sample"))
    if cw_sample:
        st.dataframe(cw_sample, use_container_width=True)
    else:
        st.info("No sample data available.")

    st.caption(f"Contingent source: {metrics.get('contingent_source', 'unknown')}")

with tab_raw:
    st.json(metrics)
