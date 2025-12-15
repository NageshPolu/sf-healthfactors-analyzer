import os
import io
import csv
import json
from datetime import datetime

import requests
import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="SF EC Go-Live Gates (API-only)", layout="wide")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "https://sf-ec-gates-backend.onrender.com").rstrip("/")

METRICS_LATEST_URL = f"{BACKEND_BASE_URL}/metrics/latest"
RUN_URL = f"{BACKEND_BASE_URL}/run"
HEALTH_URL = f"{BACKEND_BASE_URL}/health"


# -----------------------------
# Helpers
# -----------------------------
def _safe_get(d: dict, key: str, default=None):
    return d.get(key, default) if isinstance(d, dict) else default


def _as_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _as_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def df_from_list(rows):
    if not rows:
        return pd.DataFrame()
    try:
        return pd.DataFrame(rows)
    except Exception:
        # last resort: stringify
        return pd.DataFrame([{"row": json.dumps(r)} for r in rows])


def dict_to_sorted_df(d: dict, key_name="field", val_name="count"):
    if not d:
        return pd.DataFrame(columns=[key_name, val_name])
    items = [{"field": k, "count": v} for k, v in d.items()]
    df = pd.DataFrame(items).sort_values("count", ascending=False)
    df.columns = [key_name, val_name]
    return df


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_latest_metrics():
    r = requests.get(METRICS_LATEST_URL, timeout=60)
    r.raise_for_status()
    data = r.json()

    # Your backend may return either:
    # { "metrics": {...} } or the metrics dict directly
    if isinstance(data, dict) and "metrics" in data and isinstance(data["metrics"], dict):
        return data["metrics"]
    return data


def trigger_run():
    # Some backends may return plain text on error; keep it safe
    r = requests.post(RUN_URL, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"/run failed ({r.status_code}): {r.text[:500]}")
    try:
        return r.json()
    except Exception:
        return {"status": "ok", "raw": r.text[:500]}


def format_utc_iso(iso_str: str) -> str:
    if not iso_str:
        return "Unknown"
    try:
        # keeps it simple; don’t assume tz parsing libs exist
        return iso_str.replace("T", " ").replace("+00:00", " UTC")
    except Exception:
        return str(iso_str)


