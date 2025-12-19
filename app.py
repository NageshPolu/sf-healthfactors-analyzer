# app.py
from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st


# -----------------------------
# Helpers
# -----------------------------
def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    return u.rstrip("/")


def derive_api_base_from_instance(instance_url: str) -> str:
    """
    Best-effort derivation.
    Typical:
      https://hcm41.sapsf.com           -> https://api41.sapsf.com
      https://hcm41preview.sapsf.com    -> https://api41preview.sapsf.com
    If it can't derive confidently, returns the instance host as-is (user can override).
    """
    instance_url = normalize_url(instance_url)
    if not instance_url:
        return ""

    try:
        p = urlparse(instance_url if "://" in instance_url else f"https://{instance_url}")
        host = (p.netloc or "").lower()
        if not host:
            return ""

        # If already api*
        if host.startswith("api"):
            return f"https://{host}"

        # If hcm* => replace leading "hcm" with "api"
        if host.startswith("hcm"):
            return f"https://api{host[3:]}"  # swap prefix only

        # Fallback: if they typed a non-hcm instance, return same host
        return f"https://{host}"
    except Exception:
        return ""


def safe_get(d: dict, key: str, default=None):
    if not isinstance(d, dict):
        return default
    return d.get(key, default)


def backend_health(backend_url: str) -> tuple[bool, str]:
    backend_url = normalize_url(backend_url)
    if not backend_url:
        return False, "Backend URL missing"

    try:
        r = requests.get(f"{backend_url}/health", timeout=10)
        if r.status_code == 200:
            return True, "Backend reachable ✅"
        return False, f"Backend not healthy (HTTP {r.status_code})"
    except Exception as e:
        return False, f"Backend not reachable: {e}"


def call_run(
    backend_url: str,
    instance_url: str,
    api_base_url: str,
    username: str,
    password: str,
    company_id: str | None,
    timeout_s: int | None,
    verify_ssl: bool | None,
) -> dict:
    payload = {
        "instance_url": normalize_url(instance_url),
        "api_base_url": normalize_url(api_base_url),
        "username": (username or "").strip(),
        "password": password or "",
        "company_id": (company_id or "").strip() or None,
        "timeout": timeout_s,
        "verify_ssl": verify_ssl,
    }
    r = requests.post(f"{normalize_url(backend_url)}/run", json=payload, timeout=120)
    if r.status_code >= 400:
        # FastAPI returns {"detail": "..."} usually
        try:
            j = r.json()
            detail = j.get("detail") or r.text
        except Exception:
            detail = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def call_latest(backend_url: str, instance_url: str, company_id: str | None) -> dict:
    params = {}
    if normalize_url(instance_url):
        params["instance_url"] = normalize_url(instance_url)
    if (company_id or "").strip():
        params["company_id"] = (company_id or "").strip()

    r = requests.get(f"{normalize_url(backend_url)}/metrics/latest", params=params, timeout=30)
    if r.status_code >= 400:
        try:
            j = r.json()
            detail = j.get("detail") or r.text
        except Exception:
            detail = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def render_kpis(metrics: dict):
    cols = st.columns(8)
    cols[0].metric("Active users", safe_get(metrics, "active_users", 0))
    cols[1].metric("EmpJob rows", safe_get(metrics, "empjob_rows", 0))
    cols[2].metric("Contingent workers", safe_get(metrics, "contingent_workers", 0))
    cols[3].metric("Inactive users", safe_get(metrics, "inactive_users", 0))
    cols[4].metric("Missing managers", safe_get(metrics, "missing_managers", 0))
    cols[5].metric("Invalid org", safe_get(metrics, "invalid_org", 0))
    cols[6].metric("Missing emails", safe_get(metrics, "missing_emails", 0))
    cols[7].metric("Risk score", safe_get(metrics, "risk_score", 0))

    st.caption(f"Snapshot UTC: {safe_get(metrics, 'snapshot_time_utc', 'unknown')}")
    inst = safe_get(metrics, "instance_url", "")
    api = safe_get(metrics, "api_base_url", "")
    comp = safe_get(metrics, "company_id", "")
    st.caption(f"Instance: {inst or '—'}  |  API base: {api or '—'}  |  Company: {comp or '—'}")

    st.caption(
        f"Employee status source: {safe_get(metrics, 'employee_status_source', 'unknown')} "
        f"• Contingent source: {safe_get(metrics, 'contingent_source', 'unknown')}"
    )


