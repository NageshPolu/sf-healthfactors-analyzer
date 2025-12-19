# app.py
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

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
    Best-effort derivation for SAP SuccessFactors OData base.
    Examples:
      https://hcm41.sapsf.com -> https://api41.sapsf.com
      https://hcm41preview.sapsf.com -> https://api41preview.sapsf.com
    If pattern doesn't match, returns empty string (user can override manually).
    """
    inst = normalize_url(instance_url)
    if not inst:
        return ""

    m = re.match(r"^https?://hcm(\d+)(preview)?\.sapsf\.com$", inst, re.IGNORECASE)
    if not m:
        return ""

    num = m.group(1)
    preview = m.group(2) or ""
    return f"https://api{num}{preview}.sapsf.com"


def safe_get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def call_backend_get(url: str, params: dict | None = None, timeout: int = 60) -> dict:
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def call_backend_post(url: str, payload: dict, timeout: int = 120) -> dict:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def render_sample_table(title: str, rows: list[dict], max_rows: int = 50):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    st.dataframe(rows[:max_rows], use_container_width=True, hide_index=True)


# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="YASH HealthFactors - SAP SuccessFactors EC Health Check",
    page_icon="✅",
    layout="wide",
)

st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")

# -----------------------------
# Sidebar: Connection + Instance
# -----------------------------
with st.sidebar:
    st.header("Connection")

    backend_url = st.text_input(
        "Backend URL",
        value=st.session_state.get("backend_url", "https://sf-ec-gates-backend.onrender.com"),
        help="Streamlit calls this backend; backend calls SuccessFactors OData.",
    )
    backend_url = normalize_url(backend_url)
    st.session_state["backend_url"] = backend_url

    st.divider()
    st.header("Instance")

    instance_url = st.text_input(
        "Instance URL",
        value=st.session_state.get("instance_url", ""),
        help="Example: https://hcm41.sapsf.com or https://hcm41preview.sapsf.com",
    )
    instance_url = normalize_url(instance_url)

    # If instance changed, clear API override to prevent “old tenant still used”
    prev_instance = st.session_state.get("_prev_instance_url", "")
    if prev_instance and prev_instance != instance_url:
        st.session_state["api_base_override"] = ""
    st.session_state["_prev_instance_url"] = instance_url
    st.session_state["instance_url"] = instance_url

    derived_api = derive_api_base_from_instance(instance_url)
    st.text_input("Derived API base URL", value=derived_api or "", disabled=True)

    api_override = st.text_input(
        "API base override (optional)",
        value=st.session_state.get("api_base_override", ""),
        help="If derivation is wrong for your tenant, paste the correct OData host here.",
    )
    api_override = normalize_url(api_override)
    st.session_state["api_base_override"] = api_override

    effective_api_base = api_override or derived_api
    st.caption("Effective API base:")
    if effective_api_base:
        st.markdown(f"[{effective_api_base}]({effective_api_base})")
    else:
        st.warning("Could not derive API base. Provide API base override.")

    st.divider()

    auto_refresh = st.toggle(
        "Auto-refresh latest snapshot",
        value=st.session_state.get("auto_refresh", False),
    )
    st.session_state["auto_refresh"] = auto_refresh

    refresh_seconds = st.slider(
        "Refresh every (seconds)",
        min_value=10,
        max_value=120,
        value=int(st.session_state.get("refresh_seconds", 30)),
        step=5,
        disabled=not auto_refresh,
    )
    st.session_state["refresh_seconds"] = refresh_seconds

    st.divider()
    show_raw = st.toggle("Show raw JSON (advanced)", value=st.session_state.get("show_raw", False))
    st.session_state["show_raw"] = show_raw


# -----------------------------
# Top: backend health
# -----------------------------
backend_ok = False
health_error = None
if backend_url:
    try:
        health = call_backend_get(f"{backend_url}/health", timeout=20)
        backend_ok = bool(health.get("ok"))
    except Exception as e:
        health_error = str(e)

if backend_ok:
    st.success("Backend reachable ✅")
else:
    st.error("Backend not reachable ❌")
    if health_error:
        st.caption(health_error)

# -----------------------------
# Actions: Run + Refresh
# -----------------------------
col1, col2, col3 = st.columns([1.2, 1.2, 2.6])
with col1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True, disabled=not backend_ok)
with col2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True, disabled=not backend_ok)
with col3:
    st.info("Tip: **Run** pulls live SF data via backend; **Refresh** loads the latest snapshot for the selected instance.")


def fetch_latest_snapshot() -> dict:
    if not backend_url:
        return {"status": "empty"}
    params = {}
    if instance_url:
        params["instance_url"] = instance_url
    return call_backend_get(f"{backend_url}/metrics/latest", params=params, timeout=60)


# Run now
if run_clicked:
    if not instance_url:
        st.error("Instance URL is required.")
    elif not effective_api_base:
        st.error("Effective API base is empty. Provide API base override (or use a derivable instance URL).")
    else:
        payload = {
            "instance_url": instance_url,
            "api_base_url": effective_api_base,
        }
        try:
            resp = call_backend_post(f"{backend_url}/run", payload=payload, timeout=180)
            metrics = resp.get("metrics") or {}
            st.session_state["latest_metrics"] = metrics
            st.success("Run completed ✅")
        except requests.HTTPError as e:
            # Backend returns FastAPI detail
            try:
                detail = e.response.json().get("detail")
            except Exception:
                detail = e.response.text
            st.error(f"Run failed (HTTP {e.response.status_code}): {detail}")
        except Exception as e:
            st.error(f"Run failed: {e}")

# Refresh latest
if refresh_clicked:
    try:
        snap = fetch_latest_snapshot()
        if snap.get("status") == "ok":
            st.session_state["latest_metrics"] = snap.get("metrics") or {}
            st.success("Loaded latest snapshot ✅")
        else:
            st.warning("No snapshots found yet for this instance. Click Run live check now.")
    except Exception as e:
        st.error(f"Refresh failed: {e}")


# Auto-refresh (best-effort)
if backend_ok and st.session_state.get("auto_refresh") and instance_url:
    # Use Streamlit's autorefresh if available; otherwise do nothing (manual refresh still works)
    try:
        # Streamlit provides st_autorefresh in many versions
        from streamlit import st_autorefresh  # type: ignore

        st_autorefresh(interval=st.session_state["refresh_seconds"] * 1000, key="auto_refresh_key")
        try:
            snap = fetch_latest_snapshot()
            if snap.get("status") == "ok":
                st.session_state["latest_metrics"] = snap.get("metrics") or {}
        except Exception:
            pass
    except Exception:
        pass


# -----------------------------
# Display metrics
# -----------------------------
metrics: dict = st.session_state.get("latest_metrics") or {}

# If no metrics loaded yet, try to load latest (instance-scoped)
if backend_ok and not metrics:
    try:
        snap = fetch_latest_snapshot()
        if snap.get("status") == "ok":
            metrics = snap.get("metrics") or {}
            st.session_state["latest_metrics"] = metrics
    except Exception:
        pass

snapshot_time = metrics.get("snapshot_time_utc") or "unknown"

# KPI row
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
k1.metric("Active users", safe_get(metrics, "kpis", "active_users", default=0))
k2.metric("EmpJob rows", safe_get(metrics, "kpis", "empjob_rows", default=0))
k3.metric("Contingent workers", safe_get(metrics, "kpis", "contingent_workers", default=0))
k4.metric("Inactive users", safe_get(metrics, "kpis", "inactive_users", default=0))
k5.metric("Missing managers", safe_get(metrics, "kpis", "missing_managers", default=0))
k6.metric("Invalid org", safe_get(metrics, "kpis", "invalid_org", default=0))
k7.metric("Missing emails", safe_get(metrics, "kpis", "missing_emails", default=0))
k8.metric("Risk score", safe_get(metrics, "kpis", "risk_score", default=0))

st.caption(f"Snapshot UTC: {snapshot_time}")

instance_used = metrics.get("instance_url") or instance_url or ""
api_used = metrics.get("api_base_url") or ""
if instance_used or api_used:
    st.caption(f"Instance: {instance_used or '—'} | API base: {api_used or '—'}")

status_source = metrics.get("employee_status_source") or ""
cont_source = metrics.get("contingent_source") or ""
if status_source or cont_source:
    st.caption(f"Employee status source: {status_source or 'unknown'} • Contingent source: {cont_source or 'unknown'}")


# -----------------------------
# Tabs
# -----------------------------
tab_email, tab_org, tab_mgr, tab_workforce, tab_raw = st.tabs(
    ["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "🧑‍🤝‍🧑 Workforce", "🔎 Raw JSON"]
)

with tab_email:
    render_sample_table("Missing emails (sample)", safe_get(metrics, "samples", "missing_emails", default=[]))
    render_sample_table("Duplicate emails (sample)", safe_get(metrics, "samples", "duplicate_emails", default=[]))

with tab_org:
    render_sample_table("Invalid org assignments (sample)", safe_get(metrics, "samples", "invalid_org", default=[]))

with tab_mgr:
    render_sample_table("Missing managers (sample)", safe_get(metrics, "samples", "missing_managers", default=[]))

with tab_workforce:
    render_sample_table("Inactive users (sample)", safe_get(metrics, "samples", "inactive_users", default=[]))
    render_sample_table("Contingent workers (sample)", safe_get(metrics, "samples", "contingent_workers", default=[]))

with tab_raw:
    if st.session_state.get("show_raw"):
        st.json(metrics)
    else:
        st.info("Enable **Show raw JSON (advanced)** in the sidebar to view the full payload.")
