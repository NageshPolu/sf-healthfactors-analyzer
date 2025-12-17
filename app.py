import io
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

# -----------------------------
# Config
# -----------------------------
DEFAULT_BACKEND_URL = (
    st.secrets.get("BACKEND_URL", None)
    if hasattr(st, "secrets")
    else None
) or "https://your-render-backend.onrender.com"

REQUEST_TIMEOUT = 60


# -----------------------------
# Helpers
# -----------------------------
def _safe_int(x, default=0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def _safe_list(x):
    return x if isinstance(x, list) else []


def _safe_dict(x):
    return x if isinstance(x, dict) else {}


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "-"
    # Accept ISO strings; render nicely
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts


def api_health(base_url: str) -> tuple[bool, str]:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/health", timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return True, "Backend reachable ✅"
        return False, f"Backend not healthy (HTTP {r.status_code})"
    except Exception as e:
        return False, f"Backend unreachable ❌ ({e})"


def api_run_now(base_url: str) -> tuple[bool, str]:
    try:
        r = requests.post(f"{base_url.rstrip('/')}/run", timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ts = data.get("snapshot_time_utc") or ""
            return True, f"Run complete ✅ ({_fmt_ts(ts)})"
        return False, f"Run failed (HTTP {r.status_code}): {r.text[:200]}"
    except Exception as e:
        return False, f"Run failed ❌ ({e})"


def api_latest(base_url: str) -> tuple[bool, dict | None, str]:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/metrics/latest", timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return False, None, f"Fetch failed (HTTP {r.status_code}): {r.text[:200]}"
        data = r.json()
        if data.get("status") == "empty":
            return False, None, "No snapshots yet. Click **Run live check now**."
        metrics = data.get("metrics") or {}
        return True, metrics, "Latest snapshot loaded ✅"
    except Exception as e:
        return False, None, f"Fetch failed ❌ ({e})"


def compute_risk_score(metrics: dict) -> int:
    """
    If backend already supplies risk_score, use it.
    Else compute a simple weighted score.
    """
    if "risk_score" in metrics:
        return _safe_int(metrics.get("risk_score"), 0)

    mm = _safe_int(metrics.get("missing_managers"), 0)
    inv = _safe_int(metrics.get("invalid_org_assignments"), 0)
    me = _safe_int(metrics.get("missing_emails"), 0)
    iu = _safe_int(metrics.get("inactive_users"), 0)

    # Simple weights (tune anytime)
    score = (mm * 2) + (inv * 1) + (me * 1) + (iu * 1)
    return int(score)


def metrics_kpis(metrics: dict) -> dict:
    """
    Normalize common keys from backend to what UI expects.
    Adjust these if your backend uses different names.
    """
    m = _safe_dict(metrics)

    return {
        "active_users": _safe_int(m.get("active_users") or m.get("users_active")),
        "empjob_rows": _safe_int(m.get("empjob_rows") or m.get("empJob_rows") or m.get("empjob_count")),
        "missing_managers": _safe_int(m.get("missing_managers") or m.get("missing_manager_count")),
        "invalid_org": _safe_int(m.get("invalid_org_assignments") or m.get("invalid_org") or m.get("invalid_org_count")),
        "missing_emails": _safe_int(m.get("missing_emails") or m.get("missing_email_count")),
        # NEW
        "contingent_workers": _safe_int(m.get("contingent_workers") or m.get("contingent_worker_count")),
        "inactive_users": _safe_int(m.get("inactive_users") or m.get("users_inactive") or m.get("inactive_user_count")),
        "snapshot_time_utc": (m.get("snapshot_time_utc") or m.get("snapshotTimeUtc") or ""),
        "raw": m,
    }


def build_pdf_summary(metrics: dict, include_samples: bool) -> bytes:
    """
    Minimal PDF summary using reportlab (works in Streamlit).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    k = metrics_kpis(metrics)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    y = h - 48
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "SuccessFactors EC Go-Live Gates — Summary")
    y -= 18

    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Snapshot: { _fmt_ts(k['snapshot_time_utc']) }")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "KPIs")
    y -= 14

    c.setFont("Helvetica", 10)
    rows = [
        ("Active users", k["active_users"]),
        ("EmpJob rows", k["empjob_rows"]),
        ("Contingent workers", k["contingent_workers"]),
        ("Inactive users", k["inactive_users"]),
        ("Missing managers", k["missing_managers"]),
        ("Invalid org assignments", k["invalid_org"]),
        ("Missing emails", k["missing_emails"]),
        ("Risk score", compute_risk_score(k["raw"])),
    ]

    for label, val in rows:
        c.drawString(50, y, f"- {label}: {val}")
        y -= 13
        if y < 80:
            c.showPage()
            y = h - 48
            c.setFont("Helvetica", 10)

    if include_samples:
        raw = k["raw"]

        def dump_sample(title, items):
            nonlocal y
            items = _safe_list(items)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, y, title)
            y -= 14
            c.setFont("Helvetica", 9)
            if not items:
                c.drawString(50, y, "(no sample data available)")
                y -= 12
                return
            for it in items[:25]:
                line = str(it)
                if len(line) > 120:
                    line = line[:117] + "..."
                c.drawString(50, y, f"- {line}")
                y -= 11
                if y < 80:
                    c.showPage()
                    y = h - 48
                    c.setFont("Helvetica", 9)

        # Common sample keys (adjust if your backend differs)
        dump_sample("Missing emails (sample)", raw.get("missing_emails_sample") or raw.get("missingEmailsSample"))
        dump_sample("Duplicate emails (sample)", raw.get("duplicate_emails_sample") or raw.get("duplicateEmailsSample"))
        dump_sample("Missing managers (sample)", raw.get("missing_managers_sample") or raw.get("missingManagersSample"))
        dump_sample("Invalid org assignments (sample)", raw.get("invalid_org_sample") or raw.get("invalidOrgSample"))
        dump_sample("Inactive users (sample)", raw.get("inactive_users_sample") or raw.get("inactiveUsersSample"))
        dump_sample("Contingent workers (sample)", raw.get("contingent_workers_sample") or raw.get("contingentWorkersSample"))

    c.showPage()
    c.save()
    return buf.getvalue()


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="SuccessFactors EC Go-Live Gates", layout="wide")

st.title("✅ SuccessFactors EC Go-Live Gates (Streamlit UI + Render API)")

with st.sidebar:
    st.header("Connection")
    backend_url = st.text_input("Backend URL", value=st.session_state.get("backend_url", DEFAULT_BACKEND_URL))
    st.session_state["backend_url"] = backend_url

    ok, msg = api_health(backend_url)
    st.success(msg) if ok else st.error(msg)

    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    st.divider()
    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=st.session_state.get("auto_refresh", False))
    st.session_state["auto_refresh"] = auto_refresh
    refresh_seconds = st.slider("Refresh every (seconds)", 10, 120, 30, step=5, disabled=not auto_refresh)

    st.divider()
    st.header("PDF export")
    include_samples = st.toggle("Include samples in PDF", value=st.session_state.get("include_samples", False))
    st.session_state["include_samples"] = include_samples

# State
if "latest_metrics" not in st.session_state:
    st.session_state["latest_metrics"] = None
if "prev_metrics" not in st.session_state:
    st.session_state["prev_metrics"] = None

# Header status bar
status_placeholder = st.empty()

# Actions row
col_a, col_b, col_c = st.columns([1.2, 1.2, 2.6])
with col_a:
    if st.button("🔄 Run live check now", use_container_width=True):
        ok_run, msg_run = api_run_now(backend_url)
        status_placeholder.success(msg_run) if ok_run else status_placeholder.error(msg_run)
        # After run, refresh latest
        ok_latest, metrics, msg_latest = api_latest(backend_url)
        if ok_latest:
            st.session_state["prev_metrics"] = st.session_state["latest_metrics"]
            st.session_state["latest_metrics"] = metrics
            status_placeholder.success("Latest snapshot updated ✅")
        else:
            status_placeholder.warning(msg_latest)

with col_b:
    if st.button("🧾 Refresh latest snapshot", use_container_width=True):
        ok_latest, metrics, msg_latest = api_latest(backend_url)
        if ok_latest:
            st.session_state["prev_metrics"] = st.session_state["latest_metrics"]
            st.session_state["latest_metrics"] = metrics
            status_placeholder.success(msg_latest)
        else:
            status_placeholder.warning(msg_latest)

with col_c:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

# Auto refresh
if auto_refresh:
    time.sleep(0.2)  # keeps UI responsive
    # Only refresh if we already have something; otherwise don't spam the backend
    if st.session_state["latest_metrics"] is not None:
        now = time.time()
        last = st.session_state.get("_last_refresh", 0.0)
        if now - last >= float(refresh_seconds):
            ok_latest, metrics, _ = api_latest(backend_url)
            if ok_latest:
                st.session_state["prev_metrics"] = st.session_state["latest_metrics"]
                st.session_state["latest_metrics"] = metrics
            st.session_state["_last_refresh"] = now

metrics = st.session_state["latest_metrics"]
if not metrics:
    st.warning("No snapshot loaded yet. Click **Run live check now**.")
    st.stop()

k = metrics_kpis(metrics)
prev = metrics_kpis(st.session_state["prev_metrics"]) if st.session_state["prev_metrics"] else None

# KPI Row (NOW 8 tiles)
kpi_cols = st.columns(8)

kpi_cols[0].metric("Active users", k["active_users"])
kpi_cols[1].metric("EmpJob rows", k["empjob_rows"])

# NEW
kpi_cols[2].metric("Contingent workers", k["contingent_workers"])
kpi_cols[3].metric("Inactive users", k["inactive_users"])

# Existing checks (with optional delta)
def _delta(curr_key: str) -> str | None:
    if not prev:
        return None
    return str(k[curr_key] - prev[curr_key])

kpi_cols[4].metric("Missing managers", k["missing_managers"], delta=_delta("missing_managers"))
kpi_cols[5].metric("Invalid org", k["invalid_org"], delta=_delta("invalid_org"))
kpi_cols[6].metric("Missing emails", k["missing_emails"])
kpi_cols[7].metric("Risk score", compute_risk_score(k["raw"]))

st.caption(f"Snapshot UTC: { _fmt_ts(k['snapshot_time_utc']) }")

# PDF download
pdf_bytes = build_pdf_summary(k["raw"], include_samples=include_samples)
st.download_button(
    "⬇️ Download PDF summary",
    data=pdf_bytes,
    file_name="sf_ec_gates_summary.pdf",
    mime="application/pdf",
    help="PDF is a summary (no raw JSON dump). Enable samples only if you want them included.",
)

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🗂️ Org checks", "👤 Manager checks", "🔎 Raw JSON"])

raw = k["raw"]

with tab1:
    st.subheader("Missing emails (sample)")
    missing_emails_sample = raw.get("missing_emails_sample") or raw.get("missingEmailsSample") or []
    df1 = pd.DataFrame(missing_emails_sample)
    if df1.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df1, use_container_width=True)

    st.subheader("Duplicate emails (sample)")
    dup_emails_sample = raw.get("duplicate_emails_sample") or raw.get("duplicateEmailsSample") or []
    df2 = pd.DataFrame(dup_emails_sample)
    if df2.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df2, use_container_width=True)

with tab2:
    st.subheader("Invalid org assignments (sample)")
    invalid_org_sample = raw.get("invalid_org_sample") or raw.get("invalidOrgSample") or []
    df = pd.DataFrame(invalid_org_sample)
    if df.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df, use_container_width=True)

with tab3:
    st.subheader("Missing managers (sample)")
    missing_mgr_sample = raw.get("missing_managers_sample") or raw.get("missingManagersSample") or []
    df = pd.DataFrame(missing_mgr_sample)
    if df.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df, use_container_width=True)

    st.subheader("Inactive users (sample)")
    inactive_sample = raw.get("inactive_users_sample") or raw.get("inactiveUsersSample") or []
    df = pd.DataFrame(inactive_sample)
    if df.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df, use_container_width=True)

    st.subheader("Contingent workers (sample)")
    cw_sample = raw.get("contingent_workers_sample") or raw.get("contingentWorkersSample") or []
    df = pd.DataFrame(cw_sample)
    if df.empty:
        st.info("No sample data available.")
    else:
        st.dataframe(df, use_container_width=True)

with tab4:
    st.subheader("Raw metrics JSON")
    st.code(json.dumps(raw, indent=2), language="json")