def render_table(sample: list[dict], title: str):
    st.subheader(title)
    if not sample:
        st.info("No sample data available.")
        return
    df = pd.DataFrame(sample)
    st.dataframe(df, use_container_width=True, hide_index=True)


# -----------------------------
# Page
# -----------------------------
st.set_page_config(page_title="YASH HealthFactors - SAP SuccessFactors EC Health Check", layout="wide")

st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

# -----------------------------
# Sidebar: Connection / Inputs
# -----------------------------
with st.sidebar:
    st.header("Connection")

    backend_url = st.text_input("Backend URL", value=st.session_state.get("backend_url", ""), placeholder="https://your-backend.onrender.com")
    backend_url = normalize_url(backend_url)
    st.session_state["backend_url"] = backend_url

    ok, msg = backend_health(backend_url) if backend_url else (False, "Enter backend URL")
    if ok:
        st.success(msg)
    else:
        st.warning(msg)

    st.divider()
    st.subheader("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        placeholder="https://hcm41.sapsf.com",
    )
    instance_url = normalize_url(instance_url)
    st.session_state["instance_url"] = instance_url

    derived_api = derive_api_base_from_instance(instance_url)
    st.text_input("Derived API base URL", value=derived_api, disabled=True)

    api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_override", ""),
        placeholder="https://apisalesdemo2.successfactors.eu",
    )
    api_override = normalize_url(api_override)
    st.session_state["api_override"] = api_override

    effective_api = api_override or derived_api
    st.caption(f"Effective API base: {effective_api or '—'}")

    st.divider()
    st.subheader("Credentials (per tenant)")

    username = st.text_input("SF Username", value=st.session_state.get("sf_username", ""))
    st.session_state["sf_username"] = username

    password = st.text_input("SF Password", type="password", value=st.session_state.get("sf_password", ""))
    st.session_state["sf_password"] = password

    company_id = st.text_input("Company ID (optional)", value=st.session_state.get("company_id", ""))
    st.session_state["company_id"] = company_id

    st.divider()
    st.subheader("Network / Runtime")

    verify_ssl = st.checkbox("Verify SSL", value=st.session_state.get("verify_ssl", True))
    st.session_state["verify_ssl"] = verify_ssl

    timeout_s = st.number_input("SF request timeout (seconds)", min_value=10, max_value=300, value=int(st.session_state.get("timeout_s", 60)))
    st.session_state["timeout_s"] = timeout_s

    st.divider()
    st.subheader("Auto-refresh latest snapshot")
    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=st.session_state.get("auto_refresh", False))
    st.session_state["auto_refresh"] = auto_refresh

    refresh_every = st.slider("Refresh every (seconds)", min_value=10, max_value=120, value=int(st.session_state.get("refresh_every", 30)))
    st.session_state["refresh_every"] = refresh_every

    st.divider()
    st.subheader("Display")
    show_raw_json = st.toggle("Show raw JSON (advanced)", value=st.session_state.get("show_raw_json", False))
    st.session_state["show_raw_json"] = show_raw_json


# -----------------------------
# Main actions
# -----------------------------
action_cols = st.columns([1, 1, 3])
run_clicked = action_cols[0].button("🔁 Run live check now", use_container_width=True, disabled=not ok)
refresh_clicked = action_cols[1].button("🧾 Refresh latest snapshot", use_container_width=True, disabled=not ok)
action_cols[2].info("Tip: Run pulls live SF data via backend; Refresh loads the latest snapshot for the selected instance.")

# Storage for latest metrics in session
if "metrics" not in st.session_state:
    st.session_state["metrics"] = None
if "last_error" not in st.session_state:
    st.session_state["last_error"] = None

# If instance/company changes, clear shown metrics to avoid confusion
current_key = f"{normalize_url(instance_url)}|{(company_id or '').strip()}"
if st.session_state.get("scope_key") != current_key:
    st.session_state["scope_key"] = current_key
    st.session_state["metrics"] = None
    st.session_state["last_error"] = None

