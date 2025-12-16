import os
import json
from io import BytesIO
from datetime import datetime

import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="SF EC Go-Live Gates", layout="wide")


# ----------------------------
# Config
# ----------------------------
API_BASE_URL = st.secrets.get("API_BASE_URL", os.getenv("API_BASE_URL", "")).rstrip("/")
API_TIMEOUT_GET = 60
API_TIMEOUT_POST = 180

if not API_BASE_URL:
    st.error("Missing API_BASE_URL. Add it in Streamlit Secrets (Settings → Secrets).")
    st.stop()


# ----------------------------
# API helpers
# ----------------------------
def api_request(method: str, path: str, payload=None):
    url = f"{API_BASE_URL}{path}"
    try:
        if method.upper() == "GET":
            r = requests.get(url, timeout=API_TIMEOUT_GET)
        else:
            r = requests.post(url, json=payload, timeout=API_TIMEOUT_POST)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        # Show API error body if available
        try:
            detail = r.text[:1000]  # noqa: F821
        except Exception:
            detail = ""
        raise RuntimeError(f"API HTTP error: {e}\n{detail}") from e
    except Exception as e:
        raise RuntimeError(f"API connection error: {e}") from e


@st.cache_data(ttl=20)
def get_health():
    return api_request("GET", "/health")


def run_now():
    return api_request("POST", "/run")


def get_latest():
    return api_request("GET", "/metrics/latest")