def build_executive_pdf(metrics: dict, include_drilldowns: bool) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def write_line(text, x, y, size=12, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, text)

    x = 2 * cm
    y = height - 2.2 * cm

    title = "SuccessFactors EC Go-Live Gates (API-only)"
    snapshot = format_utc_iso(_safe_get(metrics, "snapshot_time_utc", ""))

    active_users = _as_int(_safe_get(metrics, "active_users", 0))
    mmc = _as_int(_safe_get(metrics, "missing_manager_count", 0))
    mmp = _as_float(_safe_get(metrics, "missing_manager_pct", 0.0))
    ioc = _as_int(_safe_get(metrics, "invalid_org_count", 0))
    iop = _as_float(_safe_get(metrics, "invalid_org_pct", 0.0))
    mec = _as_int(_safe_get(metrics, "missing_email_count", 0))
    dec = _as_int(_safe_get(metrics, "duplicate_email_count", 0))
    risk = _as_int(_safe_get(metrics, "risk_score", 0))

    write_line(title, x, y, size=20, bold=True)
    y -= 1.0 * cm
    write_line(f"Snapshot (UTC): {snapshot}", x, y, size=12)
    y -= 1.2 * cm

    write_line("Executive Summary", x, y, size=16, bold=True)
    y -= 0.8 * cm
    write_line(f"Active users: {active_users}", x, y)
    y -= 0.55 * cm
    write_line(f"Missing managers: {mmc} ({mmp}%)", x, y)
    y -= 0.55 * cm
    write_line(f"Invalid org assignments: {ioc} ({iop}%)", x, y)
    y -= 0.55 * cm
    write_line(f"Missing emails: {mec}", x, y)
    y -= 0.55 * cm
    write_line(f"Duplicate emails (extra occurrences): {dec}", x, y)
    y -= 0.55 * cm
    write_line(f"Go-Live Risk Score: {risk} / 100", x, y, bold=True)
    y -= 1.0 * cm

    # Org distribution (safe)
    write_line("Org Missing Field Distribution", x, y, size=14, bold=True)
    y -= 0.7 * cm
    org_counts = _safe_get(metrics, "org_missing_field_counts", {}) or {}
    if not org_counts or all((_as_int(v, 0) == 0 for v in org_counts.values())):
        write_line("No data available.", x, y)
        y -= 0.6 * cm
    else:
        df_org = dict_to_sorted_df(org_counts, "field", "count")
        top_rows = df_org.head(10).to_dict(orient="records")
        for row in top_rows:
            write_line(f"- {row['field']}: {row['count']}", x, y)
            y -= 0.5 * cm
            if y < 2.5 * cm:
                c.showPage()
                y = height - 2.2 * cm

    if include_drilldowns:
        c.showPage()
        y = height - 2.2 * cm
        write_line("Drilldowns (PII may be present)", x, y, size=16, bold=True)
        y -= 0.8 * cm

        def render_list_section(section_title, rows, max_rows=25):
            nonlocal y
            write_line(section_title, x, y, size=13, bold=True)
            y -= 0.6 * cm
            if not rows:
                write_line("No rows returned.", x, y)
                y -= 0.6 * cm
                return
            for r in rows[:max_rows]:
                txt = json.dumps(r, ensure_ascii=False)
                # truncate long lines
                if len(txt) > 140:
                    txt = txt[:140] + "..."
                write_line(txt, x, y, size=9)
                y -= 0.45 * cm
                if y < 2.5 * cm:
                    c.showPage()
                    y = height - 2.2 * cm

        render_list_section("Invalid Org — Sample (Top 25)", _safe_get(metrics, "invalid_org_sample", []) or [])
        render_list_section("Missing Manager — Sample (Top 25)", _safe_get(metrics, "missing_manager_sample", []) or [])
        render_list_section("Missing Email — Sample (Top 25)", _safe_get(metrics, "missing_email_sample", []) or [])
        render_list_section("Duplicate Email — Sample (Top 25)", _safe_get(metrics, "duplicate_email_sample", []) or [])

    c.setFont("Helvetica-Oblique", 10)
    c.drawString(x, 1.6 * cm, "Generated automatically from SuccessFactors OData snapshots. No manual exports.")
    c.save()

    return buf.getvalue()


# -----------------------------
# UI
# -----------------------------
st.title("SF EC Go-Live Gates (API-only)")

with st.sidebar:
    st.subheader("Backend")
    st.write("Base URL:")
    st.code(BACKEND_BASE_URL)

    colA, colB = st.columns(2)
    with colA:
        if st.button("🔄 Refresh", use_container_width=True):
            fetch_latest_metrics.clear()
            st.rerun()

    with colB:
        if st.button("▶️ Run now", use_container_width=True):
            try:
                with st.spinner("Triggering backend snapshot..."):
                    trigger_run()
                fetch_latest_metrics.clear()
                st.success("Snapshot triggered. Refreshing…")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    include_drilldowns_pdf = st.checkbox("Include drilldowns in PDF (may include PII)", value=False)


# Fetch metrics
try:
    metrics = fetch_latest_metrics()
except Exception as e:
    st.error(f"Unable to load metrics from backend: {e}")
    st.stop()

snapshot_time = _safe_get(metrics, "snapshot_time_utc", "")
st.caption(f"Last snapshot (UTC): {format_utc_iso(snapshot_time)}")


# KPIs
active_users = _as_int(_safe_get(metrics, "active_users", 0))
missing_manager_count = _as_int(_safe_get(metrics, "missing_manager_count", 0))
missing_manager_pct = _as_float(_safe_get(metrics, "missing_manager_pct", 0.0))
invalid_org_count = _as_int(_safe_get(metrics, "invalid_org_count", 0))
invalid_org_pct = _as_float(_safe_get(metrics, "invalid_org_pct", 0.0))
missing_email_count = _as_int(_safe_get(metrics, "missing_email_count", 0))
duplicate_email_count = _as_int(_safe_get(metrics, "duplicate_email_count", 0))
risk_score = _as_int(_safe_get(metrics, "risk_score", 0))