# -----------------------------
# Run action
# -----------------------------
def validate_inputs() -> list[str]:
    problems = []
    if not backend_url:
        problems.append("Backend URL is required")
    if not instance_url:
        problems.append("Instance URL is required")
    if not effective_api:
        problems.append("API base URL could not be derived; set API base override")
    if not (username or "").strip():
        problems.append("SF Username is required")
    if not (password or "").strip():
        problems.append("SF Password is required")
    return problems


if run_clicked:
    probs = validate_inputs()
    if probs:
        st.session_state["last_error"] = " • ".join(probs)
    else:
        try:
            st.session_state["last_error"] = None
            with st.spinner("Running health check via backend..."):
                _ = call_run(
                    backend_url=backend_url,
                    instance_url=instance_url,
                    api_base_url=effective_api,
                    username=username,
                    password=password,
                    company_id=company_id,
                    timeout_s=int(timeout_s),
                    verify_ssl=bool(verify_ssl),
                )
            # Always refresh after run to show latest stored snapshot
            latest = call_latest(backend_url, instance_url, company_id)
            if latest.get("status") == "ok":
                st.session_state["metrics"] = latest.get("metrics")
            else:
                st.session_state["metrics"] = None
                st.session_state["last_error"] = "Run succeeded but no snapshot returned by /metrics/latest."
        except Exception as e:
            st.session_state["metrics"] = None
            st.session_state["last_error"] = f"Run failed: {e}"

# -----------------------------
# Refresh action
# -----------------------------
if refresh_clicked:
    try:
        st.session_state["last_error"] = None
        with st.spinner("Loading latest snapshot..."):
            latest = call_latest(backend_url, instance_url, company_id)
        if latest.get("status") == "ok":
            st.session_state["metrics"] = latest.get("metrics")
        else:
            st.session_state["metrics"] = None
            st.session_state["last_error"] = "No snapshots found yet for this instance/company. Click Run live check now."
    except Exception as e:
        st.session_state["metrics"] = None
        st.session_state["last_error"] = f"Refresh failed: {e}"

# -----------------------------
# Auto refresh loop (non-blocking pattern)
# -----------------------------
if auto_refresh and ok and not run_clicked:
    # Refresh silently every N seconds
    now = time.time()
    last = st.session_state.get("last_auto_refresh_ts", 0.0)
    if now - last >= float(refresh_every):
        st.session_state["last_auto_refresh_ts"] = now
        try:
            latest = call_latest(backend_url, instance_url, company_id)
            if latest.get("status") == "ok":
                st.session_state["metrics"] = latest.get("metrics")
        except Exception:
            pass


# -----------------------------
# Display
# -----------------------------
if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])

metrics = st.session_state.get("metrics")
if metrics:
    st.success("Run completed ✅" if not st.session_state.get("last_error") else "Loaded snapshot ✅")
    render_kpis(metrics)

    tab_email, tab_org, tab_mgr, tab_workforce, tab_raw = st.tabs(
        ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce", "🔎 Raw JSON"]
    )

    with tab_email:
        render_table(safe_get(metrics, "missing_emails_sample", []) or [], "Missing emails (sample)")
        render_table(safe_get(metrics, "duplicate_emails_sample", []) or [], "Duplicate emails (sample)")

    with tab_org:
        render_table(safe_get(metrics, "invalid_org_sample", []) or [], "Invalid org assignments (sample)")

    with tab_mgr:
        render_table(safe_get(metrics, "missing_managers_sample", []) or [], "Missing managers (sample)")

    with tab_workforce:
        render_table(safe_get(metrics, "inactive_users_sample", []) or [], "Inactive users (sample)")
        render_table(safe_get(metrics, "contingent_workers_sample", []) or [], "Contingent workers (sample)")

    with tab_raw:
        if show_raw_json:
            st.code(json.dumps(metrics, indent=2), language="json")
        else:
            st.info("Enable **Show raw JSON (advanced)** in the sidebar to view the full payload.")
else:
    st.warning("No snapshot loaded yet for this instance/company. Click **Run live check now** or **Refresh latest snapshot**.")