# ----------------------------
# PDF export (summary only)
# ----------------------------
def build_pdf_bytes(metrics: dict, include_samples: bool = False) -> bytes:
    """
    Creates a clean PDF summary.
    If reportlab isn't installed, it raises ImportError (we show a helpful message).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def line(y, text, size=10, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(40, y, str(text))

    y = h - 50
    line(y, "SuccessFactors EC Go-Live Gates — Snapshot", 16, bold=True)
    y -= 22

    snap = metrics.get("snapshot_time_utc", "")
    line(y, f"Snapshot (UTC): {snap}", 10)
    y -= 18

    # KPI block
    kpis = [
        ("Active users", metrics.get("active_users", 0)),
        ("EmpJob rows", metrics.get("current_empjob_rows", 0)),
        ("Missing managers", f"{metrics.get('missing_manager_count', 0)} ({metrics.get('missing_manager_pct', 0)}%)"),
        ("Invalid org", f"{metrics.get('invalid_org_count', 0)} ({metrics.get('invalid_org_pct', 0)}%)"),
        ("Missing emails", metrics.get("missing_email_count", 0)),
        ("Duplicate emails", metrics.get("duplicate_email_count", 0)),
        ("Risk score", metrics.get("risk_score", 0)),
    ]

    line(y, "Key metrics", 12, bold=True)
    y -= 16
    for k, v in kpis:
        line(y, f"• {k}: {v}", 10)
        y -= 14

    y -= 8
    line(y, "Org missing field counts", 12, bold=True)
    y -= 16
    org_counts = metrics.get("org_missing_field_counts", {}) or {}
    for k, v in org_counts.items():
        line(y, f"• {k}: {v}", 10)
        y -= 14

    if include_samples:
        y -= 10
        line(y, "Samples (limited)", 12, bold=True)
        y -= 16

        def add_sample(title, rows, cols=("userId",), max_rows=10):
            nonlocal y
            line(y, title, 11, bold=True)
            y -= 14
            for i, r in enumerate(rows[:max_rows]):
                bits = []
                for col in cols:
                    bits.append(f"{col}={r.get(col)}")
                line(y, f"• {', '.join(bits)}", 9)
                y -= 12
                if y < 80:
                    c.showPage()
                    y = h - 50

        add_sample("Missing manager", metrics.get("missing_manager_sample", []) or [], cols=("userId", "managerId"))
        add_sample("Invalid org", metrics.get("invalid_org_sample", []) or [], cols=("userId", "missingFields"))
        add_sample("Missing email", metrics.get("missing_email_sample", []) or [], cols=("userId", "username"))
        add_sample("Duplicate emails", metrics.get("duplicate_email_sample", []) or [], cols=("email", "count"))

    c.showPage()
    c.save()
    return buf.getvalue()


# ----------------------------
# UI
# ----------------------------
st.title("✅ SuccessFactors EC Go-Live Gates (Streamlit UI + Render API)")

with st.sidebar:
    st.header("Connection")
    st.code(API_BASE_URL, language="text")
    st.caption("Streamlit calls Render. Render calls SuccessFactors.")

    auto_refresh = st.toggle("Auto-refresh latest snapshot", value=False)
    refresh_seconds = st.slider("Refresh every (seconds)", 15, 120, 30, disabled=not auto_refresh)

    st.divider()
    st.header("PDF export")
    include_samples_in_pdf = st.toggle("Include samples in PDF", value=False)

# Health
try:
    health = get_health()
    ok = bool(health.get("ok"))
    st.success("Backend reachable ✅" if ok else "Backend responded but not OK ⚠️")
except Exception as e:
    st.error(f"Backend not reachable: {e}")
    st.stop()

# Actions row
c1, c2, c3 = st.columns([1.2, 1.2, 2.6])

with c1:
    if st.button("🔄 Run live check now", use_container_width=True):
        with st.spinner("Calling backend… fetching from SuccessFactors…"):
            out = run_now()
        st.success(f"Run complete: {out.get('snapshot_time_utc', '')}")
        st.cache_data.clear()
        st.rerun()

with c2:
    if st.button("📥 Refresh latest snapshot", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with c3:
    st.info("Tip: Use **Run live check now** to pull real-time SF data via Render, then view it below.")

# Auto refresh
if auto_refresh:
    st.caption(f"Auto-refresh enabled: every {refresh_seconds}s")
    st.autorefresh(interval=refresh_seconds * 1000, key="auto_refresh_key")

# Fetch latest snapshot
data = get_latest()
if data.get("status") != "ok":
    st.warning("No snapshots yet. Click **Run live check now**.")
    st.stop()

m = data["metrics"] or {}

# KPI tiles
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Active users", m.get("active_users", 0))
k2.metric("EmpJob rows", m.get("current_empjob_rows", 0))
k3.metric("Missing managers", m.get("missing_manager_count", 0), f'{m.get("missing_manager_pct", 0)}%')
k4.metric("Invalid org", m.get("invalid_org_count", 0), f'{m.get("invalid_org_pct", 0)}%')
k5.metric("Missing emails", m.get("missing_email_count", 0))
k6.metric("Risk score", m.get("risk_score", 0))

st.caption(f"Snapshot UTC: {m.get('snapshot_time_utc', '')}")

# PDF download (clean summary)
pdf_col1, pdf_col2 = st.columns([1.2, 3.8])
with pdf_col1:
    try:
        pdf_bytes = build_pdf_bytes(m, include_samples=include_samples_in_pdf)
        fname = f"sf_ec_gates_{m.get('snapshot_time_utc','snapshot').replace(':','-')}.pdf"
        st.download_button(
            "⬇️ Download PDF summary",
            data=pdf_bytes,
            file_name=fname,
            mime="application/pdf",
            use_container_width=True,
        )
    except ImportError:
        st.warning("PDF export requires 'reportlab'. Add it to requirements.txt.")
with pdf_col2:
    st.caption("PDF is a **summary** (no raw JSON dump). Enable samples only if you want them included.")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📧 Email hygiene", "🏢 Org checks", "👤 Manager checks", "🔎 Raw JSON"])

# Email hygiene
with tab1:
    left, right = st.columns(2)

    missing_rows = m.get("missing_email_sample", []) or []
    dup_rows = m.get("duplicate_email_sample", []) or []

    with left:
        st.subheader("Missing emails (sample)")
        df = pd.DataFrame(missing_rows)
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "Download missing emails CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="missing_emails_sample.csv",
            mime="text/csv",
        )

    with right:
        st.subheader("Duplicate emails (sample)")
        df2 = pd.DataFrame(dup_rows)
        st.dataframe(df2, use_container_width=True)
        st.download_button(
            "Download duplicate emails CSV",
            data=df2.to_csv(index=False).encode("utf-8"),
            file_name="duplicate_emails_sample.csv",
            mime="text/csv",
        )

# Org checks
with tab2:
    st.subheader("Org missing field counts")
    st.json(m.get("org_missing_field_counts", {}) or {})

    st.subheader("Invalid org sample")
    inv = pd.DataFrame(m.get("invalid_org_sample", []) or [])
    st.dataframe(inv, use_container_width=True)
    st.download_button(
        "Download invalid org CSV",
        data=inv.to_csv(index=False).encode("utf-8"),
        file_name="invalid_org_sample.csv",
        mime="text/csv",
    )

# Manager checks
with tab3:
    st.subheader("Missing manager sample")
    mm = pd.DataFrame(m.get("missing_manager_sample", []) or [])
    st.dataframe(mm, use_container_width=True)
    st.download_button(
        "Download missing managers CSV",
        data=mm.to_csv(index=False).encode("utf-8"),
        file_name="missing_manager_sample.csv",
        mime="text/csv",
    )

# Raw JSON (for debugging only)
with tab4:
    st.warning("Debug view. Avoid sharing publicly if it contains sensitive IDs.")
    st.json(m)
