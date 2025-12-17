import os
import time
from typing import Any, Dict, Tuple, Optional

import requests
import streamlit as st
import pandas as pd


# -----------------------------
# Helpers
# -----------------------------
def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    return u.rstrip("/") if u else ""


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        # never dump huge HTML / stack traces to UI
        t = (resp.text or "").strip().replace("\n", " ")
        return {"detail": (t[:300] + ("…" if len(t) > 300 else ""))}


def api_get(url: str, timeout: int = 30) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)[:300]}


def api_post(url: str, timeout: int = 120) -> Tuple[bool, int, Dict[str, Any]]:
    try:
        r = requests.post(url, json={}, timeout=timeout)
        return r.ok, r.status_code, safe_json(r)
    except Exception as e:
        return False, 0, {"detail": str(e)[:300]}


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def sanitize_msg(msg: Any) -> str:
    """
    Prevent accidental rendering of large objects / stack traces / HTML.
    """
    if msg is None:
        return "Unknown error"
    s = str(msg)
    s = s.replace("\n", " ").strip()
    return s[:240] + ("…" if len(s) > 240 else "")


def render_api_error(
    title: str,
    http_code: int,
    payload: Dict[str, Any],
    *,
    show_tech: bool,
    hint: Optional[str] = None,
):
    detail = payload.get("detail") or payload.get("message") or "Request failed"
    st.error(f"{title} (HTTP {http_code}): {sanitize_msg(detail)}")
    if hint:
        st.info(hint)

    if show_tech:
        with st.expander("Show technical details"):
            st.write({"http_code": http_code, "payload": payload})


def show_table(title: str, rows: Any):
    st.subheader(title)
    if not rows:
        st.info("No sample data available.")
        return
    try:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception:
        st.info("Sample exists but cannot be rendered as a table.")
        st.write(rows)


def metric_card(label: str, value: Any, help_text: Optional[str] = None):
    v = value if value is not None else 0
    st.metric(label, v, help=help_text)


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="SuccessFactors EC Go-Live Gates", layout="wide")

st.title("✅ SuccessFactors EC Go-Live Gates (Streamlit UI + Render API)")

with st.sidebar:
    st.header("Connection")
    default_backend = os.getenv("BACKEND_URL") or ""
    backend_url = st.text_input(
        "Backend URL",
        value=default_backend,
        placeholder="https://your-render-backend",
        help="Example: https://sf-ec-gates-backend.onrender.com",
    )
    backend_url = normalize_base_url(backend_url)

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    st.divider()
    st.subheader("Refresh")
    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_secs = st.slider("Refresh every (seconds)", 10, 120, 30, disabled=not auto_refresh)

    st.divider()
    st.subheader("Display")
    show_tech_details = st.toggle("Show technical details", value=False)
    show_raw_json_tab = st.toggle("Show Raw JSON tab", value=True)

    st.divider()
    st.subheader("PDF export")
    include_samples_pdf = st.toggle("Include samples in PDF", value=False)
    st.caption("PDF export wiring is optional; this toggle is reserved for later.")


status_box = st.empty()

if not backend_url:
    status_box.warning("Enter your Render backend URL to continue.")
    st.stop()

# Health check (GET /health)
ok, code, data = api_get(f"{backend_url}/health", timeout=20)
if ok:
    status_box.success("Backend reachable ✅")
else:
    render_api_error(
        "Backend not healthy",
        code,
        data,
        show_tech=show_tech_details,
        hint="Check Render logs. Also confirm your backend exposes GET /health.",
    )
    st.stop()

# Actions
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    run_clicked = st.button("🔄 Run live check now", use_container_width=True)
with c2:
    refresh_clicked = st.button("🧾 Refresh latest snapshot", use_container_width=True)
with c3:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

# Run now (POST /run)
if run_clicked:
    with st.spinner("Running checks via backend..."):
        ok_run, code_run, out = api_post(f"{backend_url}/run", timeout=240)
    if ok_run:
        st.success("Run completed ✅")
        st.session_state["force_refresh"] = True
    else:
        render_api_error(
            "Run failed",
            code_run,
            out,
            show_tech=show_tech_details,
            hint="If you see HTTP 500, open Render logs — it’s a backend error (often a missing function/field).",
        )

if refresh_clicked:
    st.session_state["force_refresh"] = True

# Auto-refresh tick (no loops)
if auto_refresh:
    now_ts = time.time()
    last = st.session_state.get("last_refresh_ts", 0.0)
    if (now_ts - last) > refresh_secs:
        st.session_state["force_refresh"] = True
        st.session_state["last_refresh_ts"] = now_ts

