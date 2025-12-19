import os
import time
import re
import traceback
from typing import Any, Dict, Tuple, Optional
from urllib.parse import urlparse

import streamlit as st


# -----------------------------
# Safe imports (so we can show errors in UI)
# -----------------------------
try:
    import requests
except Exception:
    requests = None

try:
    import pandas as pd
except Exception:
    pd = None


# -----------------------------
# URL + API derivation helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    return u.rstrip("/") if u else ""


def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u
    return u.rstrip("/")


def derive_sf_api_base(instance_url: str) -> str:
    u = normalize_url(instance_url)
    if not u:
        return ""

    p = urlparse(u)
    host = (p.netloc or "").lower()

    if host.startswith("api"):
        return f"{p.scheme}://{host}"

    m = re.match(r"^performancemanager(\d+)\.successfactors\.com$", host)
    if m:
        return f"{p.scheme}://api{m.group(1)}.successfactors.com"

    if ".successfactors." in host:
        parts = host.split(".")
        if parts and not parts[0].startswith("api"):
            parts[0] = "api" + parts[0]
            return f"{p.scheme}://{'.'.join(parts)}"

    return f"{p.scheme}://{host}"


# -----------------------------
# HTTP helpers
# -----------------------------
def safe_json(resp) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"detail": (getattr(resp, "text", "") or "")[:500]}


def api_get(url: str, timeout: int = 30, params: Optional[dict] = None) -> Tuple[bool, int, Dict[str, Any]]:
    if requests is None:
        return False, 0, {"detail": "requests is not installed"}
    try:
        r = requests.get(url, params=params, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def api_post(url: str, timeout: int = 120, payload: Optional[dict] = None) -> Tuple[bool, int, Dict[str, Any]]:
    if requests is None:
        return False, 0, {"detail": "requests is not installed"}
    try:
        r = requests.post(url, json=(payload or {}), timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)}


def as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def show_table(title: str, rows: Any):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    if pd is None:
        st.warning("pandas is not installed, cannot render tables.")
        st.json(rows)
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# -----------------------------
# App (wrapped so UI never blanks)
# -----------------------------
def main():
    st.set_page_config(page_title="YASH HealthFactors - EC Health Check", layout="wide")

    # Always render something immediately
    st.title("✅ YASH HealthFactors - SAP SuccessFactors EC Health Check")
    st.caption("If this page ever goes blank, the error will be printed below in red (failsafe mode).")

    with st.sidebar:
        st.header("Connection")

        default_backend = os.getenv("BACKEND_URL") or ""
        backend_url = st.text_input(
            "Backend URL",
            value=default_backend,
            placeholder="https://your-render-backend",
        )
        backend_url = normalize_base_url(backend_url)

        instance_url = st.text_input(
            "Instance URL",
            value="",
            placeholder="e.g. https://salesdemo2.successfactors.eu",
        )
        instance_url = normalize_url(instance_url)

        derived_api_base = derive_sf_api_base(instance_url) if instance_url else ""
        st.text_input("Derived API base URL", value=derived_api_base, disabled=True)

        api_base_override = st.text_input(
            "API base override (optional)",
            value="",
            placeholder="https://apisalesdemo2.successfactors.eu",
        )
        api_base_override = normalize_url(api_base_override)

        effective_api_base = api_base_override or derived_api_base
        st.caption("Streamlit calls Render. Render calls SuccessFactors.")

        auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
        refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

        st.divider()
        show_raw_json = st.toggle("Show raw JSON (advanced)", value=False)

    # Backend health (don’t stop the app — show warnings instead)
    if not backend_url:
        st.warning("Enter your Render backend URL in the sidebar.")
        st.stop()

    ok, code, data = api_get(f"{backend_url}/health", timeout=20)
    if ok:
        st.success("Backend reachable ✅")
    else:
        st.error(f"Backend not healthy (HTTP {code}): {data.get('detail') or data}")
        st.stop()

    # Actions
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        run_clicked = st.button("🔄 Run live check now", use_container_width=True)
    with c2:
        refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
    with c3:
        st.info("Tip: Run live check to pull real-time SF data via backend.")

    if run_clicked:
        if not effective_api_base:
            st.error("Please enter Instance URL (or API base override).")
        else:
            with st.spinner("Running checks via backend..."):
                ok_run, code_run, out = api_post(
                    f"{backend_url}/run",
                    timeout=240,
                    payload={"instance_url": effective_api_base},
                )
            if ok_run:
                st.success("Run completed ✅")
                st.session_state["force_refresh"] = True
            else:
                st.error(f"Run failed (HTTP {code_run}): {out.get('detail') or out}")

    if refresh_clicked:
        st.session_state["force_refresh"] = True

    if auto_refresh:
        now_ts = time.time()
        last = st.session_state.get("last_refresh_ts", 0)
        if (now_ts - last) > refresh_secs:
            st.session_state["force_refresh"] = True
            st.session_state["last_refresh_ts"] = now_ts

    # Fetch metrics
    params = {}
    if effective_api_base:
        params["instance_url"] = effective_api_base

    if st.session_state.get("force_refresh"):
        st.session_state["force_refresh"] = False

    ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", timeout=30, params=params)
    if not ok_m:
        st.error(f"Could not fetch latest snapshot (HTTP {code_m}): {payload.get('detail') or payload}")
        st.stop()

    if payload.get("status") == "empty":
        st.warning("No snapshots found yet. Click Run live check now.")
        st.stop()

    metrics = payload.get("metrics") or {}
    snapshot_time = metrics.get("snapshot_time_utc", "unknown")

    # KPIs
    k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
    k1.metric("Active users", as_int(metrics.get("active_users")))
    k2.metric("EmpJob rows", as_int(metrics.get("empjob_rows") or metrics.get("current_empjob_rows")))
    k3.metric("Contingent workers", as_int(metrics.get("contingent_workers")))
    k4.metric("Inactive users", as_int(metrics.get("inactive_users")))
    k5.metric("Missing managers", as_int(metrics.get("missing_manager_count")))
    k6.metric("Invalid org", as_int(metrics.get("invalid_org_count")))
    k7.metric("Missing emails", as_int(metrics.get("missing_email_count")))
    k8.metric("Risk score", as_int(metrics.get("risk_score")))
    st.caption(f"Snapshot UTC: {snapshot_time}")

    tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🧩 Org checks", "👤 Manager checks", "👥 Workforce"])
    with tab1:
        show_table("Missing emails (sample)", metrics.get("missing_email_sample"))
        show_table("Duplicate emails (sample)", metrics.get("duplicate_email_sample"))
    with tab2:
        show_table("Invalid org assignments (sample)", metrics.get("invalid_org_sample"))
        st.subheader("Missing org field counts")
        counts = metrics.get("org_missing_field_counts") or {}
        if counts and pd is not None:
            st.dataframe(pd.DataFrame([counts]), use_container_width=True, hide_index=True)
        elif counts:
            st.json(counts)
        else:
            st.info("No org missing-field breakdown available.")
    with tab3:
        show_table("Missing managers (sample)", metrics.get("missing_manager_sample"))
    with tab4:
        show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
        show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

    if show_raw_json:
        st.divider()
        st.subheader("Raw JSON (advanced)")
        st.json(metrics)


try:
    main()
except Exception:
    st.error("App crashed while rendering. Full error below:")
    st.code(traceback.format_exc())