k1, k2, k3, k4 = st.columns(4)
k1.metric("Active users", f"{active_users}")
k2.metric("Missing managers", f"{missing_manager_count} ({missing_manager_pct}%)")
k3.metric("Invalid org", f"{invalid_org_count} ({invalid_org_pct}%)")
k4.metric("Go-Live Risk Score", f"{risk_score} / 100")

k5, k6 = st.columns(2)
k5.metric("Missing emails", f"{missing_email_count}")
k6.metric("Duplicate emails (extra occurrences)", f"{duplicate_email_count}")

st.divider()
st.header("Drilldowns")


# -----------------------------
# Invalid Org sample
# -----------------------------
left, right = st.columns(2)

with left:
    st.subheader("Invalid Org — sample rows")
    invalid_org_sample = _safe_get(metrics, "invalid_org_sample", []) or []
    df_invalid = df_from_list(invalid_org_sample)
    if df_invalid.empty:
        st.info("No invalid-org sample returned (or backend didn't provide it).")
    else:
        st.dataframe(df_invalid, use_container_width=True, height=340)
        st.download_button(
            "Download Invalid Org CSV",
            data=df_to_csv_bytes(df_invalid),
            file_name="invalid_org_sample.csv",
            mime="text/csv",
            use_container_width=True,
        )

with right:
    st.subheader("Missing Manager — sample rows")
    missing_mgr_sample = _safe_get(metrics, "missing_manager_sample", []) or []
    df_mm = df_from_list(missing_mgr_sample)
    if df_mm.empty:
        st.info("No missing-manager sample returned (or backend didn't provide it).")
    else:
        st.dataframe(df_mm, use_container_width=True, height=340)
        st.download_button(
            "Download Missing Manager CSV",
            data=df_to_csv_bytes(df_mm),
            file_name="missing_manager_sample.csv",
            mime="text/csv",
            use_container_width=True,
        )


# -----------------------------
# Org missing field distribution
# -----------------------------
st.subheader("Which org fields are missing most?")
org_counts = _safe_get(metrics, "org_missing_field_counts", {}) or {}
df_org = dict_to_sorted_df(org_counts, "orgField", "missingCount")

if df_org.empty or df_org["missingCount"].sum() == 0:
    st.info("No org field stats returned.")
else:
    st.dataframe(df_org, use_container_width=True, height=260)
    st.download_button(
        "Download Org Missing Field Stats CSV",
        data=df_to_csv_bytes(df_org),
        file_name="org_missing_field_counts.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()

# -----------------------------
# Email drilldowns
# -----------------------------
e1, e2 = st.columns(2)

with e1:
    st.subheader("Missing Email — sample rows")
    miss_email_sample = _safe_get(metrics, "missing_email_sample", []) or []
    df_me = df_from_list(miss_email_sample)
    if df_me.empty:
        st.info("No missing-email sample returned (or count is 0).")
    else:
        st.dataframe(df_me, use_container_width=True, height=340)
        st.download_button(
            "Download Missing Email CSV",
            data=df_to_csv_bytes(df_me),
            file_name="missing_email_sample.csv",
            mime="text/csv",
            use_container_width=True,
        )

with e2:
    st.subheader("Duplicate Email — sample rows")
    dup_email_sample = _safe_get(metrics, "duplicate_email_sample", []) or []
    df_de = df_from_list(dup_email_sample)
    if df_de.empty:
        st.info("No duplicate-email sample returned (or count is 0).")
    else:
        st.dataframe(df_de, use_container_width=True, height=340)
        st.download_button(
            "Download Duplicate Email CSV",
            data=df_to_csv_bytes(df_de),
            file_name="duplicate_email_sample.csv",
            mime="text/csv",
            use_container_width=True,
        )


# -----------------------------
# PDF Export
# -----------------------------
st.divider()
st.subheader("Export")

pdf_bytes = build_executive_pdf(metrics, include_drilldowns=include_drilldowns_pdf)
st.download_button(
    "Download Executive PDF",
    data=pdf_bytes,
    file_name="sf_ec_go_live_gates_executive.pdf",
    mime="application/pdf",
)