# Fetch latest snapshot (GET /metrics/latest)
# If force_refresh is set, clear it after attempt (so it doesn't keep triggering)
if st.session_state.get("force_refresh"):
    st.session_state["force_refresh"] = False

ok_m, code_m, payload = api_get(f"{backend_url}/metrics/latest", timeout=30)
if not ok_m:
    render_api_error(
        "Could not fetch latest snapshot",
        code_m,
        payload,
        show_tech=show_tech_details,
        hint="Confirm your backend exposes GET /metrics/latest and returns JSON.",
    )
    st.stop()

if payload.get("status") == "empty":
    st.warning("No snapshots found yet. Click **Run live check now**.")
    st.stop()

metrics = payload.get("metrics") or {}
snapshot_time = metrics.get("snapshot_time_utc", "unknown")

# KPI row
k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
with k1:
    metric_card("Active users", as_int(metrics.get("active_users")), help_text="Should be based on EmpJob employee status in backend.")
with k2:
    metric_card("EmpJob rows", as_int(metrics.get("empjob_rows") or metrics.get("current_empjob_rows")))
with k3:
    metric_card(
        "Contingent workers",
        as_int(metrics.get("contingent_workers")),
        help_text=metrics.get("contingent_source") or "Backend determines source (prefer EmpEmployment.isContingentWorker).",
    )
with k4:
    metric_card(
        "Inactive users",
        as_int(metrics.get("inactive_users")),
        help_text=metrics.get("employee_status_source") or "Backend determines source (prefer EmpJob.emplStatus).",
    )
with k5:
    metric_card("Missing managers", as_int(metrics.get("missing_manager_count")))
with k6:
    metric_card("Invalid org", as_int(metrics.get("invalid_org_count")))
with k7:
    metric_card("Missing emails", as_int(metrics.get("missing_email_count")), help_text="Calculated for active population in backend.")
with k8:
    metric_card("Risk score", as_int(metrics.get("risk_score")))

st.caption(f"Snapshot UTC: {snapshot_time}")

# Tabs
tabs = ["📧 Email hygiene", "🧩 Org checks", "👤 Workforce", "👥 Manager checks"]
if show_raw_json_tab:
    tabs.append("🔎 Raw JSON")

tab_objs = st.tabs(tabs)

# 1) Email hygiene
with tab_objs[0]:
    missing_cnt = as_int(metrics.get("missing_email_count"))
    missing_sample = metrics.get("missing_email_sample") or []

    if missing_cnt > 0 and not missing_sample:
        st.warning(
            "Missing emails count is > 0, but sample is empty. "
            "That means the backend did not send sample rows (or is filtering incorrectly)."
        )

    show_table("Missing emails (sample)", missing_sample)
    show_table("Duplicate emails (sample)", metrics.get("duplicate_email_sample"))

# 2) Org checks
with tab_objs[1]:
    show_table("Invalid org assignments (sample)", metrics.get("invalid_org_sample"))
    st.subheader("Missing org field counts")
    counts = metrics.get("org_missing_field_counts") or {}
    if counts:
        st.dataframe(pd.DataFrame([counts]), use_container_width=True, hide_index=True)
    else:
        st.info("No org missing-field breakdown available.")

# 3) Workforce (inactive + contingent)
with tab_objs[2]:
    cA, cB, cC = st.columns([1, 1, 2])
    with cA:
        metric_card("Inactive users", as_int(metrics.get("inactive_users")))
    with cB:
        metric_card("Contingent workers", as_int(metrics.get("contingent_workers")))
    with cC:
        ca = metrics.get("contingent_workers_active")
        if ca is not None:
            st.info(f"Contingent workers (active): **{as_int(ca)}**")
        else:
            st.caption("Optional: backend can return contingent_workers_active.")

    st.divider()

    # Breakdown by employee status (if backend provides it)
    by_status = metrics.get("inactive_users_by_status")
    if isinstance(by_status, dict) and by_status:
        st.subheader("Inactive users by Employee Status")
        df = pd.DataFrame(
            [{"Employee Status": k, "Count": as_int(v)} for k, v in by_status.items()]
        ).sort_values("Count", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info(
            "Inactive-by-status breakdown not available. "
            "Backend should return inactive_users_by_status (from EmpJob employee status)."
        )

    st.divider()
    show_table("Inactive users (sample)", metrics.get("inactive_users_sample"))
    show_table("Contingent workers (sample)", metrics.get("contingent_workers_sample"))

# 4) Manager checks
with tab_objs[3]:
    show_table("Missing managers (sample)", metrics.get("missing_manager_sample"))

# 5) Raw JSON (optional)
if show_raw_json_tab:
    with tab_objs[-1]:
        st.caption("This is the raw metrics payload returned by the backend.")
        st.json(metrics)
