# app.py
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
import streamlit as st


# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - SF EC Health Check", layout="wide")

# -----------------------------
# Helpers
# -----------------------------
def norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    return u.rstrip("/")

def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Best-effort derivation:
    https://hcm41.sapsf.com           -> https://api41.sapsf.com
    https://hcm41preview.sapsf.com    -> https://api41preview.sapsf.com
    https://salesdemo.successfactors.eu -> https://apisalesdemo.successfactors.eu
    """
    instance_url = norm_url(instance_url)
    if not instance_url:
        return ""
    host = instance_url.replace("https://", "").replace("http://", "")
    host = host.split("/")[0].strip()

    if host.startswith("hcm"):
        return "https://" + host.replace("hcm", "api", 1)

    # many EU demo tenants are already hostnames like salesdemo.successfactors.eu
    if not host.startswith("api"):
        return "https://api" + host

    return "https://" + host

def effective_api_base(instance_url: str, api_override: str) -> str:
    ov = norm_url(api_override)
    if ov:
        if ov.startswith("http://") or ov.startswith("https://"):
            return ov
        return "https://" + ov.strip("/")
    return derive_api_base_from_instance(instance_url)

def with_company_in_username(username: str, company_id: str) -> str:
    """
    If company_id is provided and username has no @company, auto append.
    Many SF tenants require USER@COMPANY in Basic Auth.
    """
    u = (username or "").strip()
    cid = (company_id or "").strip()
    if cid and "@" not in u:
        return f"{u}@{cid}"
    return u

def api_get(base: str, path: str, params: dict | None = None, timeout: int = 30) -> dict:
    url = urljoin(norm_url(base) + "/", path.lstrip("/"))
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def api_post(base: str, path: str, payload: dict, timeout: int = 120) -> dict:
    url = urljoin(norm_url(base) + "/", path.lstrip("/"))
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def clear_tenant_state():
    keys = [
        "tenant_locked",
        "tenant_backend_url",
        "tenant_instance_url",
        "tenant_api_override",
        "tenant_api_base",
        "tenant_username",
        "tenant_password",
        "tenant_company_id",
        "last_metrics",
        "last_status",
        "last_error",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

def safe_get(metrics: dict, *keys, default=None):
    for k in keys:
        if k in metrics:
            return metrics.get(k)
    return default


# -----------------------------
# Tenant lock model
# -----------------------------
@dataclass
class TenantCtx:
    backend_url: str
    instance_url: str
    api_override: str
    api_base: str
    username: str
    password: str
    company_id: str


def get_ctx_from_state() -> TenantCtx | None:
    if not st.session_state.get("tenant_locked"):
        return None
    return TenantCtx(
        backend_url=st.session_state.get("tenant_backend_url", ""),
        instance_url=st.session_state.get("tenant_instance_url", ""),
        api_override=st.session_state.get("tenant_api_override", ""),
        api_base=st.session_state.get("tenant_api_base", ""),
        username=st.session_state.get("tenant_username", ""),
        password=st.session_state.get("tenant_password", ""),
        company_id=st.session_state.get("tenant_company_id", ""),
    )


# -----------------------------
# Sidebar UI
# -----------------------------
st.sidebar.markdown("## Connection")

backend_default = st.session_state.get("tenant_backend_url", "https://sf-ec-gates-backend.")  # keep your placeholder
backend_url_input = st.sidebar.text_input(
    "Backend URL",
    value=backend_default,
    disabled=bool(st.session_state.get("tenant_locked")),
    help="Your FastAPI backend base URL (Render service). Example: https://<service>.onrender.com",
)

st.sidebar.markdown("---")
st.sidebar.markdown("## Instance")

instance_url_input = st.sidebar.text_input(
    "Instance URL",
    value=st.session_state.get("tenant_instance_url", ""),
    disabled=bool(st.session_state.get("tenant_locked")),
    help="Example: https://hcm41.sapsf.com OR https://salesdemo.successfactors.eu",
)

derived_api = derive_api_base_from_instance(instance_url_input)
st.sidebar.text_input(
    "Derived API base URL",
    value=derived_api or "",
    disabled=True,
)

# IMPORTANT: do NOT default override
api_override_input = st.sidebar.text_input(
    "API base override (optional)",
    value=st.session_state.get("tenant_api_override", "") if st.session_state.get("tenant_locked") else "",
    disabled=bool(st.session_state.get("tenant_locked")),
    help="Leave blank unless you explicitly want to force a specific api* host.",
)

api_base_now = effective_api_base(instance_url_input, api_override_input)
st.sidebar.markdown("**Effective API base:**")
st.sidebar.markdown(api_base_now if api_base_now else "_(enter instance URL)_")

st.sidebar.markdown("---")
st.sidebar.markdown("## Credentials (per tenant)")

username_input = st.sidebar.text_input(
    "SF Username",
    value=st.session_state.get("tenant_username", ""),
    disabled=bool(st.session_state.get("tenant_locked")),
)

password_input = st.sidebar.text_input(
    "SF Password",
    value=st.session_state.get("tenant_password", ""),
    type="password",
    disabled=bool(st.session_state.get("tenant_locked")),
)

company_id_input = st.sidebar.text_input(
    "Company ID (optional)",
    value=st.session_state.get("tenant_company_id", ""),
    disabled=bool(st.session_state.get("tenant_locked")),
    help="If provided, the app will auto-use USER@COMPANY for authentication unless username already contains @.",
)

st.sidebar.markdown("---")

col_a, col_b = st.sidebar.columns(2)
with col_a:
    lock_btn = st.button(
        "Use this tenant",
        disabled=bool(st.session_state.get("tenant_locked")),
        help="Locks the tenant context so you don't mix data between instances. Use Logout to switch tenants.",
    )
with col_b:
    logout_btn = st.button(
        "Logout / Clear tenant",
        disabled=not bool(st.session_state.get("tenant_locked")),
    )

if logout_btn:
    clear_tenant_state()

if lock_btn:
    # Validate minimum inputs before locking
    b = norm_url(backend_url_input)
    inst = norm_url(instance_url_input)
    api_base = norm_url(api_base_now)
    if not b or not inst or not api_base:
        st.sidebar.error("Backend URL + Instance URL are required.")
    else:
        # lock everything
        st.session_state["tenant_locked"] = True
        st.session_state["tenant_backend_url"] = b
        st.session_state["tenant_instance_url"] = inst
        st.session_state["tenant_api_override"] = norm_url(api_override_input)
        st.session_state["tenant_api_base"] = api_base
        st.session_state["tenant_username"] = (username_input or "").strip()
        st.session_state["tenant_password"] = password_input or ""
        st.session_state["tenant_company_id"] = (company_id_input or "").strip()
        st.session_state["last_metrics"] = None
        st.session_state["last_status"] = None
        st.session_state["last_error"] = None
        st.rerun()


# -----------------------------
# Main page header
# -----------------------------
st.markdown("# ✅ YASH HealthFactors – SAP SuccessFactors EC Health Check")

ctx = get_ctx_from_state()
if not ctx:
    st.info("Enter tenant details in the left panel, then click **Use this tenant**. Use **Logout** to switch instances cleanly.")
    st.stop()

# Show connection banner
try:
    health = api_get(ctx.backend_url, "/health", timeout=15)
    if health.get("ok") is True:
        st.success("Backend reachable ✅")
    else:
        st.warning("Backend reachable, but health returned unexpected response.")
except Exception as e:
    st.error(f"Backend not reachable: {e}")
    st.stop()

# Actions row
c1, c2, c3 = st.columns([1.3, 1.3, 3.4])
with c1:
    run_now = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: **Run** pulls live SF data via backend; **Refresh** loads the latest snapshot for the selected instance/company.", icon="💡")

# -----------------------------
# Run / Refresh handlers
# -----------------------------
def load_latest():
    params = {"instance_url": ctx.instance_url}
    if ctx.company_id:
        params["company_id"] = ctx.company_id
    try:
        r = api_get(ctx.backend_url, "/metrics/latest", params=params, timeout=30)
        st.session_state["last_status"] = r.get("status")
        st.session_state["last_metrics"] = r.get("metrics")
        st.session_state["last_error"] = None
    except Exception as e:
        st.session_state["last_error"] = str(e)
        st.session_state["last_metrics"] = None
        st.session_state["last_status"] = None

def do_run():
    # auto apply company into username (if needed)
    u = with_company_in_username(ctx.username, ctx.company_id)
    payload = {
        "instance_url": ctx.instance_url,
        "api_base_url": ctx.api_base,
        "username": u,
        "password": ctx.password,
        "company_id": ctx.company_id or None,
        "timeout": 60,
        "verify_ssl": True,
    }
    try:
        r = api_post(ctx.backend_url, "/run", payload, timeout=180)
        st.session_state["last_status"] = "ok"
        st.session_state["last_metrics"] = r.get("metrics")
        st.session_state["last_error"] = None
    except requests.HTTPError as he:
        # show backend detail text when possible
        try:
            detail = he.response.json().get("detail")
        except Exception:
            detail = str(he)
        st.session_state["last_error"] = detail
        st.session_state["last_metrics"] = None
        st.session_state["last_status"] = "error"
    except Exception as e:
        st.session_state["last_error"] = str(e)
        st.session_state["last_metrics"] = None
        st.session_state["last_status"] = "error"

if run_now:
    do_run()

if refresh and not run_now:
    load_latest()

# Auto-load on first render after lock
if st.session_state.get("last_metrics") is None and st.session_state.get("last_status") is None and not run_now:
    load_latest()

# -----------------------------
# Status / errors
# -----------------------------
if st.session_state.get("last_error"):
    st.error(f"Run failed: {st.session_state['last_error']}")

metrics = st.session_state.get("last_metrics")

if not metrics:
    st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
    st.stop()

# -----------------------------
# Metrics tiles (ALWAYS render these keys)
# -----------------------------
snapshot_time = safe_get(metrics, "snapshot_time_utc", "snapshotUTC", default="unknown")
st.caption(f"Snapshot UTC: {snapshot_time}")
st.caption(f"Instance: {ctx.instance_url}  |  API base: {ctx.api_base}  |  Company: {ctx.company_id or '(none)'}")

# Map: show consistent labels even if backend key changes
tiles = [
    ("Active users", safe_get(metrics, "active_users", "activeUsers", default=0)),
    ("EmpJob rows", safe_get(metrics, "empjob_rows", "empJob_rows", "empJobRows", default=0)),
    ("Contingent", safe_get(metrics, "contingent_workers", "contingent", "contingent_count", default=0)),
    ("Inactive users", safe_get(metrics, "inactive_users", "inactiveUsers", default=0)),
    ("Missing managers", safe_get(metrics, "missing_managers", "missingManagers", default=0)),
    ("Invalid org", safe_get(metrics, "invalid_org", "invalidOrg", default=0)),
    ("Missing emails", safe_get(metrics, "missing_emails", "missingEmails", default=0)),
    ("Risk score", safe_get(metrics, "risk_score", "riskScore", default=0)),
]

row1 = st.columns(4)
row2 = st.columns(4)
for i, (label, val) in enumerate(tiles[:4]):
    row1[i].metric(label, val)
for i, (label, val) in enumerate(tiles[4:]):
    row2[i].metric(label, val)

st.markdown("---")

# -----------------------------
# Tabs (NO unpack mismatch)
# -----------------------------
tab_labels = ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "🧑‍🤝‍🧑 Workforce", "🔎 Raw JSON"]
tabs = st.tabs(tab_labels)

# Email hygiene
with tabs[0]:
    st.subheader("Missing emails (sample)")
    sample = safe_get(metrics, "missing_emails_sample", "missingEmailsSample", default=[])
    if sample:
        st.dataframe(sample, use_container_width=True)
    else:
        st.info("No sample data available.")

# Org checks
with tabs[1]:
    st.subheader("Invalid org assignments (sample)")
    sample = safe_get(metrics, "invalid_org_sample", "invalidOrgSample", default=[])
    if sample:
        st.dataframe(sample, use_container_width=True)
    else:
        st.info("No sample data available.")

# Manager checks
with tabs[2]:
    st.subheader("Missing managers (sample)")
    sample = safe_get(metrics, "missing_managers_sample", "missingManagersSample", default=[])
    if sample:
        st.dataframe(sample, use_container_width=True)
    else:
        st.info("No sample data available.")

# Workforce
with tabs[3]:
    st.subheader("Inactive users (sample)")
    sample = safe_get(metrics, "inactive_users_sample", "inactiveUsersSample", default=[])
    if sample:
        st.dataframe(sample, use_container_width=True)
    else:
        st.info("No sample data available.")

    st.subheader("Contingent workers (sample)")
    sample = safe_get(metrics, "contingent_workers_sample", "contingentWorkersSample", default=[])
    if sample:
        st.dataframe(sample, use_container_width=True)
    else:
        st.info("No sample data available.")

# Raw JSON
with tabs[4]:
    st.subheader("Raw metrics JSON")
    st.code(json.dumps(metrics, indent=2), language="json")
