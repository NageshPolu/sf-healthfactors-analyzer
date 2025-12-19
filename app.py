from __future__ import annotations

import json
from urllib.parse import urlparse

import requests
import streamlit as st


# ----------------------------
# UI Config
# ----------------------------
st.set_page_config(
    page_title="YASH HealthFactors - SAP SuccessFactors EC Health Check",
    page_icon="✅",
    layout="wide",
)


# ----------------------------
# Helpers
# ----------------------------
def norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    # Allow users to paste host without scheme
    if "://" not in u:
        u = "https://" + u
    return u.rstrip("/")


def get_host(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    p = urlparse(u)
    host = (p.netloc or "").strip()
    return host


def derive_api_candidates(instance_url: str) -> list[str]:
    """
    Return candidate API base URLs from an instance URL.
    IMPORTANT: We DO NOT auto-select/use these (user must choose).
    """
    inst = norm_url(instance_url)
    host = get_host(inst)
    if not host:
        return []

    candidates: list[str] = []

    # 1) SAP "hcmXX.sapsf.com" -> "apiXX.sapsf.com"
    #    Works also with preview like "hcm41preview.sapsf.com" -> "api41preview.sapsf.com"
    if host.startswith("hcm") and host.endswith(".sapsf.com"):
        # Replace only the first "hcm" prefix with "api"
        candidates.append("https://" + ("api" + host[3:]))

    # 2) Generic: prefix "api" to the host if not already
    if not host.startswith("api"):
        candidates.append("https://" + ("api" + host))

    # 3) If it looks like successfactors.<region>, api is often "api<subdomain>..."
    #    (Not always correct, but offer as a candidate)
    if "successfactors." in host and not host.startswith("api"):
        candidates.append("https://" + ("api" + host))

    # Unique + keep order
    out: list[str] = []
    for c in candidates:
        c = norm_url(c)
        if c and c not in out:
            out.append(c)
    return out


def api_get(url: str, timeout: int = 30) -> dict:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def api_post(url: str, payload: dict, timeout: int = 120) -> dict:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def reset_tenant():
    # Everything that must be cleared when switching tenants/instances
    keys = [
        "tenant_locked",
        "backend_url",
        "instance_url",
        "api_choice",
        "api_override",
        "sf_username",
        "sf_password",
        "company_id",
        "last_metrics",
        "last_status",
        "last_error",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def kpi_value(metrics: dict, key: str) -> int:
    try:
        v = metrics.get(key, 0)
        return int(v or 0)
    except Exception:
        return 0


def show_sample_table(rows: list[dict], title: str):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ----------------------------
# Session init
# ----------------------------
if "tenant_locked" not in st.session_state:
    st.session_state.tenant_locked = False

st.session_state.setdefault("last_metrics", None)
st.session_state.setdefault("last_status", "empty")
st.session_state.setdefault("last_error", "")


# ----------------------------
# Sidebar - Connection + Tenant
# ----------------------------
st.sidebar.markdown("## Connection")

backend_url_in = st.sidebar.text_input(
    "Backend URL",
    value=st.session_state.get("backend_url", ""),
    placeholder="https://<your-backend-service>.onrender.com",
    disabled=st.session_state.tenant_locked,
    help="This is your FastAPI backend base URL (Render). Example: https://sf-ec-gates-backend.onrender.com",
)
backend_url = norm_url(backend_url_in)
st.session_state.backend_url = backend_url

# Backend health indicator
backend_ok = False
backend_msg = ""
if backend_url:
    try:
        j = api_get(f"{backend_url}/health", timeout=10)
        backend_ok = bool(j.get("ok") is True)
        backend_msg = "Backend reachable ✅" if backend_ok else "Backend reachable but returned unexpected response"
    except Exception as e:
        backend_ok = False
        backend_msg = f"Backend not reachable: {e}"

if backend_url:
    if backend_ok:
        st.sidebar.success(backend_msg)
    else:
        st.sidebar.error(backend_msg)
else:
    st.sidebar.info("Enter Backend URL to enable checks.")


st.sidebar.markdown("---")
st.sidebar.markdown("## Instance")

instance_url_in = st.sidebar.text_input(
    "Instance URL",
    value=st.session_state.get("instance_url", ""),
    placeholder="https://hcm41.sapsf.com or https://salesdemo.successfactors.eu",
    disabled=st.session_state.tenant_locked,
)
instance_url = norm_url(instance_url_in)
st.session_state.instance_url = instance_url

candidates = derive_api_candidates(instance_url)

# Show derived candidates (informational)
st.sidebar.caption("Derived API base candidates (not auto-used):")
if candidates:
    for c in candidates:
        st.sidebar.code(c, language="text")
else:
    st.sidebar.caption("—")

# IMPORTANT: do NOT default/select automatically
api_choice = st.sidebar.selectbox(
    "Select API base URL (required)",
    options=[""] + candidates,
    index=0,
    disabled=st.session_state.tenant_locked,
    help="Pick one candidate. If you get 401/403/HTML responses, pick a different one or use override.",
)
st.session_state.api_choice = api_choice

api_override_in = st.sidebar.text_input(
    "API base override (optional)",
    value=st.session_state.get("api_override", ""),
    placeholder="https://api41.sapsf.com",
    disabled=st.session_state.tenant_locked,
)
api_override = norm_url(api_override_in)
st.session_state.api_override = api_override

effective_api_base = api_override or api_choice
if effective_api_base:
    st.sidebar.markdown("**Effective API base:**")
    st.sidebar.write(effective_api_base)
else:
    st.sidebar.warning("Choose an API base URL (or enter override).")


st.sidebar.markdown("---")
st.sidebar.markdown("## Credentials (per tenant)")
sf_username = st.sidebar.text_input(
    "SF Username",
    value=st.session_state.get("sf_username", ""),
    disabled=st.session_state.tenant_locked,
)
sf_password = st.sidebar.text_input(
    "SF Password",
    value=st.session_state.get("sf_password", ""),
    type="password",
    disabled=st.session_state.tenant_locked,
)
company_id = st.sidebar.text_input(
    "Company ID (optional)",
    value=st.session_state.get("company_id", ""),
    disabled=st.session_state.tenant_locked,
    help="If your tenant requires company routing, provide Company ID. Otherwise keep blank.",
)

st.session_state.sf_username = sf_username
st.session_state.sf_password = sf_password
st.session_state.company_id = company_id.strip()


# Tenant lock + logout/reset
st.sidebar.markdown("---")
colA, colB = st.sidebar.columns(2)
with colA:
    if st.button("Use this tenant", disabled=st.session_state.tenant_locked):
        # Validate required fields
        if not backend_url:
            st.sidebar.error("Backend URL is required.")
        elif not backend_ok:
            st.sidebar.error("Backend must be reachable before locking tenant.")
        elif not instance_url:
            st.sidebar.error("Instance URL is required.")
        elif not effective_api_base:
            st.sidebar.error("Select API base URL (or enter override).")
        elif not sf_username or not sf_password:
            st.sidebar.error("Username + Password are required.")
        else:
            st.session_state.tenant_locked = True
            st.sidebar.success("Tenant locked ✅")

with colB:
    if st.button("Logout / Reset", disabled=not st.session_state.tenant_locked):
        reset_tenant()
        st.rerun()


# ----------------------------
# Main Header
# ----------------------------
st.markdown("# ✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

if not backend_ok:
    st.warning("Backend is not reachable. Fix Backend URL first.")
    st.stop()

if not st.session_state.tenant_locked:
    st.info("Enter tenant details in the left sidebar, then click **Use this tenant**.")
    st.stop()


# ----------------------------
# Actions: Run / Refresh
# ----------------------------
top_left, top_mid, top_right = st.columns([1.2, 1.2, 2.6])

with top_left:
    run_now = st.button("🔄 Run live check now", use_container_width=True)

with top_mid:
    refresh_now = st.button("🧾 Refresh latest snapshot", use_container_width=True)

with top_right:
    st.info("Tip: **Run** pulls live SF data via backend; **Refresh** loads the latest snapshot for the selected instance/company.")


def load_latest_snapshot():
    try:
        params = {"instance_url": instance_url}
        if company_id.strip():
            params["company_id"] = company_id.strip()
        r = requests.get(f"{backend_url}/metrics/latest", params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        st.session_state.last_status = payload.get("status", "empty")
        st.session_state.last_metrics = payload.get("metrics")
        st.session_state.last_error = ""
        return True
    except Exception as e:
        st.session_state.last_error = str(e)
        return False


def run_live_check():
    payload = {
        "instance_url": instance_url,
        "api_base_url": effective_api_base,
        "username": sf_username,
        "password": sf_password,
        "company_id": company_id.strip() or None,
        "timeout": 60,
        "verify_ssl": True,
    }
    try:
        r = requests.post(f"{backend_url}/run", json=payload, timeout=180)
        # backend returns 4xx/5xx with JSON detail
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            st.session_state.last_error = f"{r.status_code}: {detail}"
            return False

        data = r.json()
        st.session_state.last_metrics = data.get("metrics")
        st.session_state.last_status = "ok"
        st.session_state.last_error = ""
        return True
    except Exception as e:
        st.session_state.last_error = str(e)
        return False


if refresh_now:
    ok = load_latest_snapshot()
    if not ok:
        st.error(f"Refresh failed: {st.session_state.last_error}")

if run_now:
    ok = run_live_check()
    if not ok:
        st.error(f"Run failed: {st.session_state.last_error}")

# Auto-load snapshot on first render if none loaded yet
if st.session_state.last_metrics is None and st.session_state.last_status in ("empty", "", None):
    load_latest_snapshot()


# ----------------------------
# Render State
# ----------------------------
metrics = st.session_state.last_metrics
status = st.session_state.last_status

if st.session_state.last_error:
    st.error(f"Run/Refresh error: {st.session_state.last_error}")

if status == "empty" or not metrics:
    st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
    st.stop()


# ----------------------------
# KPI Strip (stable layout)
# ----------------------------
snapshot_time = metrics.get("snapshot_time_utc") or metrics.get("snapshot_time") or "unknown"
st.caption(f"Snapshot UTC: {snapshot_time}")

kpi_cols = st.columns(8)
kpis = [
    ("Active users", "active_users"),
    ("EmpJob rows", "empjob_rows"),
    ("Contingent", "contingent_workers"),
    ("Inactive users", "inactive_users"),
    ("Missing managers", "missing_managers"),
    ("Invalid org", "invalid_org"),
    ("Missing emails", "missing_emails"),
    ("Risk score", "risk_score"),
]
for c, (label, key) in zip(kpi_cols, kpis):
    with c:
        st.metric(label, kpi_value(metrics, key))

st.caption(
    f"Instance: {metrics.get('instance_url', instance_url)}  |  "
    f"API base: {metrics.get('api_base_url', effective_api_base)}  |  "
    f"Company: {metrics.get('company_id', company_id) or '—'}"
)

st.markdown("---")


# ----------------------------
# Tabs (MUST match variables)
# ----------------------------
tab_email, tab_org, tab_mgr, tab_work, tab_raw = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce", "🔎 Raw JSON"]
)

with tab_email:
    show_sample_table(metrics.get("missing_emails_sample", []), "Missing emails (sample)")

with tab_org:
    show_sample_table(metrics.get("invalid_org_sample", []), "Invalid org (sample)")

with tab_mgr:
    show_sample_table(metrics.get("missing_managers_sample", []), "Missing managers (sample)")

with tab_work:
    show_sample_table(metrics.get("inactive_users_sample", []), "Inactive users (sample)")
    st.markdown("---")
    show_sample_table(metrics.get("contingent_workers_sample", []), "Contingent workers (sample)")

with tab_raw:
    st.json(metrics)
