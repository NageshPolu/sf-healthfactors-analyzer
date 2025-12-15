import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

st.set_page_config(page_title="SF EC Go-Live Gates", layout="wide")
st.title("SF EC Go-Live Gates (API-only)")

BACKEND = st.secrets["BACKEND_BASE"]
r = requests.get(f"{BACKEND}/metrics/latest", timeout=30).json()

if r.get("status") != "ok":
    st.warning("No snapshot yet. Backend scheduler will populate soon.")
    st.stop()

m = r["metrics"]
st.caption(f"Last snapshot (UTC): {m['snapshot_time_utc']}")

c1, c2, c3 = st.columns(3)
c1.metric("Active users", m["active_users"])
c2.metric("Missing managers", f"{m['missing_manager_count']} ({m['missing_manager_pct']}%)")
c3.metric("Invalid org", f"{m['invalid_org_count']} ({m['invalid_org_pct']}%)")

st.metric("Go-Live Risk Score", f"{m['risk_score']} / 100")

# ---------- Drilldowns ----------
st.subheader("Drilldowns")

invalid_sample = m.get("invalid_org_sample", [])
missing_mgr_sample = m.get("missing_manager_sample", [])
org_counts = m.get("org_missing_field_counts", {})

left, right = st.columns(2)

with left:
    st.markdown("### Invalid Org — sample rows")
    if invalid_sample:
        df_invalid = pd.DataFrame(invalid_sample)
        st.dataframe(df_invalid, use_container_width=True, height=320)

        csv_bytes = df_invalid.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Invalid Org (CSV)",
            data=csv_bytes,
            file_name="invalid_org_sample.csv",
            mime="text/csv",
        )
    else:
        st.info("No invalid-org sample returned (or count is 0).")

with right:
    st.markdown("### Missing Manager — sample rows")
    if missing_mgr_sample:
        df_mgr = pd.DataFrame(missing_mgr_sample)
        st.dataframe(df_mgr, use_container_width=True, height=320)

        csv_bytes = df_mgr.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Missing Manager (CSV)",
            data=csv_bytes,
            file_name="missing_manager_sample.csv",
            mime="text/csv",
        )
    else:
        st.info("No missing-manager sample returned (or count is 0).")

st.markdown("### Which org fields are missing most?")
if org_counts:
    df_counts = pd.DataFrame([{"field": k, "missing_count": v} for k, v in org_counts.items()]).sort_values("missing_count", ascending=False)
    st.dataframe(df_counts, use_container_width=True, height=220)
else:
    st.info("No org field stats returned.")

# ---------- PDF Export ----------
def build_pdf(metrics: dict) -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = []

    story.append(Paragraph("<b>SuccessFactors EC Go-Live Gates (API-only)</b>", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Snapshot (UTC): {metrics.get('snapshot_time_utc','')}", styles["Normal"]))
    story.append(Spacer(1, 10))

    # Summary
    story.append(Paragraph("<b>Executive Summary</b>", styles["Heading2"]))
    story.append(Paragraph(f"Active users: {metrics.get('active_users')}", styles["Normal"]))
    story.append(Paragraph(f"Missing managers: {metrics.get('missing_manager_count')} ({metrics.get('missing_manager_pct')}%)", styles["Normal"]))
    story.append(Paragraph(f"Invalid org assignments: {metrics.get('invalid_org_count')} ({metrics.get('invalid_org_pct')}%)", styles["Normal"]))
    story.append(Paragraph(f"Go-Live Risk Score: {metrics.get('risk_score')} / 100", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Org missing distribution
    story.append(Paragraph("<b>Org Missing Field Distribution</b>", styles["Heading2"]))
    org_counts_local = metrics.get("org_missing_field_counts", {})
    if org_counts_local:
        rows = [["Field", "Missing Count"]]
        for k, v in sorted(org_counts_local.items(), key=lambda x: x[1], reverse=True):
            rows.append([k, str(v)])
        t = Table(rows, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("PADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No data available.", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Invalid org sample table (first 20)
    story.append(Paragraph("<b>Invalid Org — Sample (Top 20)</b>", styles["Heading2"]))
    invalid_local = metrics.get("invalid_org_sample", [])[:20]
    if invalid_local:
        rows = [["userId", "missingFields", "company", "businessUnit", "division", "department", "location"]]
        for r in invalid_local:
            rows.append([
                str(r.get("userId","")),
                str(r.get("missingFields","")),
                str(r.get("company","")),
                str(r.get("businessUnit","")),
                str(r.get("division","")),
                str(r.get("department","")),
                str(r.get("location","")),
            ])
        t = Table(rows, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("PADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No invalid org records in sample.", styles["Normal"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("<i>Generated automatically from SuccessFactors OData snapshots. No manual exports.</i>", styles["Normal"]))

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf

st.subheader("Export")
pdf_bytes = build_pdf(m)
st.download_button(
    "Download Executive PDF",
    data=pdf_bytes,
    file_name=f"SF_EC_GoLive_Gates_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf",
    mime="application/pdf",
)
