from __future__ import annotations

from urllib.parse import urlparse
import requests
import streamlit as st


# ----------------------------
# Page config
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
    if "://" not in u:
        u = "https://" + u
    return u.rstrip("/")


def host_of(u: str) -> str:
    u = norm_url(u)
    if not u:
        return ""
    return (urlparse(u).netloc or "").strip()


def backend_url_sane(u: str) -> tuple[bool, str]:
    """
    Catch common mistakes like: https://sf-ec-gates-backend. (trailing dot / missing domain)
    """
    if not u:
        return False, "Backend URL is required."
    h = host_of(u)
    if not h:
        return False, "Backend URL is invalid (missing host)."
    if h.endswith("."):
        return False, "Backend URL host ends with a dot. Remove the trailing '.'"
    if "." not in h:
        return False, "Backend URL host looks incomplete (no dot found)."
    return True, ""


def derive_api_candidates(instance_url: str) -> list[str]:
    """
    Provide candidate API bases from instance URL.
    IMPORTANT: We do NOT auto-select/use these.
    """
    host = host_of(instance_url)
    if not host:
        return []

    out: list[str] = []

    # hcmXX.sapsf.com -> apiXX.sapsf.com (also supports hcm41preview.sapsf.com -> api41preview.sapsf.com)
    if host.startswith("hcm") and host.endswith(".sapsf.com"):
        out.append("https://" + ("api" + host[3:]))

    # Generic: prefix api to host if not already
    if not host.startswith("api"):
        out.append("https://" + ("api" + host))

    # If user already pasted api host as "instance", just include it
    if host.startswith("api"):
        out.append("https://" + host)

    # de-dupe keep order
    uniq = []
    for x in out:
        x = norm_url(x)
        if x and x not in uniq:
            k = x
            uniq.append(k)
    return uniq


def safe_get(url: str, timeout: int = 25) -> dict:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def reset_tenant():
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


def metric_int(metrics: dict, *keys: str) -> int:
    """
    Return first present metric as int.
    """
    for k in keys:
        if k in metrics:
            try:
                return int(metrics.get(k) or 0)
            except Exception:
                return 0
    return 0


def pick_list(metrics: dict, *keys: str) -> list[dict]:
    for k in keys:
        v = metrics.get(k)
        if isinstance(v, list):
            return v
    return []


def show_table(rows: list[dict], title: str):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ----------------------------
# Session init
# ----------------------------
st.session_state.setdefault("tenant_locked", False)
st.session_state.setdefault("last_metrics", None)
st.session_state.setdefault("last_status", "empty")
st.session_state.setdefault("last_error", "")


# ----------------------------
# Sidebar
# ----------------------------
st.sidebar.markdown("## Connection")

backend_in = st.sidebar.text_input(
    "Backend URL",
    value=st.session_state.get("backend_url", ""),
    placeholder="https://sf-ec-gates-backend.onrender.com",
    disabled=st.session_state.tenant_locked,
)
backend_url = norm_url(backend_in)
st.session_state.backend_url = backend_url

sane, sane_msg = backend_url_sane(backend_url)
backend_ok = False
backend_err = ""

if backend_url:
    if not sane:
        backend_ok = False
        backend_err = sane_msg
        st.sidebar.error(backend_err)
    else:
        try:
            j = safe_get(f"{backend_url}/health", timeout=10)
            backend_ok = bool(j.get("ok") is True)
            if backend_ok:
                st.sidebar.success("Backend reachable ✅")
            else:
                st.sidebar.warning("Backend reachable, but health response is unexpected.")
        except Exception as e:
            backend_ok = False
            backend_err = str(e)
            st.sidebar.error(f"Backend not reachable: {backend_err}")
else:
    st.sidebar.info("Enter Backend URL to enable checks.")

st.sidebar.markdown("---")
st.sidebar.markdown("## Instance")

instance_in = st.sidebar.text_input(
    "Instance URL",
    value=st.session_state.get("instance_url", ""),
    placeholder="https://hcm41.sapsf.com or https://salesdemo.successfactors.eu",
    disabled=st.session_state.tenant_locked,
)
instance_url = norm_url(instance_in)
st.session_state.instance_url = instance_url

candidates = derive_api_candidates(instance_url)
st.sidebar.caption("Derived API base candidates (informational — not auto-used):")
if candidates:
    for c in candidates:
        st.sidebar.code(c, language="text")
else:
    st.sidebar.caption("—")

# DO NOT DEFAULT API URL
api_choice = st.sidebar.selectbox(
    "Select API base URL (required)",
    options=[""] + candidates,
    index=0,
    disabled=st.session_state.tenant_locked,
    help="Pick a candidate or use override. (We do not auto-default to prevent wrong-tenant calls.)",
)
st.session_state.api_choice = api_choice

api_override_in = st.sidebar.text_input(
    "API base override (optional)",
    value=st.session_state.get("api_override", ""),
    placeholder="https://apisalesdemo2.successfactors.eu",
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
)

st.session_state.sf_username = sf_username
st.session_state.sf_password = sf_password
st.session_state.company_id = company_id.strip()

st.sidebar.markdown("---")
c1, c2 = st.sidebar.columns(2)

with c1:
    if st.button("Use this tenant", disabled=st.session_state.tenant_locked):
        if not backend_url:
            st.sidebar.error("Backend URL is required.")
        elif not backend_ok:
            st.sidebar.error("Backend must be reachable.")
        elif not instance_url:
            st.sidebar.error("Instance URL is required.")
        elif not effective_api_base:
            st.sidebar.error("Select API base URL (or override).")
        elif not sf_username or not sf_password:
            st.sidebar.error("Username + Password are required.")
        else:
            st.session_state.tenant_locked = True
            st.sidebar.success("Tenant locked ✅")

with c2:
    if st.button("Logout / Reset", disabled=not st.session_state.tenant_locked):
        reset_tenant()
        st.rerun()


# ----------------------------
# Main header
# ----------------------------
st.markdown("# ✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

if not backend_ok:
    st.warning("Backend is not reachable. Fix Backend URL first.")
    st.stop()

if not st.session_state.tenant_locked:
    st.info("Fill the left sidebar and click **Use this tenant**. Then Run/Refresh.")
    st.stop()


# ----------------------------
# Actions
# ----------------------------
a, b, c = st.columns([1.2, 1.2, 2.6])
with a:
    run_now = st.button("🔄 Run live check now", use_container_width=True)
with b:
    refresh_now = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c:
    st.info("Tip: **Run** pulls live SF data via backend; **Refresh** loads the latest stored snapshot for this instance/company.")


def load_latest():
    params = {"instance_url": instance_url}
    if company_id.strip():
        params["company_id"] = company_id.strip()

    r = requests.get(f"{backend_url}/metrics/latest", params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()

    st.session_state.last_status = payload.get("status", "empty")
    st.session_state.last_metrics = payload.get("metrics")
    st.session_state.last_error = ""


def run_live():
    payload = {
        "instance_url": instance_url,
        "api_base_url": effective_api_base,
        "username": sf_username,
        "password": sf_password,
        "company_id": company_id.strip() or None,
        "timeout": 60,
        "verify_ssl": True,
    }
    r = requests.post(f"{backend_url}/run", json=payload, timeout=180)

    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"{r.status_code}: {detail}")

    data = r.json()
    st.session_state.last_metrics = data.get("metrics")
    st.session_state.last_status = "ok"
    st.session_state.last_error = ""


if refresh_now:
    try:
        load_latest()
    except Exception as e:
        st.session_state.last_error = str(e)
        st.error(f"Refresh failed: {st.session_state.last_error}")

if run_now:
    try:
        run_live()
    except Exception as e:
        st.session_state.last_error = str(e)
        st.error(f"Run failed: {st.session_state.last_error}")

# Auto-load once
if st.session_state.last_metrics is None and st.session_state.last_status == "empty":
    try:
        load_latest()
    except Exception:
        pass


# ----------------------------
# Render
# ----------------------------
metrics = st.session_state.last_metrics
status = st.session_state.last_status

if st.session_state.last_error:
    st.error(f"Run/Refresh error: {st.session_state.last_error}")

if status == "empty" or not metrics:
    st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
    st.stop()

snapshot_time = metrics.get("snapshot_time_utc") or "unknown"
st.caption(f"Snapshot UTC: {snapshot_time}")

# KPI Strip — match your gates.py keys
kpi_cols = st.columns(8)
kpis = [
    ("Active users", ("active_users",)),
    ("EmpJob rows", ("empjob_rows",)),
    ("Contingent", ("contingent_workers", "contingent_worker_count")),
    ("Inactive users", ("inactive_users", "inactive_user_count")),
    ("Missing managers", ("missing_manager_count", "missing_managers")),
    ("Invalid org", ("invalid_org_count", "invalid_org")),
    ("Missing emails", ("missing_email_count", "missing_emails")),
    ("Risk score", ("risk_score",)),
]
for col, (label, keys) in zip(kpi_cols, kpis):
    with col:
        st.metric(label, metric_int(metrics, *keys))

st.caption(
    f"Instance: {metrics.get('instance_url', instance_url)}  |  "
    f"API base: {metrics.get('api_base_url', effective_api_base)}  |  "
    f"Company: {metrics.get('company_id', company_id) or '—'}"
)

st.markdown("---")

# Tabs (stable)
tab_email, tab_org, tab_mgr, tab_work, tab_raw = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce", "🔎 Raw JSON"]
)

with tab_email:
    show_table(
        pick_list(metrics, "missing_email_sample", "missing_emails_sample"),
        "Missing emails (sample)",
    )
    st.markdown("---")
    show_table(
        pick_list(metrics, "duplicate_email_sample", "duplicate_emails_sample"),
        "Duplicate emails (sample)",
    )

with tab_org:
    show_table(
        pick_list(metrics, "invalid_org_sample"),
        "Invalid org (sample)",
    )
    st.markdown("---")
    st.subheader("Org missing field counts")
    st.json(metrics.get("org_missing_field_counts", {}))

with tab_mgr:
    show_table(
        pick_list(metrics, "missing_manager_sample", "missing_managers_sample"),
        "Missing managers (sample)",
    )

with tab_work:
    show_table(
        pick_list(metrics, "inactive_users_sample"),
        "Inactive users (sample)",
    )
    st.markdown("---")
    show_table(
        pick_list(metrics, "contingent_workers_sample"),
        "Contingent workers (sample)",
    )

with tab_raw:
    st.json(metrics)
